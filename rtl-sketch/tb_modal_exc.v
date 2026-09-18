// tb_modal_exc.v -- the excitation-hold hazard of ARCHITECTURE.md 4.4, as a
// bench that can fail.
//
// modal_dp / modal_dp_rom take 15 cycles for a four-mode pass and the strike
// is added once per MODE, three cycles apart. tb_modal.v, tb_modal_fx.v and
// tb_modal_rom.v all hold `exc` constant for the whole pass by construction,
// so if the module read `exc` combinationally instead of latching it, every
// one of them would still pass. This bench drives a DIFFERENT value on `exc`
// partway through the pass and requires the output to be the one the model
// computes for the value present when `sample_valid` was accepted -- the
// contract ARCHITECTURE.md 4.4 states.
//
//   +vec=<file>   one line per sample, 16 hex digits:
//                 exc_at_sv(4) exc_after(4) preset(2) spare(2) expected_y(4)
//   +delay=<n>    cycles after sample_valid at which exc changes to exc_after
//   +out=<file>   one y_out per line
//
// A "hold" run writes exc_after == exc_at_sv and must pass against any
// implementation; a "change" run writes a different value and passes only if
// the excitation is registered at the start of the pass.
`timescale 1ns/1ps
module tb_modal_exc;
    parameter PRESETS = 8;
    parameter MAXN    = 1 << 14;
    reg clk = 0, rst_n = 0, sample_valid = 0;
    reg signed [15:0] exc = 0;
    reg [2:0] preset = 0;
    wire signed [15:0] y_out;
    wire y_valid;

    modal_dp_rom #(.PRESETS(PRESETS)) dut (.clk(clk), .rst_n(rst_n), .sample_valid(sample_valid),
                                           .exc(exc), .preset(preset), .y_out(y_out), .y_valid(y_valid));
    always #10 clk = ~clk;

    reg [63:0] vec [0:MAXN-1];
    reg [8*512-1:0] vecfile, outfile;
    integer n, i, c, fd, nout, mism, first_i, first_exp, first_got, maxerr, err, timeout, delay, xs;
    reg signed [15:0] expv;

    initial begin
        if (!$value$plusargs("vec=%s", vecfile)) vecfile = "build/modal_exc_vectors.hex";
        if (!$value$plusargs("out=%s", outfile)) outfile = "build/modal_exc_rtl_out.txt";
        if (!$value$plusargs("delay=%d", delay)) delay = 4;
        for (i = 0; i < MAXN; i = i + 1) vec[i] = {64{1'bx}};
        $readmemh(vecfile, vec);
        n = 0; while (n < MAXN && vec[n] !== {64{1'bx}}) n = n + 1;
        fd = $fopen(outfile, "w");
        nout = 0; mism = 0; maxerr = 0; xs = 0; first_i = -1; first_exp = 0; first_got = 0;
        repeat (4) @(posedge clk); rst_n = 1; repeat (2) @(posedge clk);
        for (i = 0; i < n; i = i + 1) begin
            @(negedge clk);
            exc = vec[i][63:48]; preset = vec[i][26:24];
            sample_valid = 1;
            @(negedge clk); sample_valid = 0;
            // hold until `delay` cycles after sample_valid, then present the
            // other value for the rest of the pass
            timeout = 0; c = 1;
            while (!y_valid && timeout < 100) begin
                if (c == delay - 1) exc = vec[i][47:32];
                @(negedge clk); timeout = timeout + 1; c = c + 1;
            end
            if (timeout >= 100) begin
                $display("tb_modal_exc: TIMEOUT -- no y_valid for sample %0d", i);
                $fclose(fd); $finish;
            end
            expv = vec[i][15:0];
            if (^y_out === 1'bx) begin $fdisplay(fd, "x"); xs = xs + 1; end
            else $fdisplay(fd, "%0d", y_out);
            if (^y_out === 1'bx || y_out !== expv) begin
                if (mism == 0) begin first_i = i; first_exp = expv; first_got = y_out; end
                mism = mism + 1;
            end
            err = (^y_out === 1'bx) ? 65536 : (y_out > expv) ? y_out - expv : expv - y_out;
            if (err > maxerr) maxerr = err;
            nout = nout + 1;
        end
        $fclose(fd);
        $display("tb_modal_exc: %0d samples, exc changed %0d cycles after sample_valid, %0d mismatches, worst |error| %0d LSB (%0d X)",
                 n, delay, mism, maxerr, xs);
        if (mism != 0)
            $display("tb_modal_exc: first mismatch at sample %0d: model %0d, RTL %0d", first_i, first_exp, first_got);
        if (mism == 0 && nout == n) $display("tb_modal_exc: PASS"); else $display("tb_modal_exc: FAIL");
        $finish;
    end
endmodule
