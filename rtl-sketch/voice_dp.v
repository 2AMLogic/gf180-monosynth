// voice_dp.v -- the voice of spec/NUMERIC-CONTRACT.md as one sequenced
// datapath around the verified ladder: three oscillators with glide and
// PolyBLEP, the mixer, two ADSRs, the cutoff path (g ROM, kc ROM, k_eff), the
// ladder (ladder_dp_n.v, two filter contexts, bit-exact on each), the VCA,
// and the master mix of the voice bus with the drum bus behind the chip's
// one hard rail (docs/ARCHITECTURE.md section 4).
//
// STATUS: REAL RTL, written operation by operation to the contract's
// sections 5-12, with the contract's own pinned tables read from
// spec/reference/tables/ ($readmemh) and the verified ladder inside. Whether
// it is BIT-EXACT against model/voice_fx.py is what verify_voice.py /
// tb_voice.v establish at the register port; docs/ARCHITECTURE.md section 9
// states the result at the time of writing. Its AREA and CYCLE COUNT are
// measurements of this RTL either way.
//
// Structure: ONE multiplier (25 x 21 signed, covering 24u x 20u), one
// sequential divider (recip_div.v) for the PolyBLEP reciprocal, three ROMs as
// logic, and a sequencer. Per frame, after the write drain (spi_ctl.v), `go`
// starts the following, in this order (ARCHITECTURE.md section 5):
//
//   1. reciprocals: for each oscillator whose increment differs from the one
//      its (e, r) was computed for, one division (19 cycles)          6.6.1
//   2. oscillators: naive wave, up to four PolyBLEP windows at two multiplies
//      each, then osc x w into the mixer; phase advance                 6.4-6.6, 7
//   3. envelope outputs ae, fe (the levels before this frame's update)  8.2
//   4. cutoff: span x fe, clamp, g and kc interpolation, k x kc         10
//   5. mixed = sat16(sum >> 15); the voice's ladder context starts     7, 11
//      while it runs (24 cycles), on the idle multiplier:
//        the envelope updates (8.3) and the glide slews (6.7) -- step 9 of
//        4.2, whose inputs are all latched by now -- and the DRUM FILTER's
//        coefficients from DCUT (its own g, kc, k_eff; DK, DGAIN, DOGAIN)
//   6. when the voice context is done: if ROUTE.DFILT the drum filter runs
//      the second ladder context on sat16(drum_bus) (24 more cycles);
//      meanwhile VCA (y19 x ae) >> 15 and volume (v x vol) >> 15         9, 12
//   7. master: sat16(out_v + ((d19 x dvol) >> 15)) -- the chip's ONE rail; both
//      busses reach it at 19 bits (Q4.15), nothing clamps to 16 before it
//
// The drum bus is 19 bits, Q4.15, the ladder's output word (DR 0005); the
// drum branch's block produces it, and it must be valid (drum_done) before
// this frame's master mix -- the sequencer waits, it does not assume.
//
// Every register is the contract's width (5.1); the write port is DR 0007's
// register map. rst_n is the chip reset AND the RESET write (the top ANDs
// them), so RESET resets exactly the registers of contract 14.
`default_nettype none
module voice_dp #(
    parameter G_ROM_FILE = "../spec/reference/tables/g_rom128.hex",   // Appendix D, 129 x Q0.16
    parameter K_ROM_FILE = "../spec/reference/tables/k_rom32.hex",    // Appendix E,  33 x Q1.15
    parameter SINE_FILE  = "../spec/reference/tables/sine_q256.hex",  // Appendix B, 256 x Q1.15
    parameter TANH_FILE  = "tanh16.hex"                               // Appendix C, the ladder's
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire        go,                 // one cycle per frame, after the write drain
    // register write port (contract 16.2; DR 0007 section 3)
    input  wire        wr_valid,
    input  wire        wr_flag,
    input  wire [6:0]  wr_addr,
    input  wire [23:0] wr_data,
    // the drum bus (ARCHITECTURE.md section 4): Q4.15, valid for this frame once drum_done
    input  wire signed [18:0] drum_bus,
    input  wire        drum_done,
    // out
    output reg  signed [15:0] sample,
    output reg         sample_valid,
    output wire        busy,
    // taps (contract 16.4)
    output reg  signed [15:0] mixed,
    output reg  [14:0] ae,
    output reg  [14:0] fe,
    output reg  [14:0] cut,
    output reg  [16:0] k_eff,
    output reg  signed [18:0] y19
);
    // ---- control image (contract 5.1; DR 0007) ---------------------------------
    reg [23:0] inc_tgt [0:2];
    reg [31:0] inc_acc [0:2];          // Q24.8
    reg [2:0]  wave    [0:2];
    reg [15:0] w       [0:2];
    reg [23:0] a_inc_a, d_dec_a, sus_a, a_inc_f, d_dec_f, sus_f;
    reg [15:0] rate_a, rate_f;
    reg        gate;
    reg [23:0] glide;
    reg [15:0] vol, dvol;
    reg        dfilt;                  // ROUTE bit 0: the drum bus through the second ladder context
    reg [15:0] cut_lo, cut_hi, track_hz;
    reg [16:0] k;
    reg [19:0] gain, ogain;
    reg [15:0] dcut;                   // the drum filter's cutoff, integer Hz, no envelope, no tracking
    reg [16:0] dk;
    reg [19:0] dgain, dogain;
    // ---- state (contract 5.1, 6.1, 8.1) ---------------------------------------
    reg [23:0] phase   [0:2];
    reg [4:0]  sh      [0:2];          // e + 15
    reg [15:0] r       [0:2];
    reg [23:0] inc_er  [0:2];          // the inc (sh, r) was computed for
    reg [23:0] level_a, level_f;
    reg [1:0]  seg_a, seg_f;

    // ---- ROMs: the contract's pinned images ----------------------------------
    reg [15:0] grom [0:128];
    reg [15:0] krom [0:32];
    reg [15:0] srom [0:255];
    initial begin
        $readmemh(G_ROM_FILE, grom);
        $readmemh(K_ROM_FILE, krom);
        $readmemh(SINE_FILE, srom);
    end

    // ---- the one multiplier -------------------------------------------------------
    reg  signed [24:0] ma;
    reg  signed [20:0] mb;
    wire signed [45:0] mr = ma * mb;

    // ---- the divider ---------------------------------------------------------------
    reg         div_start;
    wire        div_done;
    wire [4:0]  div_sh;
    wire [15:0] div_r;
    reg  [23:0] div_inc;
    recip_div u_div (.clk(clk), .rst_n(rst_n), .start(div_start), .inc(div_inc),
                     .done(div_done), .sh(div_sh), .r(div_r));

    // ---- the ladder (verified): context 0 the voice, context 1 the drum filter --------
    reg         lad_sv, lad_ch;
    reg  [15:0] g, g2;
    reg  [16:0] k_eff2;
    reg  signed [15:0] dx;                                        // sat16(drum_bus), the drum filter's input
    wire signed [18:0] lad_y;
    wire        lad_yv;
    wire        lad_ych;
    ladder_dp_n #(.NCH(2), .ROM_FILE(TANH_FILE), .OW(19)) u_ladder (
        .clk(clk), .rst_n(rst_n), .sample_valid(lad_sv), .ch(lad_ch),
        .x_in(lad_ch ? dx : mixed), .g(lad_ch ? g2 : g), .k(lad_ch ? k_eff2 : k_eff),
        .gain(lad_ch ? dgain : gain), .ogain(lad_ch ? dogain : ogain),
        .y_out(lad_y), .y_valid(lad_yv), .y_ch(lad_ych));

    // ---- sequencer state -------------------------------------------------------------
    localparam [5:0]
        S_IDLE = 0, S_RCHK = 1, S_RWAIT = 2,
        S_WIN = 3, S_W1 = 4, S_W2 = 5, S_MIX = 6, S_ACC = 7,
        S_ENV = 8, S_CUT1 = 9, S_ROM0 = 10, S_ROM1 = 11, S_ROM2 = 12, S_ROM3 = 13, S_KEFF0 = 14, S_KEFF1 = 15,
        S_LGO = 16,
        S_EA1 = 17, S_EF1 = 18, S_SL0 = 19, S_SL1 = 20, S_SL2 = 21,
        S_DC0 = 22, S_DC1 = 23, S_DC2 = 24, S_DC3 = 25, S_DC4 = 26, S_DC5 = 27,
        S_YWAIT = 28, S_DGO = 29, S_VCA0 = 30, S_VCA1 = 31, S_VCA2 = 32, S_DWAIT = 33, S_OUT0 = 34, S_OUT1 = 35, S_OUT2 = 36;
    reg [5:0]  state;
    reg [1:0]  kk;                     // oscillator index
    reg [1:0]  win;                    // PolyBLEP window 0..3
    reg signed [16:0] c_pp, c_ps;      // corrections at the two edges
    reg signed [34:0] mixacc;
    reg        y_seen, d_seen;
    reg [15:0] g0, g1, kc0, kc1;
    reg signed [16:0] kd;
    reg [39:0] pacc;
    reg signed [19:0] out_v, out_d;
    reg signed [18:0] d19;             // the drum bus after (or without) the drum filter
    assign busy = (state != S_IDLE);

    // ---- per-oscillator combinational view (index kk) --------------------------------
    wire [23:0] ph   = phase[kk];
    wire [2:0]  wv   = wave[kk];
    wire [23:0] inc  = inc_acc[kk][31:8];
    wire        is_saw = (wv == 3'd0), is_sq = (wv == 3'd1), is_p25 = (wv == 3'd2), is_tri = (wv == 3'd3);
    wire        blep     = is_saw | is_sq | is_p25;
    wire        two_edge = is_sq | is_p25;
    // naive waveforms (6.4, 6.5)
    wire [16:0] tq = ph[23:7];
    wire signed [17:0] tri_hi = 18'sd98303 - $signed({1'b0, tq});
    wire [9:0]  sidx = ph[23:14];
    wire [7:0]  sa   = sidx[8] ? ~sidx[7:0] : sidx[7:0];
    wire [15:0] sq   = srom[sa];
    wire signed [15:0] sinev = sidx[9] ? -$signed(sq) : $signed(sq);
    wire signed [15:0] naive = is_saw ? $signed({~ph[23], ph[22:8]})
                             : is_sq  ? (ph[23] ? 16'sh8000 : 16'sh7FFF)
                             : is_p25 ? ((ph[23:22] == 2'b00) ? 16'sh7FFF : 16'sh8000)
                             : is_tri ? (tq[16] ? $signed(tri_hi[15:0]) : $signed({~tq[15], tq[14:0]}))
                             : sinev;
    // PolyBLEP windows (6.6.3, 6.6.4): win[1] selects the shifted phase, win[0] the side of the edge
    wire [23:0] P   = win[1] ? (ph + (is_sq ? 24'h800000 : 24'hC00000)) : ph;
    wire [24:0] q   = 25'h1000000 - {1'b0, P};
    wire        active = win[0] ? (q < {1'b0, inc}) : (P < inc);
    wire [23:0] x   = win[0] ? q[23:0] : P;
    wire [38:0] xs  = {x, 15'b0} >> sh[kk];
    wire [15:0] p   = xs[15:0];                                   // 6.6.2
    wire [15:0] u   = mr[30:15];                                  // (p * r) >> 15, < 2^16
    wire [16:0] s   = 17'h10000 - {1'b0, u};                      // 1..65536
    wire [15:0] c   = mr[32:17];                                  // (s * s) >> 17, 0..32768
    wire        last_win = (win == 2'd3) || (win == 2'd1 && !two_edge);
    // the oscillator sample (6.6.4) and the mixer term (7)
    wire signed [17:0] osc_raw = is_saw ? ($signed({{2{naive[15]}}, naive}) - c_pp)
                               : two_edge ? ($signed({{2{naive[15]}}, naive}) + c_pp - c_ps)
                               : $signed({{2{naive[15]}}, naive});
    wire signed [15:0] osc = (osc_raw > 18'sd32767) ? 16'sd32767 : (osc_raw < -18'sd32768) ? -16'sd32768 : osc_raw[15:0];

    // ---- envelopes (8.3) --------------------------------------------------------------
    function [25:0] env_update(input g_, input [1:0] seg, input [23:0] level,
                               input [23:0] ai, input [23:0] dd, input [23:0] su, input [23:0] dec);
        reg [24:0] sum; reg signed [25:0] diff; reg [23:0] step;
        begin
            if (g_) begin
                case (seg)
                    2'd0: begin sum = {1'b0, level} + {1'b0, ai};
                                if (sum >= 25'h0FFFFFF) env_update = {2'd1, 24'hFFFFFF};
                                else env_update = {2'd0, sum[23:0]}; end
                    2'd1: begin diff = $signed({2'b00, level}) - $signed({2'b00, dd});
                                if (diff <= $signed({2'b00, su})) env_update = {2'd2, su};
                                else env_update = {2'd1, diff[23:0]}; end
                    default: env_update = {seg, su};
                endcase
            end else begin
                step = (dec == 24'd0) ? 24'd1 : dec;
                diff = $signed({2'b00, level}) - $signed({2'b00, step});
                env_update = {seg, diff[25] ? 24'd0 : diff[23:0]};
            end
        end
    endfunction

    // ---- cutoff (10), for the voice (cut) and the drum filter (dcut, clamped) ----------
    wire signed [16:0] span = $signed({1'b0, cut_hi}) - $signed({1'b0, cut_lo});
    wire signed [16:0] t    = mr[31:15];                          // (span * fe) >> 15
    wire signed [18:0] cut_raw = $signed({3'b0, cut_lo}) + $signed({{2{t[16]}}, t}) + $signed({3'b0, track_hz});
    wire [14:0] cut_n  = (cut_raw < 19'sd30) ? 15'd30 : (cut_raw > 19'sd21600) ? 15'd21600 : cut_raw[14:0];
    wire [14:0] dcut_c = (dcut < 16'd30) ? 15'd30 : (dcut > 16'd21600) ? 15'd21600 : dcut[14:0];
    wire        dphase = (state >= S_DC0) && (state <= S_DC5);
    wire [14:0] rc  = dphase ? dcut_c : cut;                      // which cutoff the ROMs serve
    wire [6:0]  gi  = rc[14:8];
    wire [7:0]  gf  = rc[7:0];
    wire [4:0]  ki  = rc[14:10];
    wire [9:0]  kf  = rc[9:0];
    wire        rom_second = (state == S_ROM1) || (state == S_DC1);
    wire [15:0] grd = rom_second ? grom[gi + 7'd1] : grom[gi];
    wire [15:0] krd = rom_second ? krom[ki + 5'd1] : krom[ki];
    wire [15:0] kc_n = kc0 + mr[25:10];                           // kc0 + ((kd * frac) >> 10)

    // ---- glide slew (6.7) ---------------------------------------------------------------
    wire [31:0] tgt   = {inc_tgt[kk], 8'b0};
    wire [55:0] Pfull = {mr[39:0], 16'b0} + {16'b0, pacc};       // inc_acc * glide, exact
    wire [31:0] d     = Pfull[55:24];
    wire [31:0] dmax  = (d == 32'd0) ? 32'd1 : d;
    wire signed [33:0] acc_up = $signed({2'b0, inc_acc[kk]}) + $signed({2'b0, dmax});
    wire signed [33:0] acc_dn = $signed({2'b0, inc_acc[kk]}) - $signed({2'b0, dmax});

    // ---- output (9, 12; ARCHITECTURE.md 4) ---------------------------------------------
    wire signed [19:0] msh = mixacc[34:15];
    wire signed [20:0] osum = {out_v[19], out_v} + {out_d[19], out_d};
    function signed [15:0] sat16(input signed [20:0] v);
        sat16 = (v > 21'sd32767) ? 16'sd32767 : (v < -21'sd32768) ? -16'sd32768 : v[15:0];
    endfunction
    function signed [15:0] sat16m(input signed [19:0] v);
        sat16m = (v > 20'sd32767) ? 16'sd32767 : (v < -20'sd32768) ? -16'sd32768 : v[15:0];
    endfunction
    function signed [15:0] sat16d(input signed [18:0] v);
        sat16d = (v > 19'sd32767) ? 16'sd32767 : (v < -19'sd32768) ? -16'sd32768 : v[15:0];
    endfunction

    integer i;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (i = 0; i < 3; i = i + 1) begin
                inc_tgt[i] <= 0; inc_acc[i] <= 0; wave[i] <= 0; w[i] <= 0;
                phase[i] <= 0; sh[i] <= 5'd15; r[i] <= 0; inc_er[i] <= 0;
            end
            a_inc_a <= 0; d_dec_a <= 0; sus_a <= 0; rate_a <= 0; a_inc_f <= 0; d_dec_f <= 0; sus_f <= 0; rate_f <= 0;
            gate <= 0; glide <= 0; vol <= 0; dvol <= 0; dfilt <= 0; cut_lo <= 0; cut_hi <= 0; track_hz <= 0;
            k <= 0; gain <= 0; ogain <= 0; dcut <= 0; dk <= 0; dgain <= 0; dogain <= 0;
            level_a <= 0; level_f <= 0; seg_a <= 0; seg_f <= 0;
            state <= S_IDLE; kk <= 0; win <= 0; c_pp <= 0; c_ps <= 0; mixacc <= 0; y_seen <= 0; d_seen <= 0;
            g0 <= 0; g1 <= 0; kc0 <= 0; kc1 <= 0; kd <= 0; pacc <= 0; out_v <= 0; out_d <= 0; d19 <= 0;
            ma <= 0; mb <= 0; div_start <= 0; div_inc <= 0; lad_sv <= 0; lad_ch <= 0; g <= 0; g2 <= 0; k_eff2 <= 0; dx <= 0;
            sample <= 0; sample_valid <= 0; mixed <= 0; ae <= 0; fe <= 0; cut <= 0; k_eff <= 0; y19 <= 0;
        end else begin
            sample_valid <= 1'b0; div_start <= 1'b0; lad_sv <= 1'b0;
            if (lad_yv && !lad_ych) begin y19 <= lad_y; y_seen <= 1'b1; end
            if (lad_yv &&  lad_ych) begin d19 <= lad_y; d_seen <= 1'b1; end
            case (state)
                S_IDLE: if (go) begin state <= S_RCHK; kk <= 2'd0; mixacc <= 0; end
                // ---- 1. reciprocals ----
                S_RCHK: begin
                    if (inc != inc_er[kk]) begin
                        div_start <= 1'b1; div_inc <= inc; state <= S_RWAIT;
                    end else if (kk == 2'd2) begin
                        state <= S_WIN; kk <= 2'd0; win <= 2'd0; c_pp <= 0; c_ps <= 0;
                    end else kk <= kk + 2'd1;
                end
                S_RWAIT: if (div_done) begin
                    sh[kk] <= div_sh; r[kk] <= div_r; inc_er[kk] <= inc;
                    if (kk == 2'd2) begin state <= S_WIN; kk <= 2'd0; win <= 2'd0; c_pp <= 0; c_ps <= 0; end
                    else begin kk <= kk + 2'd1; state <= S_RCHK; end
                end
                // ---- 2. oscillators ----
                S_WIN: begin
                    if (!blep) state <= S_MIX;
                    else if (!active) begin
                        if (last_win) state <= S_MIX; else win <= win + 2'd1;
                    end else begin
                        ma <= {9'b0, p}; mb <= {5'b0, r[kk]}; state <= S_W1;
                    end
                end
                S_W1: begin ma <= {8'b0, s}; mb <= {4'b0, s}; state <= S_W2; end
                S_W2: begin
                    case (win)
                        2'd0: c_pp <= -$signed({1'b0, c});
                        2'd1: c_pp <=  $signed({1'b0, c});
                        2'd2: c_ps <= -$signed({1'b0, c});
                        default: c_ps <= $signed({1'b0, c});
                    endcase
                    if (last_win) state <= S_MIX; else begin win <= win + 2'd1; state <= S_WIN; end
                end
                S_MIX: begin
                    ma <= {{9{osc[15]}}, osc}; mb <= {5'b0, w[kk]};
                    phase[kk] <= ph + inc;                                    // step 9: advance
                    state <= S_ACC;
                end
                S_ACC: begin
                    mixacc <= mixacc + {{3{mr[31]}}, mr[31:0]};
                    if (kk == 2'd2) state <= S_ENV;
                    else begin kk <= kk + 2'd1; win <= 2'd0; c_pp <= 0; c_ps <= 0; state <= S_WIN; end
                end
                // ---- 3, 4. envelope outputs, cutoff ----
                S_ENV: begin
                    ae <= level_a[23:9]; fe <= level_f[23:9];
                    ma <= {{8{span[16]}}, span}; mb <= {6'b0, level_f[23:9]};
                    state <= S_CUT1;
                end
                S_CUT1: begin cut <= cut_n; state <= S_ROM0; end
                S_ROM0: begin g0 <= grd; kc0 <= krd; state <= S_ROM1; end
                S_ROM1: begin g1 <= grd; kc1 <= krd; state <= S_ROM2; end
                S_ROM2: begin
                    ma <= {9'b0, g1 - g0}; mb <= {13'b0, gf};
                    kd <= $signed({1'b0, kc1}) - $signed({1'b0, kc0});
                    state <= S_ROM3;
                end
                S_ROM3: begin
                    g  <= g0 + mr[23:8];
                    ma <= {{8{kd[16]}}, kd}; mb <= {11'b0, kf};
                    state <= S_KEFF0;
                end
                S_KEFF0: begin ma <= {8'b0, k}; mb <= {5'b0, kc_n}; state <= S_KEFF1; end
                S_KEFF1: begin k_eff <= mr[32] ? 17'h1FFFF : mr[31:15]; state <= S_LGO; end
                // ---- 5. the voice's ladder context starts ----
                S_LGO: begin
                    mixed <= sat16m(msh); lad_sv <= 1'b1; lad_ch <= 1'b0; y_seen <= 1'b0; d_seen <= 1'b0;
                    ma <= {1'b0, level_a}; mb <= {5'b0, rate_a};
                    state <= S_EA1;
                end
                // ---- step 9 while the ladder runs: envelope updates, glide slews ----
                S_EA1: begin
                    {seg_a, level_a} <= env_update(gate, seg_a, level_a, a_inc_a, d_dec_a, sus_a, mr[39:16]);
                    ma <= {1'b0, level_f}; mb <= {5'b0, rate_f};
                    state <= S_EF1;
                end
                S_EF1: begin
                    {seg_f, level_f} <= env_update(gate, seg_f, level_f, a_inc_f, d_dec_f, sus_f, mr[39:16]);
                    kk <= 2'd0; state <= S_SL0;
                end
                S_SL0: begin
                    if (inc_acc[kk] == tgt) begin
                        if (kk == 2'd2) state <= S_DC0; else kk <= kk + 2'd1;
                    end else if (glide == 24'd0) begin
                        inc_acc[kk] <= tgt;
                        if (kk == 2'd2) state <= S_DC0; else kk <= kk + 2'd1;
                    end else begin
                        ma <= {1'b0, glide}; mb <= {5'b0, inc_acc[kk][15:0]}; state <= S_SL1;
                    end
                end
                S_SL1: begin pacc <= mr[39:0]; ma <= {1'b0, glide}; mb <= {5'b0, inc_acc[kk][31:16]}; state <= S_SL2; end
                S_SL2: begin
                    if (tgt > inc_acc[kk]) inc_acc[kk] <= (acc_up > $signed({2'b0, tgt})) ? tgt : acc_up[31:0];
                    else                   inc_acc[kk] <= (acc_dn < $signed({2'b0, tgt})) ? tgt : acc_dn[31:0];
                    if (kk == 2'd2) state <= S_DC0; else begin kk <= kk + 2'd1; state <= S_SL0; end
                end
                // ---- the drum filter's coefficients (same ROMs, DCUT; DK x kc) ----
                S_DC0: begin g0 <= grd; kc0 <= krd; state <= S_DC1; end
                S_DC1: begin g1 <= grd; kc1 <= krd; state <= S_DC2; end
                S_DC2: begin
                    ma <= {9'b0, g1 - g0}; mb <= {13'b0, gf};
                    kd <= $signed({1'b0, kc1}) - $signed({1'b0, kc0});
                    state <= S_DC3;
                end
                S_DC3: begin g2 <= g0 + mr[23:8]; ma <= {{8{kd[16]}}, kd}; mb <= {11'b0, kf}; state <= S_DC4; end
                S_DC4: begin ma <= {8'b0, dk}; mb <= {5'b0, kc_n}; state <= S_DC5; end
                S_DC5: begin k_eff2 <= mr[32] ? 17'h1FFFF : mr[31:15]; state <= S_YWAIT; end
                // ---- 6. the voice context done: launch the drum filter, then the VCA ----
                S_YWAIT: if (y_seen) begin
                    if (dfilt) begin
                        if (drum_done) begin
                            dx <= sat16d(drum_bus); lad_sv <= 1'b1; lad_ch <= 1'b1; state <= S_VCA0;
                        end
                    end else state <= S_VCA0;
                end
                S_VCA0: begin ma <= {{6{y19[18]}}, y19}; mb <= {6'b0, ae}; state <= S_VCA1; end
                S_VCA1: begin ma <= mr[39:15]; mb <= {5'b0, vol}; state <= S_VCA2; end
                S_VCA2: begin out_v <= mr[34:15]; state <= S_DWAIT; end
                // ---- 7. the master mix, one rail ----
                S_DWAIT: begin
                    if (dfilt) begin
                        if (d_seen) begin ma <= {{6{d19[18]}}, d19}; mb <= {5'b0, dvol}; state <= S_OUT1; end
                    end else if (drum_done) begin
                        ma <= {{6{drum_bus[18]}}, drum_bus}; mb <= {5'b0, dvol}; state <= S_OUT1;
                    end
                end
                S_OUT1: begin out_d <= mr[34:15]; state <= S_OUT2; end
                default: begin                                                // S_OUT2
                    sample <= sat16(osum); sample_valid <= 1'b1; state <= S_IDLE;
                end
            endcase

            // ---- the register write port (DR 0007 section 3); applied while idle ----
            if (wr_valid) case (wr_addr)
                7'h00, 7'h01, 7'h02: begin
                    inc_tgt[wr_addr[1:0]] <= wr_data;
                    if (wr_flag || glide == 24'd0) inc_acc[wr_addr[1:0]] <= {wr_data, 8'b0};
                end
                7'h04, 7'h05, 7'h06: wave[wr_addr[1:0]] <= wr_data[2:0];
                7'h08, 7'h09, 7'h0A: w[wr_addr[1:0]] <= wr_data[15:0];
                7'h0C: glide <= wr_data;
                7'h0D: vol <= wr_data[15:0];
                7'h0E: dvol <= wr_data[15:0];
                7'h0F: dfilt <= wr_data[0];
                7'h10: a_inc_a <= wr_data;  7'h11: d_dec_a <= wr_data;  7'h12: sus_a <= wr_data;  7'h13: rate_a <= wr_data[15:0];
                7'h14: a_inc_f <= wr_data;  7'h15: d_dec_f <= wr_data;  7'h16: sus_f <= wr_data;  7'h17: rate_f <= wr_data[15:0];
                7'h18: cut_lo <= wr_data[15:0];  7'h19: cut_hi <= wr_data[15:0];  7'h1A: track_hz <= wr_data[15:0];
                7'h1C: k <= wr_data[16:0];  7'h1D: gain <= wr_data[19:0];  7'h1E: ogain <= wr_data[19:0];
                7'h20: begin gate <= 1'b1; seg_a <= 2'd0; seg_f <= 2'd0; end   // GATE_ON
                7'h21: gate <= 1'b0;                                           // GATE_OFF
                7'h22: begin seg_a <= 2'd0; seg_f <= 2'd0; end                 // TRIG
                7'h28: dcut <= wr_data[15:0];  7'h29: dk <= wr_data[16:0];
                7'h2A: dgain <= wr_data[19:0]; 7'h2B: dogain <= wr_data[19:0];
                default: ;                                                     // RESET is rst_n; NOP, reserved, drums
            endcase
        end
    end
endmodule
`default_nettype wire
