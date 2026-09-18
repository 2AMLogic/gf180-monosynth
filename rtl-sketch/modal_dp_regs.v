// modal_dp.v -- modal resonator bank, bit-exact against model/modal_fixed.py.
//
// The "something you can hit" engine: each mode is a two-pole resonator
//
//     y[n] = x[n] + a1*y[n-1] + a2*y[n-2],   a1 = 2 r cos w,  a2 = -r^2
//
// excited by a short noise burst. Ringing comes from the recursion, so there
// is NO DELAY LINE and no RAM: the whole state is two registers per mode.
//
// model/modal_fixed.py (ModalFx) is the specification; verify_modal.py /
// tb_modal_fx.v compare this module against it sample for sample with no
// tolerance, and the INJECT_BUG_MODAL_* defines prove that comparison can
// fail. The formats are the model's, chosen by its sizing sweep and marked
// there as PROPOSED, not ratified:
//
//   exc     Q1.15 signed          the strike; enters the state as exc << (SQ-15)
//   a1, a2  Q2.CF signed, CF=24   26 bits. The earlier sketch's Q2.16 cannot
//                                 tune a low bar: at MIDI 28 it is 2.4 % off
//                                 pitch and -1.9 dB SNR against the float
//   amp     Q0.16 unsigned        per-mode level, 1.0 = 65535
//   state   SB=28 bits, SQ=15     the bank rings to 657x the strike at note 28
//   y_out   Q1.15, saturated      mix >> (SQ - 15 + HR), HR = 10 headroom bits
//
// Structure: one SB x (CF+2) multiplier, sequenced. Per sample, per mode:
//   step 0  acc = a1*y1;                 load a2*y2
//   step 1  y = sat(((acc + a2*y2) >> CF) + exc)   -- floor; rounding was measured
//           y2 = y1; y1 = y;              load y*amp    and buys nothing
//   step 2  mix += (y*amp) >> 16;        load next mode's a1*y1
// then y_out = sat16(mix >> OSH). 3 clocks per mode + 2: 15 clocks per sample
// for four modes (tb_modal.v).
//
// The coefficients arrive as parallel ports and are selected by mux trees, as
// in the earlier sketch; a real design reads them from a small ROM. The cell
// count therefore overstates a real implementation by those muxes.
`default_nettype none
module modal_dp_regs #(
    parameter MODES = 4,
    parameter SB    = 28,       // state width          (ModalFx state_bits)
    parameter SQ    = 15,       // state fraction bits  (ModalFx state_q), >= 15
    parameter CF    = 24,       // coefficient fraction bits (ModalFx coef_frac)
    parameter HR    = 10        // output headroom bits (ModalFx headroom)
)(
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 sample_valid,
    input  wire signed [15:0]   exc,
    input  wire                 we,             // host coefficient write: 12 words
    input  wire        [3:0]    waddr,          // {mode, kind}, kind 0 = a1, 1 = a2, 2 = amp
    input  wire        [CF+1:0] wdata,
    output reg  signed [15:0]   y_out,
    output reg                  y_valid
);
    localparam CW  = CF + 2;                 // coefficient width
    reg signed [CW-1:0] a1_0, a2_0, a1_1, a2_1, a1_2, a2_2, a1_3, a2_3;
    reg        [15:0]   amp0, amp1, amp2, amp3;
    always @(posedge clk) if (we) case (waddr)
        4'd0: a1_0 <= wdata;  4'd1: a2_0 <= wdata;  4'd2: amp0 <= wdata[15:0];
        4'd4: a1_1 <= wdata;  4'd5: a2_1 <= wdata;  4'd6: amp1 <= wdata[15:0];
        4'd8: a1_2 <= wdata;  4'd9: a2_2 <= wdata;  4'd10: amp2 <= wdata[15:0];
        4'd12: a1_3 <= wdata; 4'd13: a2_3 <= wdata; 4'd14: amp3 <= wdata[15:0];
        default: ;
    endcase
    localparam PW  = SB + CW;                // product width
    localparam AW  = SB + 4;                 // pre-saturation width: |value| < 2^(SB+2)
    localparam ESH = SQ - 15;                // excitation -> state shift
    localparam OSH = SQ - 15 + HR;           // state -> output shift

    reg signed [SB-1:0] y1 [0:MODES-1];
    reg signed [SB-1:0] y2 [0:MODES-1];
    reg signed [PW-1:0] acc;
    reg signed [SB+1:0] mix;                 // MODES terms each under 2^(SB-1)
    reg [1:0] mode;
    reg [1:0] step;
    reg busy;

    // ---- the one multiplier: SB-bit signed x CW-bit signed ------------------
    reg  signed [SB-1:0] ma;
    reg  signed [CW-1:0] mb;
    wire signed [PW-1:0] mr = ma * mb;

    function signed [CW-1:0] sel_a1(input [1:0] m);
        sel_a1 = (m == 0) ? a1_0 : (m == 1) ? a1_1 : (m == 2) ? a1_2 : a1_3;
    endfunction
    function signed [CW-1:0] sel_a2(input [1:0] m);
        sel_a2 = (m == 0) ? a2_0 : (m == 1) ? a2_1 : (m == 2) ? a2_2 : a2_3;
    endfunction
    function signed [CW-1:0] sel_amp(input [1:0] m);       // Q0.16 into Q2.CF's width, positive
        sel_amp = {{(CW-16){1'b0}}, (m == 0) ? amp0 : (m == 1) ? amp1 : (m == 2) ? amp2 : amp3};
    endfunction

    // ---- saturation, the model's sat(v, bits) -------------------------------
    localparam signed [AW-1:0] SMAX = (1 << (SB - 1)) - 1;
    localparam signed [AW-1:0] SMIN = -(1 << (SB - 1));
    function signed [SB-1:0] sat_s(input signed [AW-1:0] v);
        sat_s = (v > SMAX) ? SMAX[SB-1:0] : (v < SMIN) ? SMIN[SB-1:0] : v[SB-1:0];
    endfunction
    function signed [15:0] sat16(input signed [SB+1:0] v);
        sat16 = (v > 32767) ? 16'sd32767 : (v < -32768) ? 16'sh8000 : v[15:0];
    endfunction

    // ---- the recursion, in the cycle a2*y2 is on the multiplier -------------
    wire signed [PW+3:0] acc2 = acc + mr;                // a1*y1 + a2*y2, exact
`ifdef INJECT_BUG_MODAL_SHIFT
    wire signed [AW-1:0] ysh  = acc2[(CF + 2) +: AW];   // NEGATIVE CONTROL: the old sketch's
`else                                                    //   shift, coefficients effectively /4
    wire signed [AW-1:0] ysh  = acc2[CF +: AW];          // >> CF, exact: value < 2^(SB+2)
`endif
    wire signed [SB-1:0] e_st = {{(SB - 16 - ESH){exc[15]}}, exc, {ESH{1'b0}}};
    wire signed [AW-1:0] ysum = ysh + e_st;
`ifdef INJECT_BUG_MODAL_SAT
    wire signed [SB-1:0] ynew = ysum[SB-1:0];            // NEGATIVE CONTROL: wrap
`else
    wire signed [SB-1:0] ynew = sat_s(ysum);
`endif
    wire signed [SB-1:0] mout = mr[16 +: SB];            // (y*amp) >> 16, exact
    wire signed [SB+1:0] msh  = mix >>> OSH;

    integer i;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (i = 0; i < MODES; i = i + 1) begin y1[i] <= 0; y2[i] <= 0; end
            mode <= 0; step <= 0; busy <= 0; y_valid <= 0; mix <= 0; acc <= 0;
            ma <= 0; mb <= 0; y_out <= 0;
        end else begin
            y_valid <= 1'b0;
            if (!busy) begin
                if (sample_valid) begin
                    busy <= 1'b1; mode <= 2'd0; step <= 2'd0; mix <= 0;
                    ma <= y1[0]; mb <= sel_a1(2'd0);
                end
            end else case (step)
                2'd0: begin                                  // acc = a1*y1; load a2*y2
                    acc <= mr; ma <= y2[mode]; mb <= sel_a2(mode); step <= 2'd1;
                end
                2'd1: begin                                  // y = sat((acc + a2*y2) >> CF + exc); load y*amp
                    y2[mode] <= y1[mode]; y1[mode] <= ynew;
`ifdef INJECT_BUG_MODAL_PREEXC
                    ma <= sat_s(ysh);                        // NEGATIVE CONTROL: the old sketch's amp
`else                                                        //   tap, before the excitation is added
                    ma <= ynew;
`endif
                    mb <= sel_amp(mode); step <= 2'd2;
                end
                2'd2: begin                                  // mix += (y*amp) >> 16; next mode
                    mix <= mix + mout;
                    if (mode == MODES - 1) step <= 2'd3;
                    else begin
                        mode <= mode + 2'd1; step <= 2'd0;
                        ma <= y1[mode + 2'd1]; mb <= sel_a1(mode + 2'd1);
                    end
                end
                default: begin                               // y_out = sat16(mix >> OSH)
                    y_out <= sat16(msh); y_valid <= 1'b1; busy <= 1'b0;
                end
            endcase
        end
    end
endmodule
`default_nettype wire
