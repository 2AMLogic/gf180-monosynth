// Measure the ladder datapath's ACTUAL cycles per output sample, rather than
// counting sequencer steps by eye. Budget is 256 clocks (12.288 MHz / 48 kHz).
// Correctness is tb_ladder.v's job; this bench only times the handshake.
`timescale 1ns/1ps
module tb_cycles;
    reg clk=0, rst_n=0, sample_valid=0;
    reg signed [15:0] x_in=0;
    reg [15:0] g=16'd2000;            // ~300 Hz
    reg [16:0] k=17'd52429;           // res 0.8
    reg [19:0] gain=20'd340787;       // drive 2.0
    reg [19:0] ogain=20'd65536;       // res 0.8
    wire signed [15:0] y_out; wire y_valid;
    ladder_dp dut(.clk(clk), .rst_n(rst_n), .sample_valid(sample_valid), .x_in(x_in),
                  .g(g), .k(k), .gain(gain), .ogain(ogain), .y_out(y_out), .y_valid(y_valid));
    always #10 clk = ~clk;
    integer cyc=0, started=0, total=0, n=0, worst=0;
    always @(posedge clk) begin
        if (started) cyc = cyc + 1;
        if (y_valid && started) begin
            total = total + cyc; n = n + 1;
            if (cyc > worst) worst = cyc;
            started = 0;
        end
    end
    integer i;
    initial begin
        repeat(4) @(posedge clk); rst_n = 1;
        repeat(2) @(posedge clk);
        for (i = 0; i < 64; i = i + 1) begin
            @(negedge clk);
            x_in = $signed(16'd8000) * ((i % 2) ? 1 : -1);
            sample_valid = 1; cyc = 0; started = 1;
            @(negedge clk); sample_valid = 0;
            wait (y_valid == 1'b1);
            @(negedge clk);
        end
        $display("samples measured : %0d", n);
        $display("cycles/sample    : mean %0d, worst %0d", total/n, worst);
        $display("budget           : 256 clocks at 12.288 MHz / 48 kHz");
        $display("filter uses      : %0d%% of the per-sample budget", (worst*100)/256);
        $display("remaining        : %0d clocks for oscillators, envelopes, drums, mixer", 256-worst);
        $finish;
    end
endmodule
