#!/usr/bin/env bash
# run-klt.sh -- klt synthesize + place-and-route for ladder_dp on gf180mcuD / gf180mcu_fd_sc_mcu7t5v0,
# using the provisioned prep/asic klt venv (yosys/openroad run in the pinned openroad/orfs image via
# prep/asic/bin/orfs-tool.sh). The power block above is ORFS's own platforms/gf180/openROAD/pdn/
# pdn_grid_strategy_7t_6M.cfg, transcribed field for field: without it klt places no tapcells, no
# PDN and no fillers (the "no power block" trap).
# Must be run with the repo root as cwd: the Docker wrapper mounts only prep/asic, $PWD, $PDK_ROOT.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$HERE/../../.." && pwd -P)"
ASIC="${ASIC_ROOT:-$REPO/../prep/asic}"
export PDK_ROOT="${PDK_ROOT:-$REPO/../prep/tinytapeout/pdk/ciel/gf180mcu/versions/54435919abffb937387ec956209f9cf5fd2dfbee}"
export PDK=gf180mcuD
export PATH="$ASIC/.venv/bin:$PATH"
cd "$REPO"
klt version
t0=$(date +%s); klt synthesize --pdk gf180mcuD "$HERE/synth_request.json" --format json > "$HERE/synth_response.json"; echo "synthesize: $(( $(date +%s) - t0 )) s"
# klt synthesize keeps `input signed [15:0] x_in;` from the RTL in its netlist and its own place-and-route
# then fails in OpenSTA ([ERROR STA-0171] syntax error). Strip the qualifier (a no-op for a structural
# netlist) into a sibling file that par_request.json points at.
sed -E 's/^([[:space:]]*(input|output|inout|wire|reg)[[:space:]]+)signed[[:space:]]+/\1/' "$HERE/.klt/synthesize/ladder_dp_synth.v" > "$HERE/.klt/synthesize/ladder_dp_synth_unsigned.v"
# klt synthesize's tie-cell table (_TIE_CELLS) has gf180mcu_fd_sc_mcu9t5v0 only, so for the 7t library bare
# `assign x = 1'h0;` constants survive; OpenROAD types such a net GROUND and TritonRoute refuses it
# ([ERROR DRT-0305] Net zero_ ... not routable). Replace each constant assign with a 7t tie cell.
python3 - "$HERE/.klt/synthesize/ladder_dp_synth_unsigned.v" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1]); src = p.read_text(); n = 0
def rep(m):
    global n; n += 1
    net, val = m.group(1), m.group(2)
    if val.endswith("0"): return f"  gf180mcu_fd_sc_mcu7t5v0__tiel klt_tie_lo_{n} (.ZN({net}));"
    return f"  gf180mcu_fd_sc_mcu7t5v0__tieh klt_tie_hi_{n} (.Z({net}));"
src = re.sub(r"^\s*assign\s+(\S+)\s*=\s*(1'[hb][01])\s*;", rep, src, flags=re.M)
# yosys also leaves the two `sat_s` function arguments as dangling wires assigned all-x
# (`assign \sat_s$func$...v = 28'hxxxxxxx;`); OpenSTA reads x as 0 and builds the same unroutable
# GROUND net. The wires have no loads, so drop the assigns (the polysynth RTL README documents this trap).
src, m = re.subn(r"^\s*assign\s+\S+\s*=\s*\d+'[hb]x+\s*;\n", "", src, flags=re.M)
print(f"dangling all-x assigns removed: {m}")
p.write_text(src); print(f"tie cells inserted for constant assigns: {n}")
PY
echo "signed qualifiers left: $(grep -c ' signed ' "$HERE/.klt/synthesize/ladder_dp_synth_unsigned.v" || true)"
t0=$(date +%s); klt place-and-route --pdk gf180mcuD "$HERE/par_request.json" --format json > "$HERE/par_response.json"; echo "place-and-route: $(( $(date +%s) - t0 )) s"
