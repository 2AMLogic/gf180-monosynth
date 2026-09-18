// ulx3s_top.v -- the ULX3S board wrapper around rtl-sketch/synth_top.v.
//
// NOTHING HERE IS PART OF THE ASIC. rtl-sketch/ is the chip; this file is the
// board. It adds exactly what a board has to add and nothing that changes the
// instrument:
//
//   * an ECP5 PLL, because the ULX3S oscillator is 25 MHz and synth_top is the
//     I2S MASTER -- the core clock IS the sample rate, so feeding 25 MHz in
//     runs the whole instrument at fs = 97656.25 Hz -- every voice 1229.6 cents
//     sharp, an octave plus 29.6 cents. See THE CLOCK below.
//   * a power-on reset that also waits for PLL lock;
//   * wifi_gpio0 held high, which the ULX3S requires or the on-board ESP32
//     drops into its bootloader and fights for the shared pins;
//   * an I2S sniffer driving the LEDs, so a bare board shows it is alive.
//
// THE CLOCK ------------------------------------------------------------------
// synth_top wants 12.288 MHz = 256 x 48 kHz. 12.288/25 = 1536/3125 and 3125 is
// 5^5, so with FEEDBK_PATH="CLKOP" (where Fout = Fin x CLKFB_DIV / CLKI_DIV)
// the ratio is unreachable: the only factor pair of 3125 with both terms <= 128
// is 25 x 125, and CLKI_DIV = 25 puts the phase detector at 1 MHz, below the
// ECP5's 3.125 MHz minimum.
//
// It IS reachable to +11.03 ppm by taking the core clock from the SECONDARY
// output, which has its own divider off the same VCO:
//
//     CLKI_DIV  = 1     PFD   = 25 MHz          (>= 3.125 MHz: legal)
//     CLKFB_DIV = 1     VCO   = 25 x 1 x 29
//     CLKOP_DIV = 29          = 725 MHz         (400..800 MHz: legal)
//     CLKOS_DIV = 59    CLKOS = 725/59
//                             = 12.288135593 MHz
//
//   core   12.288135593 MHz vs 12.288 MHz exactly : +11.03 ppm, +0.019 cents
//   fs     48000.530 Hz     vs 48000 Hz exactly   : +0.53 Hz
//
// That is 54x closer than the ~12.2807 MHz (-594 ppm, -1.03 cents) this
// repository's fpga/README.md previously recorded as the best available, and
// it is an order of magnitude below the +-30 ppm tolerance of the ULX3S's own
// 25 MHz oscillator -- so the crystal, not the PLL, sets the tuning error.
// The search is fpga/scripts/pll_search.py; run it to reproduce the table.
// CLKOP (25 MHz) exists only as the feedback path and drives nothing.
//
// A board that wants the sample rate exact to the crystal must supply
// 12.288 MHz directly; see docs/board-requirements.md.
`default_nettype none
module ulx3s_top #(
    parameter POR_BITS   = 12,      // reset held 2^POR_BITS core clocks after lock
    parameter SIM_NO_PLL = 0        // 1: bypass the EHXPLLL (iverilog cannot elaborate it)
)(
    input  wire       clk_25mhz,    // G2, on-board oscillator
    input  wire       btn_fire1,    // FIRE1 button: idle low (PULLMODE=DOWN), pressed = reset
    output wire [7:0] led,
    output wire       wifi_gpio0,   // must be driven high on this board

    // control link (DR 0007) -- header GN0..GN3
    input  wire       spi_sck,
    input  wire       spi_mosi,
    input  wire       spi_cs_n,
    output wire       spi_miso,

    // audio (contract 13) -- header GP0..GP2, to an external I2S DAC
    output wire       i2s_bclk,
    output wire       i2s_lrclk,
    output wire       i2s_sdata
);
    assign wifi_gpio0 = 1'b1;

    // ---- the PLL: 25 MHz -> 12.288135593 MHz (see THE CLOCK above) ----------
    wire clk_core, pll_locked;
    generate if (SIM_NO_PLL) begin : g_nopll
        assign clk_core = clk_25mhz;    // simulation only: NOT the board's clock
        assign pll_locked = 1'b1;
    end else begin : g_pll
        wire clkop_unused;
        (* FREQUENCY_PIN_CLKI="25" *)
        (* FREQUENCY_PIN_CLKOP="25" *)
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
            .RST(1'b0), .STDBY(1'b0),
            .CLKI(clk_25mhz), .CLKOP(clkop_unused), .CLKOS(clk_core), .CLKFB(clkop_unused),
            .CLKINTFB(),
            .PHASESEL0(1'b0), .PHASESEL1(1'b0), .PHASEDIR(1'b1),
            .PHASESTEP(1'b1), .PHASELOADREG(1'b1), .PLLWAKESYNC(1'b0), .ENCLKOP(1'b0),
            .LOCK(pll_locked));
    end endgenerate

    // ---- power-on reset, released only after lock --------------------------
    reg [1:0] lock_q = 2'b00;
    reg [POR_BITS-1:0] por = {POR_BITS{1'b0}};
    wire por_done = &por;
    always @(posedge clk_core) begin
        lock_q <= {lock_q[0], pll_locked};
        if (!lock_q[1])      por <= {POR_BITS{1'b0}};
        else if (!por_done)  por <= por + 1'b1;
    end
    wire rst_n = por_done & ~btn_fire1;

    // ---- the chip ----------------------------------------------------------
    synth_top u_synth (
        .clk(clk_core), .rst_n_pad(rst_n),
        .sck(spi_sck), .mosi(spi_mosi), .cs_n(spi_cs_n), .miso(spi_miso),
        .bclk(i2s_bclk), .lrclk(i2s_lrclk), .sdata(i2s_sdata));

    // ---- I2S sniffer -> LEDs ------------------------------------------------
    // Decodes the LEFT word back off the three audio pins the way a DAC does,
    // in the core clock domain, and shows its magnitude. This is a liveness
    // display, not a measurement: fpga/verify_fpga_netlist.py is what compares
    // the wire against the model. `vu_sample` is checked there too, so the
    // decoder is not merely asserted to work.
    wire [15:0] vu_sample;
    i2s_sniff u_sniff (.clk(clk_core), .rst_n(rst_n),
                       .bclk(i2s_bclk), .lrclk(i2s_lrclk), .sdata(i2s_sdata),
                       .left(vu_sample));

    // peak-hold with a slow decay (tau ~ 42 ms), and a sticky "it made sound" bit
    reg [15:0] peak;
    reg [12:0] dec;
    reg [21:0] hb;
    reg        any_sound;
    wire [15:0] mag = vu_sample[15] ? ~vu_sample : vu_sample;   // |x|, saturating at 32767
    always @(posedge clk_core) begin
        if (!rst_n) begin peak <= 16'd0; dec <= 13'd0; hb <= 22'd0; any_sound <= 1'b0; end
        else begin
            hb  <= hb + 22'd1;
            dec <= dec + 13'd1;
            if (mag != 16'd0) any_sound <= 1'b1;
            if (mag > peak) peak <= mag;
            else if (dec == 13'd0) peak <= peak - {6'd0, peak[15:6]};
        end
    end
    // a 4-LED bar on the top bits, and four status LEDs below it
    assign led[7] = |peak[15:14];
    assign led[6] = |peak[15:12];
    assign led[5] = |peak[15:10];
    assign led[4] = |peak[15:7];
    assign led[3] = pll_locked;
    assign led[2] = por_done;
    assign led[1] = hb[21];                 // ~1.5 Hz heartbeat: the core clock is running
    assign led[0] = any_sound;              // sticky: a non-zero sample has reached the wire
endmodule

// i2s_sniff -- recover the left word from BCLK / LRCLK / SDATA alone.
// Contract 13: LRCLK low = left, 32 BCLK per slot, MSB on the SECOND BCLK
// after the LRCLK edge, SDATA changing on BCLK's falling edge, so a receiver
// samples on BCLK's rising edge. Sixteen bits, then the slot is padded.
module i2s_sniff (
    input  wire clk, input wire rst_n,
    input  wire bclk, input wire lrclk, input wire sdata,
    output reg [15:0] left
);
    reg bclk_d, lrclk_d;
    reg [5:0]  bcnt;
    reg [15:0] sh;
    wire bclk_rise  = bclk & ~bclk_d;
    wire lrclk_fall = ~lrclk & lrclk_d;
    always @(posedge clk) begin
        if (!rst_n) begin
            bclk_d <= 1'b0; lrclk_d <= 1'b0; bcnt <= 6'd63; sh <= 16'd0; left <= 16'd0;
        end else begin
            bclk_d <= bclk; lrclk_d <= lrclk;
            if (lrclk_fall) bcnt <= 6'd0;
            else if (bclk_rise && bcnt != 6'd63) bcnt <= bcnt + 6'd1;
            if (bclk_rise) begin
                // bcnt is the index of the BCLK rising edge being taken now,
                // counted from the first one after the LRCLK falling edge.
                // The MSB sits on the second, i.e. index 1.
                if (bcnt >= 6'd1 && bcnt <= 6'd16) sh <= {sh[14:0], sdata};
                if (bcnt == 6'd16) left <= {sh[14:0], sdata};
            end
        end
    end
endmodule
`default_nettype wire
