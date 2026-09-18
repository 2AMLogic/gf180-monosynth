// Cycles per sample for modal_dp; correctness is tb_modal_fx.v's job.
`timescale 1ns/1ps
module tb_modal;
    reg clk=0, rst_n=0, sample_valid=0; reg signed [15:0] exc=0;
    wire signed [15:0] y_out; wire y_valid;
    modal_dp dut(.clk(clk),.rst_n(rst_n),.sample_valid(sample_valid),.exc(exc),
      .a1_0(26'sd33552000),.a2_0(-26'sd16776000),.a1_1(26'sd33540000),.a2_1(-26'sd16775000),
      .a1_2(26'sd33500000),.a2_2(-26'sd16774000),.a1_3(26'sd33400000),.a2_3(-26'sd16773000),
      .amp0(16'd65535),.amp1(16'd39322),.amp2(16'd26214),.amp3(16'd16384),
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
