`timescale 1ns/1ps
module tb_modal_rom;
    parameter PRESETS = 8; parameter MAXN = 1 << 17;
    localparam PSW = (PRESETS > 1) ? $clog2(PRESETS) : 1;
    reg clk = 0, rst_n = 0, sample_valid = 0; reg signed [15:0] exc = 0; reg [PSW-1:0] preset = 0;
    wire signed [15:0] y_out; wire y_valid;
    modal_dp_rom #(.PRESETS(PRESETS)) dut (.clk(clk), .rst_n(rst_n), .sample_valid(sample_valid), .exc(exc),
        .preset(preset), .y_out(y_out), .y_valid(y_valid));
    always #10 clk = ~clk;
    reg [39:0] vec [0:MAXN-1];   // {exc[15:0], preset[7:0], y[15:0]}
    reg [8*256-1:0] vecfile;
    integer n, i, nout, mism, first_i, maxerr, err, timeout; reg signed [15:0] expv;
    always @(posedge clk) if (rst_n && y_valid) begin
        expv = vec[nout][15:0];
        if (^y_out === 1'bx || y_out !== expv) begin if (mism == 0) first_i = nout; mism = mism + 1; end
        err = (^y_out === 1'bx) ? 65536 : (y_out > expv) ? y_out - expv : expv - y_out;
        if (err > maxerr) maxerr = err;
        nout = nout + 1;
    end
    initial begin
        if (!$value$plusargs("vec=%s", vecfile)) vecfile = "modal_rom_vectors_p8.hex";
        for (i = 0; i < MAXN; i = i + 1) vec[i] = {40{1'bx}};
        $readmemh(vecfile, vec);
        n = 0; while (n < MAXN && vec[n] !== {40{1'bx}}) n = n + 1;
        nout = 0; mism = 0; maxerr = 0; first_i = -1;
        repeat (4) @(posedge clk); rst_n = 1; repeat (2) @(posedge clk);
        for (i = 0; i < n; i = i + 1) begin
            @(negedge clk); exc = vec[i][39:24]; preset = vec[i][23:16]; sample_valid = 1;
            @(negedge clk); sample_valid = 0; timeout = 0;
            while (!y_valid && timeout < 1000) begin @(negedge clk); timeout = timeout + 1; end
            if (timeout >= 1000) begin $display("tb_modal_rom: TIMEOUT at sample %0d", i); $finish; end
        end
        repeat (2) @(posedge clk);
        $display("tb_modal_rom: PRESETS=%0d %0d samples driven, %0d outputs, %0d mismatches, worst |error| %0d LSB, first at %0d",
                 PRESETS, n, nout, mism, maxerr, first_i);
        if (mism == 0 && nout == n && n > 0) $display("tb_modal_rom: PASS"); else $display("tb_modal_rom: FAIL");
        $finish;
    end
endmodule
