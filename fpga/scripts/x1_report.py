#!/usr/bin/env python3
"""Distil rtl-sketch/build/x1ab/*.json into fpga/reports/x1_ab.txt.

Separate from x1_ab.sh so the table can be rebuilt without re-running ten
syntheses. NOTE the trap this file exists to avoid: yosys keys parameterised
modules as `$paramod$<hash>\\<name>`, so `modules.values()[0]` is a SUBMODULE,
not the top. An earlier version of this script did exactly that and reported
drum_kit at 325,388 um2 when the top is 603,118 -- the submodule modal_dp.
Always select by the exact `\\<top>` key.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
B    = os.path.join(ROOT, 'rtl-sketch', 'build', 'x1ab')

# tag -> (top module name, label)
DESIGNS = [
    ('top',      'synth_top',                'synth_top (PLACEHOLDER drums)'),
    ('plh',      'drum_section_placeholder', 'drum_section_placeholder'),
    ('kit8',     'drum_kit',                 'drum_kit MODES=8  NUMS=6'),
    ('kit12',    'drum_kit',                 'drum_kit MODES=12 NUMS=6  (shipped)'),
    ('kit16n11', 'drum_kit',                 'drum_kit MODES=16 NUMS=11 (complete 808)'),
]

def area(tag, var, top):
    """Hierarchical cell area of the TOP module, by exact key."""
    f = os.path.join(B, f'{tag}.{var}.json')
    if not os.path.exists(f):
        return None
    mods = json.load(open(f))['modules']
    key = '\\' + top
    if key not in mods:
        raise SystemExit(f'{f}: no module {key!r}; have {sorted(mods)[:4]}')
    return mods[key].get('area', 0.0)

rows, out = [], []
for tag, top, label in DESIGNS:
    a, b = area(tag, 'x1', top), area(tag, 'nox1', top)
    rows.append((label, a, b))

out.append('DONT_USE_CELLS A/B -- what excluding the *_1 drive strengths costs,')
out.append('per block. CELL area, gf180mcu_fd_sc_mcu7t5v0, tt_025C_5v00.')
out.append('SYNTHESISED, NOT placed, NOT routed.')
out.append('')
out.append(f"{'design':<42s} {'*_1 allowed':>13s} {'*_1 excluded':>13s} {'delta':>11s} {'penalty':>8s}")
for label, a, b in rows:
    if a is None or b is None:
        out.append(f'{label:<42s} {"-":>13s} {"-":>13s}')
    else:
        out.append(f'{label:<42s} {a:13.1f} {b:13.1f} {b-a:11.1f} {100*(b-a)/a:7.1f}%')
out.append('')
out.append('"*_1 allowed"  = klt\'s recipe (docs/area-budget.md uses this).')
out.append('"*_1 excluded" = ORFS\'s stock gf180 DONT_USE_CELLS, 62 cells; the ORFS')
out.append('                 synth_top base netlist contains no *_1 cell at all.')
out.append('')
out.append('synth_top here contains drum_section_placeholder, NOT drum_kit. No')
out.append('synth_top on any branch instantiates the real drum section (contract 17.23).')
out.append('')
out.append('Blocks are synthesised standalone: no cross-boundary optimisation, so')
out.append('they do not sum to a top-level number. Adding them is a PROJECTION.')
out.append('')
out.append('AREA IS NOT CORRECTNESS. docs/verification-rules.md rule 3.')
txt = '\n'.join(out) + '\n'
open(os.path.join(ROOT, 'fpga', 'reports', 'x1_ab.txt'), 'w').write(txt)
print(txt)
