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
// STATUS: REAL RTL (the sibling's, with its two recorded defects kept out);
// tb_synth_top.v decodes SDATA as a DAC does and checks it against the
// sample stream with D = 1, so this file is verified in this repository too.
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
                        cur     <= held;
`ifdef INJECT_BUG_TOP_I2S_SHIFT
                        shifter <= {held[14:0], 17'd0};  // NEGATIVE CONTROL: the word one bit early --
`else                                                    //   a bit shift on the wire. The existing
                        shifter <= {held, 16'd0};        //   top-level check compares SDATA against the
`endif                                                   //   DUT's own sample stream, so it defines its
                    end else                             //   expectation from the thing under test.
`ifdef INJECT_BUG_TOP_I2S_SWAP
                        shifter <= {held, 16'd0};        // NEGATIVE CONTROL: the right slot carries the
`else                                                    //   NEWER sample -- the two channels no longer
                        shifter <= {cur, 16'd0};         //   carry one word (contract 13)
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
