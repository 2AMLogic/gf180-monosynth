#!/usr/bin/env python3
"""blockarea.py -- what the routed die is made of, from 6_final.def + the platform 7-track cell LEF.

IMPORTANT, and the reason this script has two tables: ORFS flattens before ABC, so only cells that
carry an RTL signal name survive with their hierarchy (u_voice.u_ladder.y[3]$_SDFF_...). Those are
essentially the REGISTERS. Every mapped combinational cell is renamed `_01234_` by yosys and cannot
be attributed to a block from the flat netlist at all. So:

  table 1  cell class -- the whole die, measured
  table 2  sequential cells by block -- measured, but covers only the flops
           (for a per-block total-area split, synthesise hierarchically: FLOW_VARIANT=hier
            SYNTH_HIERARCHICAL=1, reports/.../hier/synth_stat.txt)

Usage: blockarea.py <6_final.def> <cells_7t.lef>
"""
import re, sys, collections

def lef_areas(path):
    area, name = {}, None
    for line in open(path, errors="ignore"):
        m = re.match(r"\s*MACRO\s+(\S+)", line)
        if m: name = m.group(1); continue
        m = re.match(r"\s*SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", line)
        if m and name: area[name] = float(m.group(1)) * float(m.group(2)); name = None
    return area

# (regex on the instance name, bucket).  Order matters; first match wins.
BUCKETS = [
    (r"^u_voice\.u_ladder\b",        "u_voice.u_ladder  (ladder_dp_n, NCH=2)"),
    (r"^u_voice\.u_div\b",           "u_voice.u_div     (recip_div)"),
    (r"^u_voice\b",                  "u_voice           (own: oscs, mixer, ADSRs, ROMs, VCA, mix)"),
    (r"^u_drums\.u_modal\b",         "u_drums.u_modal   (modal_dp_rom, 8 presets)"),
    (r"^u_drums\b",                  "u_drums           (PLACEHOLDER sources)"),
    (r"^u_spi\b",                    "u_spi             (spi_ctl)"),
    (r"^u_i2s\b",                    "u_i2s             (i2s_tx)"),
]
def hier_bucket(inst):
    for rx, b in BUCKETS:
        if re.match(rx, inst): return b
    return "synth_top own (cyc, frame, overrun, rst sync)" if "." not in inst else "other: " + inst.split(".")[0]

def bucket(inst, master):
    ml = master.lower()
    if "__fill" in ml:    return "ZZ flow: filler cells"
    if "filltie" in ml or "__tap" in ml: return "ZZ flow: tap cells"
    if "endcap" in ml:    return "ZZ flow: endcap cells"
    if "antenna" in ml:   return "ZZ flow: antenna diode"
    if inst.startswith("clkbuf_") or inst.startswith("clknet_"):
        return "ZZ flow: clock tree (CTS)"
    for rx, b in BUCKETS:
        if re.match(rx, inst): return b
    if "." not in inst:   return "synth_top own + resizer-inserted"
    return "other: " + inst.split(".")[0]

def main():
    defp, lefp = sys.argv[1], sys.argv[2]
    area = lef_areas(lefp)
    cnt, ar = collections.Counter(), collections.Counter()
    scnt, sar = collections.Counter(), collections.Counter()
    missing = collections.Counter()
    inside = False
    for line in open(defp, errors="ignore"):
        if line.startswith("COMPONENTS"): inside = True; continue
        if line.startswith("END COMPONENTS"): break
        if not inside: continue
        m = re.match(r"\s*-\s+(\S+)\s+(\S+)", line)
        if not m: continue
        inst, master = m.group(1).replace("\\", ""), m.group(2)
        a = area.get(master)
        if a is None: missing[master] += 1; a = 0.0
        b = bucket(inst, master)
        cnt[b] += 1; ar[b] += a
        if "__dff" in master.lower() or "__sdff" in master.lower():
            sb = hier_bucket(inst)
            scnt[sb] += 1; sar[sb] += a
    tot = sum(ar.values()); totn = sum(cnt.values())
    logic = sum(v for k, v in ar.items() if not k.startswith("ZZ flow: filler"))
    print(f"instances {totn}, area {tot:,.1f} um2 (excluding fillers: {logic:,.1f} um2)")
    print()
    print("cell classes over the whole die (combinational cells are renamed `_NNNNN_` by yosys and")
    print("carry no block identity, so they all land in one bucket -- that is a property of the flow,")
    print("not a measurement of synth_top's own logic):")
    print()
    print("| bucket | instances | area um2 | % of non-filler |")
    print("|---|---:|---:|---:|")
    for b in sorted(ar, key=lambda b: -ar[b]):
        pct = 100.0 * ar[b] / logic if not b.startswith("ZZ flow: filler") else float("nan")
        print(f"| {b} | {cnt[b]:,} | {ar[b]:,.1f} | {'' if pct != pct else f'{pct:.1f}'} |")
    print()
    stot = sum(sar.values())
    print(f"sequential cells only ({sum(scnt.values()):,} flops, {stot:,.1f} um2) -- the only part of a")
    print("flattened netlist that can be attributed to a block:")
    print()
    print("| block | flops | flop area um2 | % of flops |")
    print("|---|---:|---:|---:|")
    for b in sorted(sar, key=lambda b: -sar[b]):
        print(f"| {b} | {scnt[b]:,} | {sar[b]:,.1f} | {100.0*sar[b]/stot:.1f} |")
    if missing: print("\nmasters with no LEF SIZE (counted as 0):", dict(missing))
    return 0

if __name__ == "__main__": sys.exit(main())
