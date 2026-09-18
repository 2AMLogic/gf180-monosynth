# Routed `synth_top` — evidence

Two different chips are recorded here, because `synth_top` changed underneath this run.

| directory | RTL | what it is |
|---|---|---|
| `placeholder-2a88c35/` | `2a88c35` | `synth_top` with `drum_section_placeholder` — the design `docs/ARCHITECTURE.md` section 10 and `docs/area-budget.md` row G describe. **Fully routed**: synthesis, floorplan, placement, CTS, detailed routing, finish, multi-corner STA. The first `synth_top` ever placed and routed. |
| `quarterslot-does-not-fit/` | `d1e5068` | `synth_top` with the **real** `drum_kit`/`drum_regs` engine, floorplanned on the quarter slot. Floorplan only: at 118.3 % utilisation there is nothing to place. |
| `joined-d1e5068/` | `d1e5068` | the same joined design on a die that holds it — two quarter slots, 3.4650 mm². **Fully routed**: 60.1 % utilisation, **0 detailed-route DRC violations**, positive setup and hold slack at tt/ss/ff. Also carries the hierarchical synthesis (`synth_stat_hier.txt`, the per-block split) and the `DONT_USE_CELLS=` synthesis (`synth_stat_x1.txt`). |

The RTL of `placeholder-2a88c35` (md5, in the order `pnr/orfs/synth_top/config.mk` listed them at
that commit):

```
7e31eb64bfb275a57c3e32a3eaed48e3  synth_top.v
ac7c82eebd52818af98ce90bd50de027  spi_ctl.v
56c3056a91bba6a11bab3dfd4ee3383b  voice_dp.v
75f6233a7bb5703b314359db9d46309b  recip_div.v
afd0a9555b74734b83e4e24a89da5973  ladder_dp_n.v
b5ce1c8e5852fb46cce20f09b469664e  i2s_tx.v
19eef123dade7c0719daece8211fd2b4  modal_dp_rom.v
d58e26131548422d2230333e1367ee00  modal_coef_rom_p8.v
```

Nothing in here is evidence that the chip computes anything (`docs/verification-rules.md` rule 3).
It is area, timing and DRC.
