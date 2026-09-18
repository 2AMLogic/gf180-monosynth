// STRAWMAN, not design RTL. drum_kit.v takes a1_bus/a2_bus/amp_bus/num_bus as
// INPUT PORTS: the mode configuration storage does not exist in RTL anywhere in
// this repository -- tb_drums.v drives those buses from a file. This module is
// the smallest honest stand-in for what silicon must add: one host write port
// (contract 16.2's addr/data), MODES x (a1, a2, amp, num) registers, and the
// buses back out. It is measured, not guessed, and it is labelled a strawman
// everywhere it is quoted.
`default_nettype none
module mode_cfg_regs #(
    parameter MODES = 12,
    parameter CF    = 24
)(
    input  wire                    clk,
    input  wire                    rst_n,
    input  wire                    wr_valid,
    input  wire [6:0]              wr_addr,
    input  wire [23:0]             wr_data,
    output wire [MODES*(CF+2)-1:0] a1_bus,
    output wire [MODES*(CF+2)-1:0] a2_bus,
    output wire [MODES*16-1:0]     amp_bus,
    output wire [MODES*2-1:0]      num_bus
);
    localparam CW = CF + 2;
    reg signed [CW-1:0] a1  [0:MODES-1];
    reg signed [CW-1:0] a2  [0:MODES-1];
    reg        [15:0]   amp [0:MODES-1];
    reg        [1:0]    num [0:MODES-1];
    integer i;
    wire [$clog2(MODES)-1:0] sel = wr_addr[$clog2(MODES)+1:2];
    always @(posedge clk) begin
        if (!rst_n) begin
            for (i = 0; i < MODES; i = i + 1) begin
                a1[i] <= {CW{1'b0}}; a2[i] <= {CW{1'b0}};
                amp[i] <= 16'd0;     num[i] <= 2'd0;
            end
        end else if (wr_valid) begin
            case (wr_addr[1:0])
                2'd0: a1[sel]  <= wr_data[CW-1:0];
                2'd1: a2[sel]  <= wr_data[CW-1:0];
                2'd2: amp[sel] <= wr_data[15:0];
                2'd3: num[sel] <= wr_data[1:0];
            endcase
        end
    end
    genvar g;
    generate for (g = 0; g < MODES; g = g + 1) begin : pack
        assign a1_bus [(g+1)*CW-1 -: CW] = a1[g];
        assign a2_bus [(g+1)*CW-1 -: CW] = a2[g];
        assign amp_bus[(g+1)*16-1 -: 16] = amp[g];
        assign num_bus[(g+1)*2-1  -: 2 ] = num[g];
    end endgenerate
endmodule
`default_nettype wire
