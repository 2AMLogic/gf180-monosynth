`timescale 1ns/1ps
module tb_modal;
    reg clk=0, rst_n=0, sample_valid=0; reg signed [15:0] exc=0;
    wire signed [15:0] y_out; wire y_valid;
    modal_dp dut(.clk(clk),.rst_n(rst_n),.sample_valid(sample_valid),.exc(exc),
      .a1_0(18'sd120000),.a2_0(-18'sd65000),.a1_1(18'sd118000),.a2_1(-18'sd64000),
      .a1_2(18'sd110000),.a2_2(-18'sd63000),.a1_3(18'sd100000),.a2_3(-18'sd62000),
      .amp0(16'd32767),.amp1(16'd20000),.amp2(16'd13000),.amp3(16'd8000),
      .y_out(y_out),.y_valid(y_valid));
    always #10 clk=~clk;
    integer cyc=0,started=0,total=0,n=0,worst=0,i;
    always @(posedge clk) begin
        if (started) cyc=cyc+1;
        if (y_valid && started) begin total=total+cyc; n=n+1; if(cyc>worst) worst=cyc; started=0; end
    end
    initial begin
        repeat(4) @(posedge clk); rst_n=1; repeat(2) @(posedge clk);
        for (i=0;i<32;i=i+1) begin
            @(negedge clk); exc = (i==0)? 16'sd12000 : 16'sd0;
            sample_valid=1; cyc=0; started=1;
            @(negedge clk); sample_valid=0;
            wait (y_valid==1'b1); @(negedge clk);
        end
        $display("modal_dp: %0d cycles/sample (worst %0d), 4 modes", total/n, worst);
        $finish;
    end
endmodule
