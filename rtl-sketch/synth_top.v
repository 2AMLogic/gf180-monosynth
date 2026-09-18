// synth_top.v -- the chip: docs/ARCHITECTURE.md as RTL.
//
//   SPI pins -> spi_ctl (link, 4-deep write queue, drain at the tick)
//            -> voice_dp (three oscillators, mixer, envelopes, cutoff ROMs,
//                         the verified ladder_dp_n -- two filter contexts: the
//                         voice's, and the drum filter's -- VCA, volume, master mix)
//            -> i2s_tx  (BCLK / LRCLK / SDATA)
//   and, on the drum bus, drum_section_placeholder (see below).
//
// WHAT IS REAL AND WHAT IS A PLACEHOLDER -- read this before quoting a number:
//   REAL, verified bit-exact against a model:  ladder_dp_n (inside voice_dp; each channel),
//                                              modal_dp_rom (inside the drum placeholder)
//   REAL, written to the contract; whether voice_dp is bit-exact against the
//   model is verify_voice.py's finding, stated in ARCHITECTURE.md section 9:
//                                              voice_dp, recip_div, spi_ctl (DR 0007), i2s_tx
//                                              (the sibling's, checked here by tb_synth_top), this file
//   PLACEHOLDER:                               drum_section_placeholder's SOURCES -- eight
//                                              trigger bits that fire a decaying noise burst
//                                              into the modal bank. The `drums` branch
//                                              replaces that module; its register addresses
//                                              0x40-0x7F are reserved for it (DR 0007).
//
// One clock (12.288 MHz, 256 cycles per 48 kHz frame), one reset (the pad,
// synchronised), synchronous resets throughout; no derived clocks -- BCLK and
// LRCLK are bits of the frame cycle counter. Frame schedule: ARCHITECTURE.md
// section 5; `go` at cycle GO_CYCLE starts every block after the write drain.
`default_nettype none
module synth_top #(
    parameter GO_CYCLE = 8
)(
    input  wire clk,          // 12.288 MHz
    input  wire rst_n_pad,    // active-low reset from the MCU
    // control link (DR 0007)
    input  wire sck,
    input  wire mosi,
    input  wire cs_n,
    output wire miso,
    // audio (contract 13)
    output wire bclk,
    output wire lrclk,
    output wire sdata
);
    // ---- reset synchroniser ------------------------------------------------------
    reg [1:0] rst_q;
    always @(posedge clk) rst_q <= {rst_q[0], rst_n_pad};
    wire rst_n = rst_q[1];

    // ---- the frame: cycle counter, tick, go, frame counter, overrun flag ----------
    reg [7:0]  cyc;
    reg [15:0] frame;
    reg        overrun;
    wire tick = (cyc == 8'd0);
    wire go   = (cyc == GO_CYCLE[7:0]);
    wire voice_busy, drum_busy;
    always @(posedge clk) begin
        if (!rst_n) begin cyc <= 8'd0; frame <= 16'd0; overrun <= 1'b0; end
        else begin
            cyc <= cyc + 8'd1;
            if (tick) frame <= frame + 16'd1;
            if (tick && (voice_busy || drum_busy)) overrun <= 1'b1;     // a defect if it ever sets
        end
    end

    // ---- the link and the write port ------------------------------------------------
    wire        wr_valid, wr_flag;
    wire [6:0]  wr_addr;
    wire [23:0] wr_data;
    wire        fresh, overflow;
    wire [2:0]  q_count;
    spi_ctl u_spi (.clk(clk), .rst_n(rst_n), .sck(sck), .mosi(mosi), .cs_n(cs_n), .miso(miso),
                   .tick(tick), .frame(frame), .overrun(overrun),
                   .wr_valid(wr_valid), .wr_flag(wr_flag), .wr_addr(wr_addr), .wr_data(wr_data),
                   .fresh(fresh), .overflow(overflow), .q_count(q_count));
    // RESET (0x23) resets every datapath register of contract 14 and nothing on the link
    wire soft_rst  = wr_valid && (wr_addr == 7'h23);
    wire rst_n_dp  = rst_n & ~soft_rst;

    // ---- the drum bus: Q4.15, 19 bits, the ladder's output word (ARCHITECTURE.md 4) -------
    wire signed [18:0] drum_bus;
    wire        drum_done;
    drum_section_placeholder u_drums (.clk(clk), .rst_n(rst_n_dp), .go(go),
                                      .wr_valid(wr_valid), .wr_addr(wr_addr), .wr_data(wr_data),
                                      .drum_bus(drum_bus), .drum_done(drum_done), .busy(drum_busy));

    // ---- the voice, the ladder, the master mix -------------------------------------------
    wire signed [15:0] sample;
    wire        sample_valid;
    voice_dp u_voice (.clk(clk), .rst_n(rst_n_dp), .go(go),
                      .wr_valid(wr_valid), .wr_flag(wr_flag), .wr_addr(wr_addr), .wr_data(wr_data),
                      .drum_bus(drum_bus), .drum_done(drum_done),
                      .sample(sample), .sample_valid(sample_valid), .busy(voice_busy),
                      .mixed(), .ae(), .fe(), .cut(), .k_eff(), .y19());

    // ---- I2S -------------------------------------------------------------------------------
    i2s_tx u_i2s (.clk(clk), .rst_n(rst_n), .cyc(cyc), .sample_valid(sample_valid), .sample(sample),
                  .bclk(bclk), .lrclk(lrclk), .sdata(sdata));
endmodule


// drum_section_placeholder -- the drum path of ARCHITECTURE.md section 4 with
// PLACEHOLDER SOURCES and the REAL modal bank.
//
//   sources (PLACEHOLDER): eight trigger bits at 0x40; a 0->1 write fires a
//     16-bit envelope (32767, then -1/8 per frame) that signs an LFSR: a
//     decaying noise burst, roughly the model's 1.6 ms strike. No multiplier,
//     no per-drum tuning, no mix of its own -- the `drums` branch owns all of
//     that, and docs/area-budget.md's drum_src_seq strawman (89,004 um^2) is
//     the expected size of the real thing.
//   bodies (REAL): modal_dp_rom, bit-exact against model/modal_fixed.py, 15
//     cycles, preset from 0x41 (eight stored bars, gen_modal_rom.py).
//
// ORDER IS A CORRECTNESS PROPERTY of the schedule (ARCHITECTURE.md section
// 5): the excitation the bank receives in frame f is the sources' output for
// frame f, and the bank's output for frame f is the drum bus of frame f.
// Running the bank before the sources would feed it frame f-1's pulse -- a
// one-frame offset that "works" and is wrong. Two things this module honours
// that the drum branch's block must too: (1) modal_dp_rom reads `exc` on
// every one of its 15 cycles, so the excitation is registered before
// sample_valid and held until y_valid (`exc` changes only at the next `go`);
// (2) drum_done is cleared at `go` and set only when THIS frame's bus is on
// drum_bus, and the voice's master mix waits for it rather than assuming it.
module drum_section_placeholder (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        go,
    input  wire        wr_valid,
    input  wire [6:0]  wr_addr,
    input  wire [23:0] wr_data,
    output reg  signed [18:0] drum_bus,     // Q4.15; the placeholder fills it from the bank's Q1.15 word
    output reg         drum_done,
    output wire        busy
);
    reg [7:0]  trig, trig_q;
    reg [2:0]  preset;
    reg [15:0] env;
    reg [15:0] lfsr;
    reg signed [15:0] exc;
`ifdef INJECT_BUG_TOP_DRUM_ORDER
    reg signed [15:0] exc_d;        // NEGATIVE CONTROL: the bodies run on the PREVIOUS frame's
`endif                              //   strike -- ARCHITECTURE.md 4.4's "one-frame offset that
    reg        m_sv;                //   works and is wrong". 20.8 us of drum latency, silently.
    reg [1:0]  st;
    wire signed [15:0] m_y;
    wire        m_yv;
    assign busy = (st != 2'd0);
    wire fire = |(trig & ~trig_q);
    modal_dp_rom #(.PRESETS(8)) u_modal (.clk(clk), .rst_n(rst_n), .sample_valid(m_sv), .exc(exc),
                                         .preset(preset), .y_out(m_y), .y_valid(m_yv));
    always @(posedge clk) begin
        if (!rst_n) begin
            trig <= 0; trig_q <= 0; preset <= 0; env <= 0; lfsr <= 16'hACE1; exc <= 0; m_sv <= 0; st <= 0;
`ifdef INJECT_BUG_TOP_DRUM_ORDER
            exc_d <= 0;
`endif
            drum_bus <= 0; drum_done <= 0;
        end else begin
            m_sv <= 1'b0;
            case (st)
                2'd0: if (go) begin                                  // 1. sources (placeholder)
                    drum_done <= 1'b0;
                    trig_q <= trig;
                    env  <= fire ? 16'h7FFF : (env - (env >> 3));
                    lfsr <= {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
                    st <= 2'd1;
                end
                2'd1: begin                                          // 2. excite the bodies, this frame
`ifdef INJECT_BUG_TOP_DRUM_ORDER
                    exc <= exc_d; exc_d <= lfsr[0] ? $signed(env) : -$signed(env);
`else
                    exc <= lfsr[0] ? $signed(env) : -$signed(env);
`endif
                    m_sv <= 1'b1; st <= 2'd2;
                end
                default: if (m_yv) begin                             // 3. the drum bus is this frame's
                    drum_bus <= {{3{m_y[15]}}, m_y}; drum_done <= 1'b1; st <= 2'd0;
                end
            endcase
            if (wr_valid) case (wr_addr)                             // 0x40-0x7F: the drum branch's map
                7'h40: trig   <= wr_data[7:0];
                7'h41: preset <= wr_data[2:0];
                default: ;
            endcase
        end
    end
endmodule
`default_nettype wire
