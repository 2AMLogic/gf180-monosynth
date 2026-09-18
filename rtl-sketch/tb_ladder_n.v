// tb_ladder.v -- bit-exact bench for ladder_dp against model/fixed.py.
//
// verify_ladder.py runs the model and writes one 120-bit word per sample:
//   [119:104] x_in  Q1.15      [103:88] g  Q0.16       [87:64] k  Q3.14 (17 used)
//   [63:40]   gain  Q4.16      [39:16]  ogain Q4.16    [15:0]  y  the model's output
// This bench drives the DUT with the first five, writes every y_out to +out=,
// and compares each against the sixth with no tolerance. verify_ladder.py is
// the comparator of record; the summary printed here is a convenience.
`timescale 1ns/1ps
module tb_ladder_n;
    parameter NCH      = 1;
    localparam CHW = (NCH > 1) ? $clog2(NCH) : 1;
    reg [CHW-1:0] ch = 0; wire [CHW-1:0] y_ch; integer c;
    parameter LOG2N    = 4;
    parameter ROM_FILE = "tanh16.hex";
    parameter MAXN     = 1 << 17;

    reg clk = 0, rst_n = 0, sample_valid = 0;
    reg signed [15:0] x_in = 0;
    reg        [15:0] g = 0;
    reg        [16:0] k = 0;
    reg        [19:0] gain = 0, ogain = 0;
    wire signed [15:0] y_out;
    wire               y_valid;

    ladder_dp_n #(.TANH_LOG2N(LOG2N), .ROM_FILE(ROM_FILE), .NCH(NCH)) dut (
        .clk(clk), .rst_n(rst_n), .sample_valid(sample_valid), .ch(ch), .x_in(x_in),
        .g(g), .k(k), .gain(gain), .ogain(ogain), .y_out(y_out), .y_valid(y_valid), .y_ch(y_ch));

    always #10 clk = ~clk;

    reg [119:0] vec [0:MAXN-1];
    reg [8*256-1:0] vecfile, outfile;
    integer n, i, fd, nout, mism, first_i, first_exp, first_got, maxerr, err, timeout;
    reg signed [15:0] expv;

    // Every y_valid is one output sample: record it and score it.
    always @(posedge clk) if (rst_n && y_valid) begin
        expv = vec[nout / NCH][15:0];
        if (y_ch !== nout % NCH) mism = mism + 1000000;
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
        if (!$value$plusargs("vec=%s", vecfile)) vecfile = "build/ladder_vectors.hex";
        if (!$value$plusargs("out=%s", outfile)) outfile = "build/ladder_rtl_out.txt";
        for (i = 0; i < MAXN; i = i + 1) vec[i] = {120{1'bx}};
        $readmemh(vecfile, vec);
        n = 0; while (n < MAXN && vec[n] !== {120{1'bx}}) n = n + 1;
        fd = $fopen(outfile, "w");
        nout = 0; mism = 0; maxerr = 0; first_i = -1; first_exp = 0; first_got = 0;
        repeat (4) @(posedge clk); rst_n = 1; repeat (2) @(posedge clk);
        for (i = 0; i < n; i = i + 1) begin
            @(negedge clk);
            x_in  = vec[i][119:104]; g = vec[i][103:88]; k = vec[i][87:64];
            gain  = vec[i][63:40];   ogain = vec[i][39:16];
            for (c = 0; c < NCH; c = c + 1) begin
                ch = c; sample_valid = 1;
                @(negedge clk); sample_valid = 0;
                timeout = 0;
                while (!y_valid && timeout < 1000) begin @(negedge clk); timeout = timeout + 1; end
                if (timeout >= 1000) begin
                    $display("tb_ladder: TIMEOUT -- no y_valid within 1000 clocks for sample %0d", i);
                    $fclose(fd); $finish;
                end
            end
        end
        repeat (2) @(posedge clk);
        $fclose(fd);
        $display("tb_ladder: %0d samples driven, %0d outputs, %0d mismatches, worst |error| %0d LSB",
                 n, nout, mism, maxerr);
        if (mism != 0)
            $display("tb_ladder: first mismatch at sample %0d: model %0d, RTL %0d",
                     first_i, first_exp, first_got);
        if (mism == 0 && nout == n * NCH) $display("tb_ladder: PASS (NCH=%0d, %0d channel-samples)", NCH, nout); else $display("tb_ladder: FAIL");
        $finish;
    end
endmodule
