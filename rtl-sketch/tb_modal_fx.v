// tb_modal_fx.v -- bit-exact bench for modal_dp against model/modal_fixed.py.
//
// verify_modal.py runs the model and writes one 336-bit word per sample:
//   [335:320] exc (Q1.15, pushed to EVERY mode through the accumulate port)
//   [319:96]  a1_0 a2_0 a1_1 a2_1 a1_2 a2_2 a1_3 a2_3, 28-bit fields
//   [95:32]   amp0..amp3      [31:24] num3 num2 num1 num0, 2 bits each
//   [23:0]    y, the model's output, sign-extended from OW bits
// Every y_out is written to +out= and compared against y with no tolerance.
// verify_modal.py is the comparator of record.
`timescale 1ns/1ps
module tb_modal_fx;
    parameter NUMS = 2;
    parameter MAXN = 1 << 17;
    reg clk = 0, rst_n = 0, sample_valid = 0, exc_we = 0;
    reg [1:0] exc_mode = 0;
    reg signed [20:0] exc_val = 0;
    reg [4*26-1:0] a1_bus = 0, a2_bus = 0;
    reg [4*16-1:0] amp_bus = 0;
    reg [4*2-1:0]  num_bus = 0;
    wire signed [18:0] y_out; wire y_valid;
    wire signed [27:0] tap_y1;
    modal_dp #(.MODES(4), .NUMS(NUMS), .HR(10), .OW(19), .EW(21), .MW(2)) dut (
        .clk(clk), .rst_n(rst_n), .exc_we(exc_we), .exc_mode(exc_mode), .exc_val(exc_val),
        .sample_valid(sample_valid), .a1_bus(a1_bus), .a2_bus(a2_bus), .amp_bus(amp_bus), .num_bus(num_bus),
        .tap_sel(2'd0), .tap_y1(tap_y1), .y_out(y_out), .y_valid(y_valid));
    always #10 clk = ~clk;

    reg [335:0] vec [0:MAXN-1];
    reg [8*256-1:0] vecfile, outfile;
    integer n, i, m, fd, nout, mism, first_i, first_exp, first_got, maxerr, err, timeout;
    reg signed [23:0] expv;
    reg signed [15:0] exc16;

    always @(posedge clk) if (rst_n && y_valid) begin
        expv = vec[nout][23:0];
        if (^y_out === 1'bx) $fdisplay(fd, "x"); else $fdisplay(fd, "%0d", y_out);
        if (^y_out === 1'bx || y_out !== expv[18:0]) begin
            if (mism == 0) begin first_i = nout; first_exp = expv; first_got = y_out; end
            mism = mism + 1;
        end
        err = (^y_out === 1'bx) ? (1 << 19) : (y_out > expv) ? y_out - expv : expv - y_out;
        if (err > maxerr) maxerr = err;
        nout = nout + 1;
    end

    initial begin
        if (!$value$plusargs("vec=%s", vecfile)) vecfile = "build/modal_vectors.hex";
        if (!$value$plusargs("out=%s", outfile)) outfile = "build/modal_rtl_out.txt";
        for (i = 0; i < MAXN; i = i + 1) vec[i] = {336{1'bx}};
        $readmemh(vecfile, vec);
        n = 0; while (n < MAXN && vec[n] !== {336{1'bx}}) n = n + 1;
        fd = $fopen(outfile, "w");
        nout = 0; mism = 0; maxerr = 0; first_i = -1; first_exp = 0; first_got = 0;
        repeat (4) @(posedge clk); rst_n = 1; repeat (2) @(posedge clk);
        for (i = 0; i < n; i = i + 1) begin
            @(negedge clk);
            exc16 = vec[i][335:320];
            for (m = 0; m < 4; m = m + 1) begin
                a1_bus[m*26 +: 26] = vec[i][(317 - m*56) -: 26];
                a2_bus[m*26 +: 26] = vec[i][(289 - m*56) -: 26];
                amp_bus[m*16 +: 16] = vec[i][(95 - m*16) -: 16];
                num_bus[m*2 +: 2]   = vec[i][(24 + m*2) +: 2];
            end
            // push the excitation to every mode, one accumulate per clock
            for (m = 0; m < 4; m = m + 1) begin
                exc_we = 1; exc_mode = m; exc_val = {{5{exc16[15]}}, exc16};
                @(negedge clk);
            end
            exc_we = 0;
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
