#!/usr/bin/env bash
set -uo pipefail
HERE=/tmp/wt-par/pnr/orfs
cd "$HERE"
echo "########## C1 x1 (DONT_USE_CELLS empty) synth+floorplan start $(date)"
./run-orfs.sh synth_top FLOW_VARIANT=x1 DONT_USE_CELLS= synth floorplan > work/synth_top_x1_phaseA.log 2>&1
echo "########## C1 rc=$? $(date)"
tail -12 work/synth_top_x1_phaseA.log
echo "--- synth_stat tail"
tail -6 work/reports/gf180/synth_top/x1/synth_stat.txt 2>/dev/null
echo "--- synth_check"
tail -4 work/reports/gf180/synth_top/x1/synth_check.txt 2>/dev/null
python3 - <<'PY'
import json,os
L='/tmp/wt-par/pnr/orfs/work/logs/gf180/synth_top/x1'
for n in ['1_synth','2_1_floorplan']:
    p=os.path.join(L,n+'.json')
    if not os.path.exists(p): print(n,'MISSING'); continue
    d=json.load(open(p))
    for k,v in sorted(d.items()):
        if any(s in k for s in ['instance__count','instance__area','die__area','core__area','utilization','setup__ws']):
            if not k.endswith(('cover','macros','padcells')): print('   ',k,'=',v)
PY
echo "########## C1_DONE"
