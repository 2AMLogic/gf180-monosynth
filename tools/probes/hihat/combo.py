_ROOT = __import__("pathlib").Path(__file__).resolve().parents[3]
import os, sys, json
WT=str(_ROOT); SC=os.path.dirname(os.path.abspath(__file__))
sys.path[:0]=[os.path.join(WT,"model"), os.path.join(WT,"audition"), SC]
import numpy as np, audio_measure as am, drums_fx as dx
from dsp import SR
from modal_fixed import BP, HP
from hh_probe import say, render, fast_band_energy, fmt, cost, gate, CY_BANDS, HW_CY, unity_amp, sallen_key_hp
f_hh1,q_hh1 = sallen_key_hp(1.5e-9,22e3,82e3)
img = dict(dx.kit_with_sounds("CY"))
for a,v in dx.mode_writes(dx.M_CYHI, dx.CY_HI_HZ, 4.0, dx.AMP_CY_HI, BP): img[a]=v
_,x = render(sorted(img.items()), 2.0)
shq = fast_band_energy(x, CY_BANDS)
for a,v in dx.mode_writes(16, f_hh1, q_hh1, unity_amp(f_hh1,q_hh1,HP), HP): img[a]=v
img[dx.A_PATH+dx.P_CYL]=dx.path_word(dx.SRC_TAP+dx.M_CYBP, dx.E_CYL, nl=dx.NL_SWING, att=dx.CY_ATT, dest=16)
_,y = render(sorted(img.items()), 2.0, modes=17, nums=17)
shb = fast_band_energy(y, CY_BANDS)
say("== does Hh1 buy anything ON TOP of the Q change? ==")
say(f"  machine            {fmt(HW_CY)}")
say(f"  Q 4.0 only         {fmt(shq)}  cost {cost(shq,HW_CY):5.1f}  (16 modes)")
say(f"  Q 4.0 + Hh1        {fmt(shb)}  cost {cost(shb,HW_CY):5.1f}  (17 modes)")
gate(shq,"Q 4.0 only, 16 modes"); gate(shb,"Q 4.0 + Hh1, 17 modes")
t=am.schroeder_t20(y,SR); say(f"  T20 with Hh1 {t.value*1e3 if t.ok else float('nan'):.0f} ms (machine 798)")
json.dump(dict(q_only=list(shq),q_plus_hh1=list(shb)),open(os.path.join(SC,"hh_combo.json"),"w"),default=float)
