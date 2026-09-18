// tb_modal_fx.v -- bit-exact bench for modal_dp against model/modal_fixed.py.
//
// verify_modal.py runs the model and writes one 320-bit word per sample:
//   [319:304] exc            [303:80] a1_0 a2_0 a1_1 a2_1 a1_2 a2_2 a1_3 a2_3, 28-bit fields
//   [79:16]   amp0..amp3     [15:0]   y, the model's output
// Every y_out is written to +out= and compared against y with no tolerance.
// verify_modal.py is the comparator of record.
`timescale 1ns/1ps
module tb_modal_fx;
    parameter MAXN = 1 << 17;
    reg clk = 0, rst_n = 0, sample_valid = 0;
    reg signed [15:0] exc = 0;
    reg signed [25:0] a1_0 = 0, a2_0 = 0, a1_1 = 0, a2_1 = 0, a1_2 = 0, a2_2 = 0, a1_3 = 0, a2_3 = 0;
    reg [15:0] amp0 = 0, amp1 = 0, amp2 = 0, amp3 = 0;
    wire signed [15:0] y_out; wire y_valid;
    modal_dp dut (.clk(clk), .rst_n(rst_n), .sample_valid(sample_valid), .exc(exc),
        .a1_0(a1_0), .a2_0(a2_0), .a1_1(a1_1), .a2_1(a2_1), .a1_2(a1_2), .a2_2(a2_2), .a1_3(a1_3), .a2_3(a2_3),
        .amp0(amp0), .amp1(amp1), .amp2(amp2), .amp3(amp3), .y_out(y_out), .y_valid(y_valid));
    always #10 clk = ~clk;

    reg [319:0] vec [0:MAXN-1];
    reg [8*256-1:0] vecfile, outfile;
    integer n, i, fd, nout, mism, first_i, first_exp, first_got, maxerr, err, timeout;
    reg signed [15:0] expv;

    always @(posedge clk) if (rst_n && y_valid) begin
        expv = vec[nout][15:0];
        if (^y_out === 1'bx) $fdisplay(fd, "x"); else $fdisplay(fd, "%0d", y_out);
        if (^y_out === 1'bx || y_out !== expv) begin
            if (mism == 0) begin first_i = nout; first_exp = expv; first_got = y_out; end
            mism = mism + 1;
        end
        err = (^y_out === 1'bx) ? 65536 : (y_out > expv) ? y_out - expv : expv - y_out;
        if (err > maxerr) maxerr = err;
        nout = nout + 1;
    end

    initial begin
        if (!$value$plusargs("vec=%s", vecfile)) vecfile = "build/modal_vectors.hex";
        if (!$value$plusargs("out=%s", outfile)) outfile = "build/modal_rtl_out.txt";
        for (i = 0; i < MAXN; i = i + 1) vec[i] = {320{1'bx}};
        $readmemh(vecfile, vec);
        n = 0; while (n < MAXN && vec[n] !== {320{1'bx}}) n = n + 1;
        fd = $fopen(outfile, "w");
        nout = 0; mism = 0; maxerr = 0; first_i = -1; first_exp = 0; first_got = 0;
        repeat (4) @(posedge clk); rst_n = 1; repeat (2) @(posedge clk);
        for (i = 0; i < n; i = i + 1) begin
            @(negedge clk);
            exc  = vec[i][319:304];
            a1_0 = vec[i][303:276]; a2_0 = vec[i][275:248]; a1_1 = vec[i][247:220]; a2_1 = vec[i][219:192];
            a1_2 = vec[i][191:164]; a2_2 = vec[i][163:136]; a1_3 = vec[i][135:108]; a2_3 = vec[i][107:80];
            amp0 = vec[i][79:64]; amp1 = vec[i][63:48]; amp2 = vec[i][47:32]; amp3 = vec[i][31:16];
            sample_valid = 1;
            @(negedge clk); sample_valid = 0;
            timeout = 0;
            while (!y_valid && timeout < 1000) begin @(negedge clk); timeout = timeout + 1; end
            if (timeout >= 1000) begin
                $display("tb_modal_fx: TIMEOUT -- no y_valid within 1000 clocks for sample %0d", i);
                $fclose(fd); $finish;
            end
        end
        repeat (2) @(posedge clk);
        $fclose(fd);
        $display("tb_modal_fx: %0d samples driven, %0d outputs, %0d mismatches, worst |error| %0d LSB",
                 n, nout, mism, maxerr);
        if (mism != 0)
            $display("tb_modal_fx: first mismatch at sample %0d: model %0d, RTL %0d", first_i, first_exp, first_got);
        if (mism == 0 && nout == n) $display("tb_modal_fx: PASS"); else $display("tb_modal_fx: FAIL");
        $finish;
    end
endmodule
