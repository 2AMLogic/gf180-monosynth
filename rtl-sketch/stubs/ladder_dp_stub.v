// A module with the right ports that computes nothing. A harness that PASSES
// against this cannot detect anything.
`default_nettype none
module ladder_dp #(parameter SW=24, parameter TW=16, parameter TANH_LOG2N=4,
                   parameter AW=28, parameter OW=19, parameter ROM_FILE="")
  (input wire clk, input wire rst_n, input wire sample_valid,
   input wire signed [TW-1:0] x_in, input wire [15:0] g, input wire [16:0] k,
   input wire [19:0] gain, input wire [16:0] ogain,
   output reg signed [OW-1:0] y_out, output reg y_valid);
  always @(posedge clk) begin
    if (!rst_n) begin y_out <= 0; y_valid <= 0; end
    else begin y_valid <= sample_valid; y_out <= 0; end   // always zero
  end
endmodule
`default_nettype wire
