// tb_voice.v -- bit-exact bench for voice_dp against model/voice_fx.py, at
// the register port of contract 16.2 (the physical layer bypassed, so the
// bench decides exactly which frame every write lands in).
//
// verify_voice.py writes two files: +wr=<writes>, one "frame flag addr data"
// line per write in application order, and +exp=<samples>, one int16 per
// frame, the model's output. The bench runs its own 256-cycle frames: the
// writes of frame f are applied one per cycle from cycle 1, `go` is pulsed
// at cycle GO (after the last write), and the sample strobed during the frame
// is compared with the model's, no tolerance. The drum bus is silent and
// always "done", so the master mix is the contract's sat16((v * vol) >> 15).
// Taps (mixed, ae, fe, cut, k_eff, y19) go to +tap= for debugging.
`timescale 1ns/1ps
module tb_voice;
    parameter GO   = 100;             // writes occupy cycles 1..GO-2; the datapath has 256-GO cycles (measured worst ~90)
    parameter MAXW = 1 << 16;
    parameter MAXN = 1 << 17;

    reg clk = 0, rst_n = 0;
    reg go = 0, wr_valid = 0, wr_flag = 0;
    reg [6:0]  wr_addr = 0;
    reg [23:0] wr_data = 0;
    wire signed [15:0] sample;
    wire sample_valid, busy;
    wire signed [15:0] mixed; wire [14:0] ae, fe, cut; wire [16:0] k_eff; wire signed [18:0] y19;
    voice_dp dut (.clk(clk), .rst_n(rst_n), .go(go),
                  .wr_valid(wr_valid), .wr_flag(wr_flag), .wr_addr(wr_addr), .wr_data(wr_data),
                  .drum_bus(19'sd0), .drum_done(1'b1),
                  .sample(sample), .sample_valid(sample_valid), .busy(busy),
                  .mixed(mixed), .ae(ae), .fe(fe), .cut(cut), .k_eff(k_eff), .y19(y19));
    always #10 clk = ~clk;

    reg [1023:0] wrfile, expfile, outfile, tapfile;
    integer wfd, efd, ofd, tfd, rc, nw, nexp, i, f, frame, cyc, wi, nout, mism, first_f, first_exp, first_got, maxerr, err;
    integer wr_f [0:MAXW-1]; integer wr_fl [0:MAXW-1]; integer wr_a [0:MAXW-1]; integer wr_d [0:MAXW-1];
    integer expv [0:MAXN-1];
    reg signed [15:0] got; reg got_valid;

    initial begin
        if (!$value$plusargs("wr=%s", wrfile)) wrfile = "build/voice_writes.txt";
        if (!$value$plusargs("exp=%s", expfile)) expfile = "build/voice_expected.txt";
        if (!$value$plusargs("out=%s", outfile)) outfile = "build/voice_rtl_out.txt";
        tfd = 0; if ($value$plusargs("tap=%s", tapfile)) tfd = $fopen(tapfile, "w");
        wfd = $fopen(wrfile, "r"); nw = 0;
        while (!$feof(wfd) && nw < MAXW) begin
            rc = $fscanf(wfd, "%d %d %d %d\n", wr_f[nw], wr_fl[nw], wr_a[nw], wr_d[nw]);
            if (rc == 4) nw = nw + 1;
        end
        $fclose(wfd);
        efd = $fopen(expfile, "r"); nexp = 0;
        while (!$feof(efd) && nexp < MAXN) begin
            rc = $fscanf(efd, "%d\n", expv[nexp]);
            if (rc == 1) nexp = nexp + 1;
        end
        $fclose(efd);
        ofd = $fopen(outfile, "w");
        nout = 0; mism = 0; maxerr = 0; first_f = -1; first_exp = 0; first_got = 0; wi = 0;
        repeat (4) @(posedge clk); rst_n = 1; repeat (2) @(posedge clk);
        for (frame = 0; frame < nexp; frame = frame + 1) begin
            got_valid = 0;
            for (cyc = 0; cyc < 256; cyc = cyc + 1) begin
                @(negedge clk);
                wr_valid = 0; go = 0;
                if (cyc >= 1 && cyc < GO - 1 && wi < nw && wr_f[wi] == frame) begin
                    wr_valid = 1; wr_flag = wr_fl[wi]; wr_addr = wr_a[wi]; wr_data = wr_d[wi]; wi = wi + 1;
                end
                if (cyc == GO) go = 1;
                if (cyc == GO + 1 && wi < nw && wr_f[wi] == frame) begin
                    $display("tb_voice: frame %0d has more writes than cycles 1..%0d", frame, GO - 2); $finish;
                end
                @(posedge clk); #1;
                if (sample_valid) begin got = sample; got_valid = 1; end
            end
            if (busy) begin $display("tb_voice: datapath still busy at the end of frame %0d", frame); $finish; end
            if (!got_valid) begin $display("tb_voice: no sample in frame %0d", frame); $finish; end
            $fdisplay(ofd, "%0d", got);
            if (tfd) $fdisplay(tfd, "%0d %0d %0d %0d %0d %0d %0d", frame, mixed, ae, fe, cut, k_eff, y19);
            if (got !== expv[frame]) begin
                if (mism == 0) begin first_f = frame; first_exp = expv[frame]; first_got = got; end
                mism = mism + 1;
            end
            err = (got > expv[frame]) ? got - expv[frame] : expv[frame] - got;
            if (err > maxerr) maxerr = err;
            nout = nout + 1;
        end
        $fclose(ofd); if (tfd) $fclose(tfd);
        $display("tb_voice: %0d writes, %0d frames, %0d mismatches, worst |error| %0d LSB", nw, nout, mism, maxerr);
        if (mism != 0) $display("tb_voice: first mismatch at frame %0d: model %0d, RTL %0d", first_f, first_exp, first_got);
        if (mism == 0 && nout == nexp) $display("tb_voice: PASS"); else $display("tb_voice: FAIL");
        $finish;
    end
endmodule
