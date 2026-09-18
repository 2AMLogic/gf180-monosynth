#!/usr/bin/env python3
"""check-pdn.py -- prove a routed DEF has a power grid, tap cells and fillers (the "no power block" trap).

Usage: check-pdn.py <6_final.def> [--json]
Parses COMPONENTS (instances by master / by role) and SPECIALNETS (VDD/VSS stripes per layer+shape and
via count). Pure text parsing of the DEF, no EDA tool needed. Exit 1 if any of: no followpin rails,
no strap layer above Metal1, no PDN vias, no tap/endcap cells, no filler cells.
"""
import re, sys, json, collections

def main():
    path = sys.argv[1]
    txt = open(path).read()
    # ---- components
    comp = re.search(r"COMPONENTS (\d+) ;(.*?)END COMPONENTS", txt, re.S)
    n_comp = int(comp.group(1))
    by_master = collections.Counter()
    by_role = collections.Counter()
    for m in re.finditer(r"^\s*- (\S+) (\S+)", comp.group(2), re.M):
        inst, master = m.group(1), m.group(2)
        by_master[master] += 1
        base = master.split("__", 1)[-1]
        if base.startswith("fill_"):        role = "filler"
        elif base in ("filltie", "endcap"): role = "tap/endcap"
        elif base == "antenna":            role = "antenna diode"
        elif inst.startswith("clkbuf_") or inst.startswith("clkload"): role = "clock tree buffer"
        elif inst.startswith(("hold", "rebuffer", "input", "output", "fanout", "split", "wire", "load", "max_cap", "max_length", "max_slew")): role = "timing-repair buffer/inverter"
        elif base.startswith(("dff", "sdff", "dffr", "dffs", "dffn", "latq")): role = "flip-flop/latch"
        else:                              role = "logic"
        by_role[role] += 1
    # ---- special nets
    sn = re.search(r"SPECIALNETS (\d+) ;(.*?)END SPECIALNETS", txt, re.S)
    nets = {}
    if sn:
        for block in re.split(r"^\s*- ", sn.group(2), flags=re.M)[1:]:
            name = block.split()[0]
            segs = collections.Counter(); vias = 0
            for seg in re.finditer(r"(?:ROUTED|NEW)\s+(\S+)\s+(\d+)\s*(?:\+ SHAPE (\S+))?\s*((?:\(\s*[-\d*]+\s+[-\d*]+\s*\)\s*)+)(\S+)?", block):
                layer, width, shape, pts, via = seg.groups()
                if via and via not in ("+", "NEW", ";"):
                    vias += 1; segs[(layer, "via:" + via)] += 1
                else:
                    segs[(layer, shape or "wire")] += 1
            nets[name] = {"segments": {f"{l} {s}": c for (l, s), c in sorted(segs.items())}, "vias": vias}
    n_vias_def = len(re.findall(r"^\s*- \S+", re.search(r"^VIAS (\d+) ;(.*?)END VIAS", txt, re.S | re.M).group(2), re.M)) if re.search(r"^VIAS", txt, re.M) else 0
    die = re.search(r"DIEAREA \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \)", txt)
    units = int(re.search(r"UNITS DISTANCE MICRONS (\d+)", txt).group(1))
    x0, y0, x1, y1 = (int(v) / units for v in die.groups())
    rows = len(re.findall(r"^ROW ", txt, re.M))
    out = {"def": path, "die_um": [x0, y0, x1, y1], "die_area_um2": (x1 - x0) * (y1 - y0), "rows": rows,
           "components": n_comp, "by_role": dict(by_role), "via_definitions": n_vias_def, "special_nets": nets,
           "top_masters": by_master.most_common(12)}
    # ---- verdict
    problems = []
    def has(net, pred): return any(pred(k) for k in nets.get(net, {}).get("segments", {}))
    for net in ("VDD", "VSS"):
        if net not in nets: problems.append(f"no SPECIALNET {net}"); continue
        if not has(net, lambda k: "FOLLOWPIN" in k): problems.append(f"{net}: no FOLLOWPIN rails on Metal1")
        if not has(net, lambda k: "STRIPE" in k and not k.startswith("Metal1 ")): problems.append(f"{net}: no straps above Metal1")
        if nets[net]["vias"] == 0: problems.append(f"{net}: no PDN vias")
    if by_role.get("tap/endcap", 0) == 0: problems.append("no tap/endcap cells")
    if by_role.get("filler", 0) == 0: problems.append("no filler cells")
    out["problems"] = problems
    out["verdict"] = "PASS: power grid, taps and fillers present" if not problems else "FAIL"
    if "--json" in sys.argv: print(json.dumps(out, indent=2))
    else:
        print(f"{path}\n  die {x1-x0:.2f} x {y1-y0:.2f} um = {out['die_area_um2']:.0f} um2, {rows} rows, {n_comp} components")
        for r, c in sorted(by_role.items(), key=lambda kv: -kv[1]): print(f"  {c:6d}  {r}")
        for net, d in nets.items():
            print(f"  {net}: {d['vias']} vias; " + ", ".join(f"{k} x{c}" for k, c in d["segments"].items() if "via:" not in k))
        print(f"  VIAS section: {n_vias_def} via definitions")
        print("  " + out["verdict"] + ("" if not problems else ": " + "; ".join(problems)))
    sys.exit(1 if problems else 0)

if __name__ == "__main__": main()
