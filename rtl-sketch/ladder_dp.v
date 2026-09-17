// ladder_dp.v -- AREA SKETCH ONLY, not a verified design.
//
// Time-shared Huovilainen ladder datapath, to answer one question: how much
// bigger does the chip get if it has a real Moog filter in it?
//
// Structure: the four stages are NOT four parallel datapaths. One multiplier
// and one tanh ROM are sequenced across 5 tanh evaluations x 2 oversample
// steps = 10 passes per output sample. At 12.288 MHz and 48 kHz there are 256
// clocks per sample, so 10 passes is comfortable.
//
//   y_k += g * (w_{k-1} - w_k)      then    w_k = tanh(y_k)
//
// Fixed point (the point of the sketch): Q1.15 signal, Q0.16 coefficient,
// 24-bit state to give the integrators headroom in the feedback loop.
`default_nettype none
module ladder_dp #(
    parameter SW = 24,          // state width
    parameter TW = 16           // tanh table / signal width
)(
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 sample_valid,
    input  wire signed [TW-1:0] x_in,        // Q1.15 input sample
    input  wire        [15:0]   g,           // Q0.16 cutoff coefficient
    input  wire        [15:0]   k,           // Q2.14 resonance (4*r)
    output reg  signed [TW-1:0] y_out,
    output reg                  y_valid
);
    // ---- tanh table: 256 entries x 16 bits, quarter-symmetric in practice
    reg signed [TW-1:0] tanh_rom [0:255];
    initial $readmemh("tanh256.hex", tanh_rom);

    // ---- state
    reg signed [SW-1:0] y [0:3];
    reg signed [TW-1:0] w [0:3];
    reg signed [SW-1:0] d1, d2;        // half-sample delay in the feedback
    reg signed [TW-1:0] w_in;
    reg [3:0]  step;
    reg [1:0]  os;                     // oversample phase
    reg        busy;

    // ---- one shared multiplier
    reg  signed [TW-1:0] mul_a;
    reg  signed [15:0]   mul_b;
    wire signed [TW+15:0] mul_r = mul_a * mul_b;

    // ---- feedback input, computed once per oversample pass
    wire signed [SW-1:0] fb   = (d1 + d2) >>> 1;
    wire signed [SW+15:0] kfb = $signed(fb) * $signed({1'b0, k});
    wire signed [TW-1:0] u    = x_in - kfb[SW+13 -: TW];

    // ---- tanh address: take the top bits of the state as the table index
    function [7:0] taddr(input signed [SW-1:0] v);
        taddr = v[SW-2 -: 8] ^ 8'h80;   // signed -> unsigned index
    endfunction

    integer i;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (i = 0; i < 4; i = i + 1) begin y[i] <= 0; w[i] <= 0; end
            d1 <= 0; d2 <= 0; step <= 0; os <= 0; busy <= 0; y_valid <= 0;
        end else begin
            y_valid <= 1'b0;
            if (sample_valid && !busy) begin
                busy <= 1'b1; step <= 4'd0; os <= 2'd0;
                w_in <= tanh_rom[taddr({u, {(SW-TW){1'b0}}})];
            end else if (busy) begin
                case (step)
                    4'd0, 4'd2, 4'd4, 4'd6: begin        // integrate one stage
                        mul_a <= (step == 0) ? (w_in     - w[0])
                               : (step == 2) ? (w[0]     - w[1])
                               : (step == 4) ? (w[1]     - w[2])
                                             : (w[2]     - w[3]);
                        mul_b <= g;
                        step  <= step + 4'd1;
                    end
                    4'd1, 4'd3, 4'd5, 4'd7: begin        // accumulate + tanh
                        i = (step - 1) >> 1;
                        y[i] <= y[i] + $signed(mul_r[TW+15 -: SW]);
                        w[i] <= tanh_rom[taddr(y[i] + $signed(mul_r[TW+15 -: SW]))];
                        step <= step + 4'd1;
                    end
                    default: begin                        // end of an oversample pass
                        d2 <= d1; d1 <= y[3];
                        if (os == 2'd1) begin
                            y_out   <= y[3][SW-2 -: TW];
                            y_valid <= 1'b1;
                            busy    <= 1'b0;
                        end else begin
                            os   <= os + 2'd1;
                            step <= 4'd0;
                            w_in <= tanh_rom[taddr({u, {(SW-TW){1'b0}}})];
                        end
                    end
                endcase
            end
        end
    end
endmodule
`default_nettype wire
