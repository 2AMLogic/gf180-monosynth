// headroom_top.v -- NOT A BOARD DESIGN. A measurement fixture, and nothing else.
//
// `make -C fpga headroom` synthesises and routes THIS instead of ulx3s_top, to
// answer one question with a number instead of an estimate:
//
//     the eight drums in the shipping build are 8 of the 808's 11 circuits.
//     Completing the kit raises drum_kit's MODES from 12 to 16 and NUMS from
//     6 to 11. Does the finished instrument still fit an ECP5 25F?
//
// Same wrapper as the ULX3S board top -- same PLL, same pins, same LPF -- with
// synth_top's drum parameters overridden. Nothing else differs, so the
// difference between fpga/reports/ecp5_25f.txt and
// fpga/reports/ecp5_25f_headroom.txt is the drum growth and only that.
//
// Do not program this. It is not the instrument: no host, no register map
// rework (see docs/fpga-build.md on the A_MODE/A_RESET collision at MODES=16),
// and the extra modes are unpopulated.
`default_nettype none
module headroom_top #(
    parameter POR_BITS   = 12,
    parameter SIM_NO_PLL = 0,
    parameter MODES      = 16,      // 12 today; 16 completes the 808
    parameter NUMS       = 11       // 6 today; 11 completes the 808
)(
    input  wire       clk_25mhz,
    input  wire       btn_fire1,
    output wire [7:0] led,
    output wire       wifi_gpio0,
    input  wire       spi_sck,
    input  wire       spi_mosi,
    input  wire       spi_cs_n,
    output wire       spi_miso,
    output wire       i2s_bclk,
    output wire       i2s_lrclk,
    output wire       i2s_sdata
);
    assign wifi_gpio0 = 1'b1;
    wire clk_core, pll_locked;
    generate if (SIM_NO_PLL) begin : g_nopll
        assign clk_core = clk_25mhz; assign pll_locked = 1'b1;
    end else begin : g_pll
        wire clkop_unused;
        (* FREQUENCY_PIN_CLKI="25" *) (* FREQUENCY_PIN_CLKOP="25" *)
        (* FREQUENCY_PIN_CLKOS="12.288136" *)
        (* ICP_CURRENT="12" *) (* LPF_RESISTOR="8" *)
        (* MFG_ENABLE_FILTEROPAMP="1" *) (* MFG_GMCREF_SEL="2" *)
        EHXPLLL #(
            .PLLRST_ENA("DISABLED"), .INTFB_WAKE("DISABLED"),
            .STDBY_ENABLE("DISABLED"), .DPHASE_SOURCE("DISABLED"),
            .OUTDIVIDER_MUXA("DIVA"), .OUTDIVIDER_MUXB("DIVB"),
            .OUTDIVIDER_MUXC("DIVC"), .OUTDIVIDER_MUXD("DIVD"),
            .CLKI_DIV(1),
            .CLKOP_ENABLE("ENABLED"), .CLKOP_DIV(29), .CLKOP_CPHASE(14), .CLKOP_FPHASE(0),
            .CLKOS_ENABLE("ENABLED"), .CLKOS_DIV(59), .CLKOS_CPHASE(14), .CLKOS_FPHASE(0),
            .FEEDBK_PATH("CLKOP"), .CLKFB_DIV(1)
        ) pll_i (
            .RST(1'b0), .STDBY(1'b0), .CLKI(clk_25mhz),
            .CLKOP(clkop_unused), .CLKOS(clk_core), .CLKFB(clkop_unused), .CLKINTFB(),
            .PHASESEL0(1'b0), .PHASESEL1(1'b0), .PHASEDIR(1'b1),
            .PHASESTEP(1'b1), .PHASELOADREG(1'b1), .PLLWAKESYNC(1'b0), .ENCLKOP(1'b0),
            .LOCK(pll_locked));
    end endgenerate

    reg [1:0] lock_q = 2'b00;
    reg [POR_BITS-1:0] por = {POR_BITS{1'b0}};
    wire por_done = &por;
    always @(posedge clk_core) begin
        lock_q <= {lock_q[0], pll_locked};
        if (!lock_q[1]) por <= {POR_BITS{1'b0}};
        else if (!por_done) por <= por + 1'b1;
    end
    wire rst_n = por_done & ~btn_fire1;

    synth_top #(.MODES(MODES), .NUMS(NUMS)) u_synth (
        .clk(clk_core), .rst_n_pad(rst_n),
        .sck(spi_sck), .mosi(spi_mosi), .cs_n(spi_cs_n), .miso(spi_miso),
        .bclk(i2s_bclk), .lrclk(i2s_lrclk), .sdata(i2s_sdata));

    wire [15:0] vu_sample;
    i2s_sniff u_sniff (.clk(clk_core), .rst_n(rst_n),
                       .bclk(i2s_bclk), .lrclk(i2s_lrclk), .sdata(i2s_sdata), .left(vu_sample));
    reg [15:0] peak; reg [12:0] dec; reg [21:0] hb; reg any_sound;
    wire [15:0] mag = vu_sample[15] ? ~vu_sample : vu_sample;
    always @(posedge clk_core) begin
        if (!rst_n) begin peak <= 16'd0; dec <= 13'd0; hb <= 22'd0; any_sound <= 1'b0; end
        else begin
            hb <= hb + 22'd1; dec <= dec + 13'd1;
            if (mag != 16'd0) any_sound <= 1'b1;
            if (mag > peak) peak <= mag;
            else if (dec == 13'd0) peak <= peak - {6'd0, peak[15:6]};
        end
    end
    assign led = {|peak[15:14], |peak[15:12], |peak[15:10], |peak[15:7],
                  pll_locked, por_done, hb[21], any_sound};
endmodule
`default_nettype wire
