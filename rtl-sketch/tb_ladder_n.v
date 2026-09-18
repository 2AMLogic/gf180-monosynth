// tb_ladder_n.v -- bit-exact bench for ladder_dp_n (NCH channels) against
// model/fixed.py.
//
// VECTOR FORMAT: tb_ladder.v's 128-bit word (see there), but INTERLEAVED --
// one line per CHANNEL-SAMPLE, channel = line index mod NCH. Each line
// carries that channel's own x, g, k, gain, ogain and its own expected
// y_out, so every channel can be driven with a DIFFERENT stimulus stream.
//
// Why that matters: this bench used to read one line per sample and drive it
// to every channel in turn. All NCH channels then saw identical input every
// sample, so their states agreed by construction and STATE BLEEDING BETWEEN
// CHANNELS WAS UNDETECTABLE -- a channel that read another's delay line
// still produced the right number. verify_ladder.py --nch N --distinct
// generates N independent streams; --nch N alone still generates the old
// identical ones, and INJECT_BUG_LADDER_XTALK is the control that separates
// them (it passes the identical-stimulus run and fails the distinct one).
`timescale 1ns/1ps
module tb_ladder_n;
    parameter NCH      = 1;
    localparam CHW = (NCH > 1) ? $clog2(NCH) : 1;
    reg [CHW-1:0] ch = 0; wire [CHW-1:0] y_ch;
    parameter LOG2N    = 4;
    parameter ROM_FILE = "tanh16.hex";
    parameter OW       = 19;
    parameter MAXN     = 1 << 19;

    reg clk = 0, rst_n = 0, sample_valid = 0;
    reg signed [15:0] x_in = 0;
    reg        [15:0] g = 0;
    reg        [16:0] k = 0;
    reg        [19:0] gain = 0, ogain = 0;
    wire signed [OW-1:0] y_out;
    wire                 y_valid;

    ladder_dp_n #(.TANH_LOG2N(LOG2N), .ROM_FILE(ROM_FILE), .NCH(NCH), .OW(OW)) dut (
        .clk(clk), .rst_n(rst_n), .sample_valid(sample_valid), .ch(ch), .x_in(x_in),
        .g(g), .k(k), .gain(gain), .ogain(ogain), .y_out(y_out), .y_valid(y_valid), .y_ch(y_ch));

    always #10 clk = ~clk;

    reg [127:0] vec [0:MAXN-1];
    reg [8*512-1:0] vecfile, outfile;
    integer n, i, fd, nout, mism, chtag, first_i, first_exp, first_got, maxerr, err, timeout;
    reg signed [23:0] expv;

    // Every y_valid is one channel-sample: record it and score it.
    always @(posedge clk) if (rst_n && y_valid) begin
        expv = vec[nout][23:0];
        if (y_ch !== (nout % NCH)) chtag = chtag + 1;
        if (^y_out === 1'bx) $fdisplay(fd, "x"); else $fdisplay(fd, "%0d", y_out);
        if (^y_out === 1'bx || y_out !== expv) begin
            if (mism == 0) begin first_i = nout; first_exp = expv; first_got = y_out; end
            mism = mism + 1;
        end
        err = (^y_out === 1'bx) ? (1 << OW) : (y_out > expv) ? y_out - expv : expv - y_out;
        if (err > maxerr) maxerr = err;
        nout = nout + 1;
    end

    initial begin
        if (!$value$plusargs("vec=%s", vecfile)) vecfile = "build/ladder_vectors.hex";
        if (!$value$plusargs("out=%s", outfile)) outfile = "build/ladder_rtl_out.txt";
        for (i = 0; i < MAXN; i = i + 1) vec[i] = {128{1'bx}};
        $readmemh(vecfile, vec);
        n = 0; while (n < MAXN && vec[n] !== {128{1'bx}}) n = n + 1;
        fd = $fopen(outfile, "w");
        nout = 0; mism = 0; chtag = 0; maxerr = 0; first_i = -1; first_exp = 0; first_got = 0;
        repeat (4) @(posedge clk); rst_n = 1; repeat (2) @(posedge clk);
        for (i = 0; i < n; i = i + 1) begin                 // one line = one channel-sample
            @(negedge clk);
            x_in  = vec[i][127:112]; g = vec[i][111:96]; k = vec[i][95:72];
            gain  = vec[i][71:48];   ogain = vec[i][47:24];
            ch = i % NCH;
            sample_valid = 1;
            @(negedge clk); sample_valid = 0;
            timeout = 0;
            while (!y_valid && timeout < 1000) begin @(negedge clk); timeout = timeout + 1; end
            if (timeout >= 1000) begin
                $display("tb_ladder: TIMEOUT -- no y_valid within 1000 clocks for channel-sample %0d", i);
                $fclose(fd); $finish;
            end
        end
        repeat (2) @(posedge clk);
        $fclose(fd);
        $display("tb_ladder: %0d channel-samples driven, %0d outputs, %0d mismatches, %0d channel-tag errors, worst |error| %0d LSB",
                 n, nout, mism, chtag, maxerr);
        if (mism != 0)
            $display("tb_ladder: first mismatch at channel-sample %0d (ch %0d): model %0d, RTL %0d",
                     first_i, first_i % NCH, first_exp, first_got);
        if (mism == 0 && chtag == 0 && nout == n) $display("tb_ladder: PASS (NCH=%0d, %0d channel-samples)", NCH, nout);
        else $display("tb_ladder: FAIL");
        $finish;
    end
endmodule
