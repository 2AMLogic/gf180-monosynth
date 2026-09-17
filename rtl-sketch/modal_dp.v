// modal_dp.v -- AREA SKETCH ONLY. Modal resonator bank: the "something you can
// hit" engine.
//
// Each mode is a two-pole resonator, y[n] = x[n] + a1*y[n-1] + a2*y[n-2],
// excited by a short noise burst. Ringing comes from the recursion, so there
// is NO DELAY LINE and therefore no RAM -- the entire state is 2 registers per
// mode. That is the whole reason this is the cheap physical-modelling option:
// Karplus-Strong needs SR/f0 samples of memory per voice (1.2 KB at low E),
// modal needs eight registers total for four modes.
//
// Inharmonic mode ratios are what make it sound struck rather than plucked;
// a free bar is 1 : 2.76 : 5.40 : 8.93.
`default_nettype none
module modal_dp #(
    parameter MODES = 4,
    parameter SW    = 24,       // state width
    parameter CW    = 18        // coefficient width, Q2.16
)(
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 sample_valid,
    input  wire signed [15:0]   exc,            // excitation (noise burst)
    input  wire signed [CW-1:0] a1_0, a2_0, a1_1, a2_1,
    input  wire signed [CW-1:0] a1_2, a2_2, a1_3, a2_3,
    input  wire        [15:0]   amp0, amp1, amp2, amp3,
    output reg  signed [15:0]   y_out,
    output reg                  y_valid
);
    reg signed [SW-1:0] y1 [0:MODES-1];
    reg signed [SW-1:0] y2 [0:MODES-1];
    reg signed [SW+CW-1:0] acc;
    reg signed [SW-1:0] mix;
    reg [2:0] mode;
    reg [1:0] step;
    reg busy;

    // one shared multiplier, sequenced across modes x 2 coefficients
    reg  signed [SW-1:0] ma;
    reg  signed [CW-1:0] mb;
    wire signed [SW+CW-1:0] mr = ma * mb;

    function signed [CW-1:0] sel_a1(input [2:0] m);
        sel_a1 = (m==0)?a1_0:(m==1)?a1_1:(m==2)?a1_2:a1_3;
    endfunction
    function signed [CW-1:0] sel_a2(input [2:0] m);
        sel_a2 = (m==0)?a2_0:(m==1)?a2_1:(m==2)?a2_2:a2_3;
    endfunction
    function [15:0] sel_amp(input [2:0] m);
        sel_amp = (m==0)?amp0:(m==1)?amp1:(m==2)?amp2:amp3;
    endfunction

    integer i;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (i=0;i<MODES;i=i+1) begin y1[i]<=0; y2[i]<=0; end
            mode<=0; step<=0; busy<=0; y_valid<=0; mix<=0;
        end else begin
            y_valid <= 1'b0;
            if (sample_valid && !busy) begin
                busy<=1'b1; mode<=0; step<=0; mix<=0;
                ma <= y1[0]; mb <= sel_a1(3'd0);
            end else if (busy) begin
                case (step)
                    2'd0: begin acc <= mr; ma <= y2[mode]; mb <= sel_a2(mode); step<=2'd1; end
                    2'd1: begin acc <= acc + mr; step<=2'd2; end
                    2'd2: begin
                        y2[mode] <= y1[mode];
                        y1[mode] <= $signed(acc[SW+CW-1 -: SW]) + {{(SW-16){exc[15]}}, exc};
                        ma <= $signed(acc[SW+CW-1 -: SW]); mb <= {2'b0, sel_amp(mode)};
                        step <= 2'd3;
                    end
                    default: begin
                        mix <= mix + $signed(mr[SW+CW-1 -: SW]);
                        if (mode == MODES-1) begin
                            y_out   <= mix[SW-2 -: 16];
                            y_valid <= 1'b1;
                            busy    <= 1'b0;
                        end else begin
                            mode <= mode + 3'd1; step <= 2'd0;
                            ma <= y1[mode+1]; mb <= sel_a1(mode+3'd1);
                        end
                    end
                endcase
            end
        end
    end
endmodule
`default_nettype wire
