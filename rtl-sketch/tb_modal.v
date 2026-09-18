// Cycles per sample for modal_dp at 4 and 12 modes; correctness is tb_modal_fx.v's job.
`timescale 1ns/1ps
module tb_modal;
    parameter MODES = 4;
    parameter MW = 4;
    reg clk=0, rst_n=0, sample_valid=0, exc_we=0; reg [MW-1:0] exc_mode=0; reg signed [20:0] exc_val=0;
    reg [MODES*26-1:0] a1_bus, a2_bus; reg [MODES*16-1:0] amp_bus; reg [MODES*2-1:0] num_bus = 0;
    wire signed [18:0] y_out; wire y_valid; wire signed [27:0] tap_y1;
    modal_dp #(.MODES(MODES), .NUMS(MODES/2), .HR(0), .OW(19), .EW(21), .MW(MW)) dut(.clk(clk),.rst_n(rst_n),
      .exc_we(exc_we),.exc_mode(exc_mode),.exc_val(exc_val),.sample_valid(sample_valid),
      .a1_bus(a1_bus),.a2_bus(a2_bus),.amp_bus(amp_bus),.num_bus(num_bus),.tap_sel({MW{1'b0}}),.tap_y1(tap_y1),
      .y_out(y_out),.y_valid(y_valid));
    always #10 clk=~clk;
    integer cyc=0,started=0,total=0,n=0,worst=0,i,m;
    always @(posedge clk) begin
        if (started) cyc=cyc+1;
        if (y_valid && started) begin total=total+cyc; n=n+1; if(cyc>worst) worst=cyc; started=0; end
    end
    initial begin
        for (m = 0; m < MODES; m = m + 1) begin
            a1_bus[m*26 +: 26] = 26'sd33548016; a2_bus[m*26 +: 26] = -26'sd16771702; amp_bus[m*16 +: 16] = 16'd1000;
        end
        repeat(4) @(posedge clk); rst_n=1; repeat(2) @(posedge clk);
        for (i=0;i<32;i=i+1) begin
            @(negedge clk); exc_we = 1; exc_mode = 0; exc_val = (i==0) ? 21'sd12000 : 21'sd0;
            @(negedge clk); exc_we = 0;
            sample_valid=1; cyc=0; started=1;
            @(negedge clk); sample_valid=0;
            wait (y_valid==1'b1); @(negedge clk);
        end
        $display("modal_dp: %0d cycles/sample (worst %0d), %0d modes", total/n, worst, MODES);
        $finish;
    end
endmodule
