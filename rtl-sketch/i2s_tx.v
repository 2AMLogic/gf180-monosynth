// i2s_tx.v -- the I2S transmitter of contract section 13, which adopts
// gf180-polysynth's fpga/i2s_tx.v unchanged in convention: BCLK = clk/4 =
// 3.072 MHz (64 x fs), LRCLK = clk/256 = 48 kHz (low = left), one 16-bit
// sample MSB first, left-justified in a 32-bit slot, the MSB on the second
// BCLK after the LRCLK edge, SDATA changing on BCLK's falling edge, the same
// sample on both channels.
//
// This copy takes the chip's frame cycle counter `cyc` instead of running its
// own, so LRCLK is the frame clock by construction: cycle 0 of frame f is the
// start of LRCLK period f. The sample strobed during frame f is loaded at
// cycle 255 of frame f and transmitted in period f+1: the latency D of
// contract 13 is 1, provided the strobe precedes cycle 255 (the scheduler
// guarantees it; tb_synth_top.v measures where the strobe lands).
//
// STATUS: REAL RTL (the sibling's, with its two recorded defects kept out).
// tb_top_bx.v / verify_synth_top.py decode SDATA as a DAC does -- from BCLK,
// LRCLK and SDATA only -- and check every word against model/synth_top_model.py.
// That is the verification of this file. tb_synth_top.v also decodes the wire,
// but compares it against `dut.sample`, the core's OWN stream: circular, and
// blind to a bit shift, a channel swap or a wrong D by construction. The three
// INJECT_BUG_I2S_* controls below are exactly those three defects, and each is
// demonstrated to turn verify_synth_top.py red.
`default_nettype none
module i2s_tx (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [7:0]  cyc,           // frame cycle counter: bit 1 = BCLK, bit 7 = LRCLK
    input  wire        sample_valid,
    input  wire [15:0] sample,
    output wire        bclk,
    output wire        lrclk,
    output reg         sdata
);
    reg [15:0] held;                 // latest sample from the core (once per frame)
`ifdef INJECT_BUG_I2S_DELAY
    reg [15:0] held2;
    always @(posedge clk) if (!rst_n) held2 <= 16'd0; else if (cyc == 8'd255) held2 <= held;
`endif
    reg [15:0] cur;                  // the sample of this LRCLK period (L and R)
    reg [31:0] shifter;
    assign bclk  = cyc[1];
    assign lrclk = cyc[7];
    always @(posedge clk) begin
        if (!rst_n) begin
            held <= 16'd0; cur <= 16'd0; shifter <= 32'd0; sdata <= 1'b0;
        end else begin
            if (sample_valid) held <= sample;
            if (cyc[1:0] == 2'b11) begin                 // falling edge of BCLK: SDATA changes here
                if (cyc[6:2] == 5'd31) begin             // last BCLK of a slot = delay bit of the next slot
                    sdata <= 1'b0;
                    if (cyc[7]) begin                    // right slot ends: next period, fresh sample
`ifdef INJECT_BUG_I2S_DELAY
                        cur     <= held2;                // NEGATIVE CONTROL: one period too late (D = 2)
                        shifter <= {held2, 16'd0};
`elsif INJECT_BUG_I2S_SHIFT
                        cur     <= held;                 // NEGATIVE CONTROL: every bit one BCLK late
                        shifter <= {1'b0, held, 15'd0};
`else
                        cur     <= held;
                        shifter <= {held, 16'd0};
`endif
                    end else                             // left slot ends: right repeats the same sample
`ifdef INJECT_BUG_I2S_SWAP
                        shifter <= {held, 16'd0};        // NEGATIVE CONTROL: the right channel carries
`elsif INJECT_BUG_I2S_SHIFT                              //   a different sample from the left
                        shifter <= {1'b0, cur, 15'd0};
`else
                        shifter <= {cur, 16'd0};
`endif
                end else begin
                    sdata   <= shifter[31];
                    shifter <= {shifter[30:0], 1'b0};
                end
            end
        end
    end
endmodule
`default_nettype wire
