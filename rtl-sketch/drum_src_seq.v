// drum_src_seq.v -- AREA STRAWMAN (sequenced envelopes: ONE shifter/subtractor shared by all drums), unverified against any model (like touch_dp.v).
//
// The 808-style percussion SOURCES the issue-7 proposal lists, minus the tuned
// bodies: 8 edge-triggered stops, 8 exponential-decay envelopes (shift-subtract,
// rate = a per-drum shift), one 23-bit LFSR noise source, one swept-pitch sine
// kick through the contract's 257-word quarter-sine ROM, and ONE 16x16
// multiplier that applies env x source to each drum in turn (DRUMS cycles per
// frame) into a saturated mix. The tuned parts (snare shell, toms, cowbell,
// hat band-pass) are resonators, i.e. the modal bank, which this block feeds
// with an enveloped-noise excitation on exc_out. Nothing here is a numeric
// choice a model has made; it exists to put a measured number on "drums".
`default_nettype none
module drum_src_seq #(parameter DRUMS = 8) (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               frame_tick,
    input  wire [DRUMS-1:0]   stops,          // stop mask; a 0->1 edge fires the drum
    input  wire [DRUMS*4-1:0] decay_sh,       // per-drum decay: level -= level >> sh, per frame
    input  wire [23:0]        kick_inc0,      // kick rest pitch (phase increment)
    input  wire [15:0]        kick_sweep0,    // pitch sweep added at the hit, decays
    input  wire [3:0]         kick_sweep_sh,
    output reg  signed [15:0] mix_out,
    output reg                mix_valid,
    output reg  signed [15:0] exc_out         // enveloped noise for the modal bank
);
    reg [DRUMS-1:0] stops_q, fire_q;
    wire [19:0] env_d = env[d];
    wire [3:0]  sh_d  = decay_sh[d*4 +: 4];
    wire [DRUMS-1:0] fire = stops & ~stops_q;
    reg [19:0] env [0:DRUMS-1];
    reg [22:0] lfsr;
    reg [23:0] kphase;
    reg [15:0] ksweep;
    // kick sine via the contract's quarter table (same mirror/sign logic as synth_voice)
    wire [9:0]  si         = kphase[23:14];
    wire [8:0]  sine_q_idx = si[8] ? (9'd256 - {1'b0, si[7:0]}) : {1'b0, si[7:0]};
    `include "sine_q_rom.vh"
    wire [15:0] ksine = si[9] ? (16'd0 - sine_q_val) : sine_q_val;
    wire [15:0] noise = lfsr[15:0];
    // sequencer: one drum per clock after the tick
    reg [3:0] d;
    reg       busy;
    reg  signed [15:0] ma;
    reg         [15:0] mb;
    wire signed [32:0] prod = ma * $signed({1'b0, mb});
    reg  signed [19:0] acc;
    wire signed [19:0] acc_n = acc + {{4{prod[31]}}, prod[31:16]};
    wire signed [15:0] acc_sat = (acc > 20'sd32767) ? 16'sd32767 : (acc < -20'sd32768) ? -16'sd32768 : acc[15:0];
    integer i;
    always @(posedge clk) begin
        if (!rst_n) begin
            stops_q <= 0; fire_q <= 0; lfsr <= 23'h1; kphase <= 0; ksweep <= 0; d <= 0; busy <= 0;
            ma <= 0; mb <= 0; acc <= 0; mix_out <= 0; mix_valid <= 0; exc_out <= 0;
            for (i = 0; i < DRUMS; i = i + 1) env[i] <= 0;
        end else begin
            mix_valid <= 1'b0;
            if (frame_tick) begin
                stops_q <= stops;
                lfsr    <= {lfsr[21:0], lfsr[22] ^ lfsr[17]};
                kphase  <= kphase + kick_inc0 + {8'b0, ksweep};
                ksweep  <= fire[0] ? kick_sweep0 : ksweep - (ksweep >> kick_sweep_sh);
                fire_q <= fire;
                busy <= 1'b1; d <= 0; acc <= 0;
                ma <= ksine; mb <= env[0][19:4];
            end else if (busy) begin
                acc <= acc_n;
                env[d] <= fire_q[d] ? 20'hFFFFF : env_d - (env_d >> sh_d);   // one shifter, one subtractor
                if (d == 1) exc_out <= prod[31:16];              // drum 1's enveloped noise excites the bodies
                if (d == DRUMS - 1) begin
                    busy <= 1'b0; mix_out <= acc_sat; mix_valid <= 1'b1;
                end else begin
                    d  <= d + 4'd1;
                    ma <= noise; mb <= env[d + 4'd1][19:4];
                end
            end
        end
    end
endmodule
`default_nettype wire
