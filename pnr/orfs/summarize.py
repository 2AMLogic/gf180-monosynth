#!/usr/bin/env python3
"""summarize.py -- turn an ORFS run's per-stage metric JSONs into the tables in docs/pnr-first-run.md.

Usage: summarize.py <design> [flow_variant] [--work DIR]
Reads work/logs/gf180/<design>/<variant>/{1_synth,2_1_floorplan,3_5_place_dp,4_1_cts,5_2_route,6_report}.json,
reports/.../synth_stat.txt and (if present) logs/.../sta_corners.log. Prints markdown.
"""
import json, re, sys, os, glob

def load(p):
    try: return json.load(open(p))
    except FileNotFoundError: return {}

def pick(d, suffix):
    for k, v in d.items():
        if k.endswith(suffix) and ":" not in k.split("__")[-1]: return v
    return None

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    design = args[0]; variant = args[1] if len(args) > 1 else "base"
    work = sys.argv[sys.argv.index("--work") + 1] if "--work" in sys.argv else os.path.join(os.path.dirname(os.path.abspath(__file__)), "work")
    L = f"{work}/logs/gf180/{design}/{variant}"; R = f"{work}/reports/gf180/{design}/{variant}"
    st = {s: load(f"{L}/{f}.json") for s, f in [("synth", "1_synth"), ("floorplan", "2_1_floorplan"), ("place", "3_5_place_dp"), ("cts", "4_1_cts"), ("route", "5_2_route"), ("finish", "6_report")]}
    fin = st["finish"]
    if not fin: print(f"no 6_report.json for {design}/{variant}"); return 1
    die = pick(fin, "design__die__area"); core = pick(fin, "design__core__area")
    # die is square (aspect 1): side from area
    print(f"### {design} ({variant})\n")
    print("| Stage | instances | std-cell area (um2) | utilisation | setup WNS @tt (ns) |")
    print("|---|---|---|---|---|")
    for s in ["synth", "floorplan", "place", "cts", "finish"]:
        d = st[s]
        if not d: continue
        n = pick(d, "design__instance__count"); a = pick(d, "design__instance__area"); u = pick(d, "design__instance__utilization"); ws = pick(d, "timing__setup__ws")
        note = {"synth": "yosys+ABC, DONT_USE *_1", "floorplan": "+ 0 (taps/endcaps not counted as std cells)", "place": "+ input/output buffers, resizing", "cts": "+ clock tree", "finish": "incl. fillers/taps/endcaps in count; area = std cells only"}[s]
        print(f"| {s} ({note}) | {n} | {a:,.0f} | {'' if u is None else f'{u*100:.1f} %'} | {'' if ws is None else f'{ws:+.2f}'} |")
    print()
    cls = {k.split("class:")[1]: v for k, v in fin.items() if "instance__count__class:" in k}
    cla = {k.split("class:")[1]: v for k, v in fin.items() if "instance__area__class:" in k}
    print("| Cell class (final) | count | area (um2) |"); print("|---|---|---|")
    for c in sorted(cls, key=lambda c: -cla.get(c, 0)): print(f"| {c} | {cls[c]} | {cla.get(c,0):,.1f} |")
    print()
    rt = st["route"]
    print(f"- die area **{die:,.0f} um2** ({die**0.5:.1f} x {die**0.5:.1f} um, aspect 1), core area **{core:,.0f} um2**")
    print(f"- final std-cell area {pick(fin,'design__instance__area'):,.0f} um2 = {pick(fin,'design__instance__utilization')*100:.1f} % of core; die / synth cell area = {die/pick(st['synth'],'design__instance__area'):.2f}, core / synth cell area = {core/pick(st['synth'],'design__instance__area'):.2f}")
    print(f"- routed wirelength {pick(rt,'route__wirelength'):,} um, detailed-route DRC errors {pick(rt,'route__drc_errors')}, antenna violating nets {pick(rt,'antenna__violating__nets')}, antenna diodes {pick(rt,'antenna_diodes_count')}")
    print(f"- finish (tt_025C_5v00, RCX typ): setup WNS {pick(fin,'timing__setup__ws'):+.3f} ns, hold WNS {pick(fin,'timing__hold__ws'):+.3f} ns, TNS {pick(fin,'timing__setup__tns')}/{pick(fin,'timing__hold__tns')}, setup/hold violations {pick(fin,'timing__drv__setup_violation_count')}/{pick(fin,'timing__drv__hold_violation_count')}, max slew/cap violations {pick(fin,'timing__drv__max_slew')}/{pick(fin,'timing__drv__max_cap')}, clock skew {pick(fin,'clock__skew__setup'):.3f} ns, ORFS fmax {pick(fin,'timing__fmax')/1e6:.1f} MHz, power {pick(fin,'power__total')*1e3:.2f} mW")
    sta = f"{L}/sta_corners.log"
    if os.path.exists(sta):
        txt = open(sta).read()
        print("- multi-corner STA on the routed design (`sta-corners.tcl`, per-corner OpenRCX):")
        for m in re.finditer(r"=== CORNER (\w+) setup_wns_ns=(\S+) setup_tns_ns=(\S+) hold_wns_ns=(\S+) hold_tns_ns=(\S+) implied_min_period_ns=(\S+) implied_fmax_mhz=(\S+)", txt):
            c, sw, stn, hw, htn, mp, fm = m.groups()
            name = {"tt": "tt_025C_5v00", "ss": "ss_125C_4v50", "ff": "ff_n40C_5v50"}[c]
            print(f"  - **{name}**: setup WNS {sw} ns (TNS {stn}), hold WNS {hw} ns (TNS {htn}); implied min period {mp} ns ({fm} MHz)")
    ss = f"{R}/synth_stat.txt"
    if os.path.exists(ss):
        rows = [(int(m.group(1)), m.group(2)) for m in re.finditer(r"^\s+(\d+)\s+\S+\s+\d+\s+\S+\s+gf180mcu_fd_sc_mcu7t5v0__(\S+)", open(ss).read(), re.M)]
        rows.sort(reverse=True)
        print(f"- synth cell mix (top 8 of {len(rows)} types): " + ", ".join(f"{c}x {n}" for c, n in rows[:8]))
    return 0

if __name__ == "__main__": sys.exit(main())
