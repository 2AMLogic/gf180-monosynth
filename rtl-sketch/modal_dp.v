// modal_dp.v -- modal resonator bank, bit-exact against model/modal_fixed.py.
//
// Each mode is a two-pole resonator
//
//     y[n] = x[n] + a1*y[n-1] + a2*y[n-2],   a1 = 2 r cos w,  a2 = -r^2
//
// with no delay line and no RAM: the whole state is two registers per mode.
// Since DR 0008 the bank is the drum section's bodies and filters as well as
// the struck bar: the TR-808's bridged-T voices are coefficient presets of
// it, and its band-pass / high-pass filters are modes whose input is
// pre-differenced (contract 15.6):
//
//     num = 0 RAW  x = e                         the resonator
//     num = 1 BP   x = e - e[n-2]                the (1 - z^-2) band-pass numerator
//     num = 2 HP   x = e - 2 e[n-1] + e[n-2]     the (1 - z^-1)^2 high-pass numerator
//
// from two excitation-history registers on the first NUMS modes; modes at
// or above NUMS are RAW whatever num says.
//
// model/modal_fixed.py (ModalFx) is the specification; verify_modal.py /
// tb_modal_fx.v compare this module against it sample for sample with no
// tolerance, and the INJECT_BUG_MODAL_* defines prove that comparison can
// fail. The formats are the model's:
//
//   exc     signed, EW = 21 bits    per mode; enters the state as exc << (SQ-15)
//   a1, a2  Q2.CF signed, CF=24     26 bits. Q2.16 cannot tune a low bar: at
//                                   MIDI 28 it is 2.4 % off pitch
//   amp     Q0.16 unsigned          per-mode level, 1.0 = 65535
//   state   SB=28 bits, SQ=15       the bank rings to 657x the strike at note 28
//   y_out   Q(OW-16).15, saturated  mix >> (SQ - 15 + HR), OW = 19 (DR 0005's width);
//                                   HR = 0 in the drum section, 10 for the bar
//
// EXCITATION INTERFACE (the timing contract of 15.6). The excitation is not
// a port that must be held: it is ACCUMULATED into the bank's exc registers
// by exc_we pulses (exc[exc_mode] += exc_val) while the bank is idle, and
// sample_valid consumes them -- each mode's exc is read once, in its own
// step, and cleared. A write while busy is ignored. The coefficient buses
// must be held while busy, as the ladder's coefficients must.
//
// Structure: one SB x (CF+2) multiplier, sequenced. Per sample, per mode:
//   step 0  acc = a1*y1;                 load a2*y2
//   step 1  y = sat(((acc + a2*y2) >> CF) + x)   -- floor; rounding was measured
//           y2 = y1; y1 = y;              load y*amp    and buys nothing
//   step 2  mix += (y*amp) >> 16;        load next mode's a1*y1
// then y_out = sat(mix >> OSH). 3 clocks per mode + 2: 14 clocks per sample
// for four modes, 38 for twelve (tb_modal.v).
//
// tap_y1 is a combinational read of y1[tap_sel], the drum section's TAP
// source (15.5); it is only meaningful while the bank is idle.
`default_nettype none
module modal_dp #(
    parameter MODES = 4,
    parameter NUMS  = 0,        // modes 0..NUMS-1 have the numerator (ModalFx nums)
    parameter SB    = 28,       // state width          (ModalFx state_bits)
    parameter SQ    = 15,       // state fraction bits  (ModalFx state_q), >= 15
    parameter CF    = 24,       // coefficient fraction bits (ModalFx coef_frac)
    parameter HR    = 10,       // output headroom bits (ModalFx headroom)
    parameter OW    = 19,       // output width (ModalFx out_bits)
    parameter EW    = 21,       // excitation width (ModalFx exc_bits)
    parameter MW    = 4         // mode index width; 2^MW >= MODES
)(
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  exc_we,
    input  wire [MW-1:0]         exc_mode,
    input  wire signed [EW-1:0]  exc_val,
    input  wire                  sample_valid,
    input  wire [MODES*(CF+2)-1:0] a1_bus,
    input  wire [MODES*(CF+2)-1:0] a2_bus,
    input  wire [MODES*16-1:0]   amp_bus,
    input  wire [MODES*2-1:0]    num_bus,
    input  wire [MW-1:0]         tap_sel,
    output wire signed [SB-1:0]  tap_y1,
    output reg  signed [OW-1:0]  y_out,
    output reg                   y_valid
);
    localparam CW  = CF + 2;                 // coefficient width
    localparam PW  = SB + CW;                // product width
    localparam AW  = SB + 4;                 // pre-saturation width: |value| < 2^(SB+2)
    localparam ESH = SQ - 15;                // excitation -> state shift
    localparam OSH = SQ - 15 + HR;           // state -> output shift
    localparam XW  = EW + 2;                 // numerator output: up to 4x the excitation
    localparam MXW = SB + MW;                // mix: MODES terms each under 2^(SB-1)

    reg signed [SB-1:0] y1 [0:MODES-1];
    reg signed [SB-1:0] y2 [0:MODES-1];
    reg signed [EW-1:0] exc [0:MODES-1];     // accumulated excitation, consumed once
    reg signed [EW-1:0] h1  [0:MODES-1];     // excitation history (modes < NUMS)
    reg signed [EW-1:0] h2  [0:MODES-1];
    reg signed [PW-1:0] acc;
    reg signed [MXW-1:0] mix;
    reg [MW-1:0] mode;
    reg [1:0] step;
    reg busy;

    assign tap_y1 = y1[tap_sel];

    // ---- the one multiplier: SB-bit signed x CW-bit signed ------------------
    reg  signed [SB-1:0] ma;
    reg  signed [CW-1:0] mb;
    wire signed [PW-1:0] mr = ma * mb;

    wire signed [CW-1:0] a1_m  = a1_bus[mode*CW +: CW];
    wire signed [CW-1:0] a2_m  = a2_bus[mode*CW +: CW];
    wire        [15:0]   amp_m = amp_bus[mode*16 +: 16];
    wire        [1:0]    num_m = num_bus[mode*2 +: 2];
    wire [MW:0] mode1 = mode + 1'b1;
    wire signed [CW-1:0] a1_n  = a1_bus[mode1[MW-1:0]*CW +: CW];

    // ---- saturation, the model's sat(v, bits) -------------------------------
    localparam signed [AW-1:0] SMAX = (1 << (SB - 1)) - 1;
    localparam signed [AW-1:0] SMIN = -(1 << (SB - 1));
    function signed [SB-1:0] sat_s(input signed [AW-1:0] v);
        sat_s = (v > SMAX) ? SMAX[SB-1:0] : (v < SMIN) ? SMIN[SB-1:0] : v[SB-1:0];
    endfunction
    localparam signed [MXW-1:0] OMAX = (1 << (OW - 1)) - 1;
    localparam signed [MXW-1:0] OMIN = -(1 << (OW - 1));
    function signed [OW-1:0] sat_o(input signed [MXW-1:0] v);
        sat_o = (v > OMAX) ? OMAX[OW-1:0] : (v < OMIN) ? OMIN[OW-1:0] : v[OW-1:0];
    endfunction

    // ---- the numerator (contract 15.6), in the cycle a2*y2 is on the multiplier
    wire signed [EW-1:0] e_m  = exc[mode];
    wire                 has_num = (mode < NUMS);
`ifdef INJECT_BUG_MODAL_NUM_HOLD
    wire signed [EW-1:0] h1_m = 0;                       // NEGATIVE CONTROL: no history
    wire signed [EW-1:0] h2_m = 0;
`else
    wire signed [EW-1:0] h1_m = h1[mode];
    wire signed [EW-1:0] h2_m = h2[mode];
`endif
    wire signed [XW-1:0] x_m  = (!has_num || num_m == 2'd0 || num_m == 2'd3) ? e_m :
                                (num_m == 2'd1) ? (e_m - h2_m) : (e_m - (h1_m <<< 1) + h2_m);

    // ---- the recursion ---------------------------------------------------------
    wire signed [PW+3:0] acc2 = acc + mr;                // a1*y1 + a2*y2, exact
`ifdef INJECT_BUG_MODAL_SHIFT
    wire signed [AW-1:0] ysh  = acc2[(CF + 2) +: AW];   // NEGATIVE CONTROL: the old sketch's
`else                                                    //   shift, coefficients effectively /4
    wire signed [AW-1:0] ysh  = acc2[CF +: AW];          // >> CF, exact: value < 2^(SB+2)
`endif
    wire signed [AW-1:0] x_st = {{(AW - XW - ESH){x_m[XW-1]}}, x_m, {ESH{1'b0}}};
    wire signed [AW-1:0] ysum = ysh + x_st;
`ifdef INJECT_BUG_MODAL_SAT
    wire signed [SB-1:0] ynew = ysum[SB-1:0];            // NEGATIVE CONTROL: wrap
`else
    wire signed [SB-1:0] ynew = sat_s(ysum);
`endif
    wire signed [SB-1:0] mout = mr[16 +: SB];            // (y*amp) >> 16, exact
    wire signed [MXW-1:0] msh = mix >>> OSH;

    integer i;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (i = 0; i < MODES; i = i + 1) begin
                y1[i] <= 0; y2[i] <= 0; exc[i] <= 0; h1[i] <= 0; h2[i] <= 0;
            end
            mode <= 0; step <= 0; busy <= 0; y_valid <= 0; mix <= 0; acc <= 0;
            ma <= 0; mb <= 0; y_out <= 0;
        end else begin
            y_valid <= 1'b0;
            if (!busy) begin
                if (exc_we) exc[exc_mode] <= exc[exc_mode] + exc_val;
                if (sample_valid) begin
                    busy <= 1'b1; mode <= 0; step <= 2'd0; mix <= 0;
                    ma <= y1[0]; mb <= a1_bus[CW-1:0];
                end
            end else case (step)
                2'd0: begin                                  // acc = a1*y1; load a2*y2
                    acc <= mr; ma <= y2[mode]; mb <= a2_m; step <= 2'd1;
                end
                2'd1: begin                                  // y = sat((acc + a2*y2) >> CF + x); load y*amp
                    y2[mode] <= y1[mode]; y1[mode] <= ynew;
`ifndef INJECT_BUG_MODAL_EXC_NOCLEAR
                    exc[mode] <= 0;                          // consumed once
`endif
                    if (has_num) begin h2[mode] <= h1[mode]; h1[mode] <= e_m; end
`ifdef INJECT_BUG_MODAL_PREEXC
                    ma <= sat_s(ysh);                        // NEGATIVE CONTROL: the old sketch's amp
`else                                                        //   tap, before the excitation is added
                    ma <= ynew;
`endif
                    mb <= {{(CW-16){1'b0}}, amp_m}; step <= 2'd2;
                end
                2'd2: begin                                  // mix += (y*amp) >> 16; next mode
                    mix <= mix + mout;
                    if (mode == MODES - 1) step <= 2'd3;
                    else begin
                        mode <= mode1[MW-1:0]; step <= 2'd0;
                        ma <= y1[mode1[MW-1:0]]; mb <= a1_n;
                    end
                end
                default: begin                               // y_out = sat(mix >> OSH)
                    y_out <= sat_o(msh); y_valid <= 1'b1; busy <= 1'b0;
                end
            endcase
        end
    end
endmodule
`default_nettype wire
