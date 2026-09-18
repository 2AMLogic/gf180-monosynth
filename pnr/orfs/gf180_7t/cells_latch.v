// 7-track copy of OpenROAD-flow-scripts platforms/gf180/cells_latch.v (26Q3-296-gda37dce1c), with
// gf180mcu_fd_sc_mcu9t5v0 -> gf180mcu_fd_sc_mcu7t5v0. The stock ORFS gf180 platform hard-codes the 9t
// cell names in its techmap files, so TRACK_OPTION=7t produces undriven adder outputs (yosys 'check
// -assert' fails with hundreds of 'is used but has no driver'). Selected via ADDER_MAP_FILE / LATCH_MAP_FILE.
module $_DLATCH_P_(input E, input D, output Q);
    gf180mcu_fd_sc_mcu7t5v0__latq_1 _TECHMAP_REPLACE_ (
        .D(D),
        .E(E),
        .Q(Q)
        );
endmodule

module $_DLATCH_N_(input E, input D, output Q);
    gf180mcu_fd_sc_mcu7t5v0__latsnq_1 _TECHMAP_REPLACE_ (
        .D(D),
        .E(E),
        .Q(Q)
        );
endmodule
