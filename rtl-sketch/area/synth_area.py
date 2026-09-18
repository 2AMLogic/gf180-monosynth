#!/usr/bin/env python3
"""Hierarchical gf180mcu cell-area measurement, per module -- docs/area-budget.md.

Mirrors klt synthesize's yosys recipe (hierarchy -check; synth -top; dfflibmap
-liberty; abc -liberty; stat -liberty -json) with NO flatten unless --flatten,
so `stat` reports every submodule. Liberty: gf180mcu_fd_sc_mcu<track>t5v0,
corner tt_025C_5v00. Cell area only: no placement, no routing, no utilisation.

  GF180_PDK_REF   .../gf180mcuD/libs.ref   (the ciel/volare install)
  yosys on PATH, or OSS_CAD_SUITE=/path/to/oss-cad-suite

  synth_area.py --tag ladder --top ladder_dp ../ladder_dp.v
  synth_area.py --tag core4 --top synth_core --chparam NV=4 <polysynth>/rtl/{uart_rx,synth_voice,synth_core}.v
Results: build/area/<tag>/{synth.ys,yosys.log,stat.json,netlist.v,result.json}.
"""
import argparse, json, os, subprocess, sys
_OSS = os.environ.get('OSS_CAD_SUITE')
YOSYS = os.path.join(_OSS, 'bin', 'yosys') if _OSS else 'yosys'
PDK = os.environ.get('GF180_PDK_REF')
if not PDK:
    sys.exit('set GF180_PDK_REF to <pdk>/gf180mcuD/libs.ref')
S = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'build', 'area')
def lib(t): return f'{PDK}/gf180mcu_fd_sc_mcu{t}t5v0/lib/gf180mcu_fd_sc_mcu{t}t5v0__tt_025C_5v00.lib'
ap = argparse.ArgumentParser()
ap.add_argument('--tag', required=True); ap.add_argument('--top', required=True)
ap.add_argument('--track', default='7'); ap.add_argument('--chparam', action='append', default=[])
ap.add_argument('--define', action='append', default=[]); ap.add_argument('--flatten', action='store_true')
ap.add_argument('--booth', action='store_true'); ap.add_argument('--cwd', default=None)
ap.add_argument('--quiet', action='store_true'); ap.add_argument('--reparse', action='store_true'); ap.add_argument('src', nargs='+')
a = ap.parse_args()
out = os.path.join(S, a.tag); os.makedirs(out, exist_ok=True)
cwd = a.cwd or os.path.dirname(os.path.abspath(a.src[0]))
L = lib(a.track)
lines = []
for s in a.src:
    lines.append('read_verilog -sv ' + ''.join(f'-D{d} ' for d in a.define) + os.path.abspath(s))
if a.chparam:
    lines.append('chparam ' + ' '.join(f'-set {p.split("=")[0]} {p.split("=",1)[1]}' for p in a.chparam) + f' {a.top}')
lines.append(f'hierarchy -check -top {a.top}')
lines.append(f'synth -top {a.top}' + (' -flatten' if a.flatten else '') + (' -booth' if a.booth else ''))
lines.append(f'dfflibmap -liberty {L}')
lines.append(f'abc -liberty {L}')
lines.append('opt_clean -purge')
lines.append(f'tee -q -o {out}/stat.json stat -liberty {L} -json -top {a.top}')
lines.append(f'write_verilog -noattr {out}/netlist.v')
open(f'{out}/synth.ys', 'w').write('\n'.join(lines) + '\n')
r = subprocess.CompletedProcess([], 0, '', '') if a.reparse else subprocess.run([YOSYS, '-q', '-l', f'{out}/yosys.log', '-s', f'{out}/synth.ys'], cwd=cwd, capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout[-3000:], r.stderr[-3000:]); sys.exit(1)

d = json.load(open(f'{out}/stat.json'))
mods = {k.lstrip('\\'): v for k, v in d['modules'].items()}
def hier(m):
    """(hier_area, hier_cells) -- yosys 0.69 'area' is already hierarchical; num_cells is own incl. instances"""
    return mods[m].get('area', 0.0), None
def own_and_hier(m):
    a = mods[m].get('area', 0.0)
    child_a = 0.0; child_c = 0; own_c = 0
    for t, n in mods[m].get('num_cells_by_type', {}).items():
        t2 = t.lstrip('\\')
        if t2 in mods:
            ca, cc = own_and_hier(t2)[2:4]
            child_a += n * ca; child_c += n * cc
        else:
            own_c += n
    return a - child_a, own_c, a, own_c + child_c
rows = []
def walk(m, inst, depth):
    own_a, own_c, ta, tc = own_and_hier(m)
    rows.append((depth, inst, m, own_c, own_a, tc, ta))
    for t, n in mods[m].get('num_cells_by_type', {}).items():
        t2 = t.lstrip('\\')
        if t2 in mods:
            walk(t2, f'{n}x {t2[:40]}', depth + 1)
walk(a.top, a.top, 0)
res = {'tag': a.tag, 'top': a.top, 'track': a.track, 'liberty': os.path.basename(L), 'chparam': a.chparam,
       'defines': a.define, 'flatten': a.flatten, 'booth': a.booth,
       'total_area_um2': rows[0][6], 'total_cells': rows[0][5],
       'modules': [{'depth': r[0], 'inst': r[1], 'module': r[2], 'own_cells': r[3], 'own_area_um2': r[4],
                    'hier_cells': r[5], 'hier_area_um2': r[6]} for r in rows],
       'cells_by_type': {m: mods[m].get('num_cells_by_type', {}) for m in mods}}
json.dump(res, open(f'{out}/result.json', 'w'), indent=1)
if not a.quiet:
    print(f'== {a.tag}  top={a.top}  lib=gf180mcu_fd_sc_mcu{a.track}t5v0 tt_025C_5v00  chparam={a.chparam} def={a.define} flat={a.flatten} booth={a.booth}')
    print(f'{"instance":44} {"own cells":>9} {"own um2":>10} {"hier cells":>10} {"hier um2":>10} {"hier mm2":>9}')
    for r in rows:
        print(f'{"  "*r[0]+r[1]:44} {r[3]:9d} {r[4]:10.1f} {r[5]:10d} {r[6]:10.1f} {r[6]/1e6:9.4f}')
