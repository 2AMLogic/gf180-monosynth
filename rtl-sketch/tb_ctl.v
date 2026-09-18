// tb_ctl.v -- the CONTROL PATH bench: can the host express, over the pins, the
// register writes the two models need?
//
// Every other bench in this repository drives the register WRITE PORT directly
// (tb_voice.v, tb_drums.v) or checks the link's schedule (tb_synth_top.v).
// None of them asks whether a write the model performs can be carried by the
// frame the link defines. It could not: DR 0007 revision 1's 32-bit frame has
// a 7-bit address and a 24-bit datum, and contract 15.1's drum image is an
// 8-bit address space with 27-bit values. This bench is the test that sees it.
//
// It drives SCK / MOSI / CS_N as an MCU's SPI master does, transaction by
// transaction, and records what comes out of the register write port. The
// comparison is against the (flag, sec, addr, data) the host INTENDED, not
// against anything the DUT produced, so a truncation is a mismatch and not a
// self-consistent pass.
//
//   +writes=<file>  one 64-bit hex word per line, in order:
//                     [63:48] wait_frames   [47:44] flag   [43:40] sec
//                     [39:32] addr          [31:0]  data
//   +out=<file>     one line per write SEEN at the port: "flag sec addr data cyc"
//                   where cyc is the cycle-since-tick it was applied in
//   +bits=32|48     how the MASTER packs the word. 32 is DR 0007 revision 1:
//                   {F, A[6:0], D[23:0]} -- all the host can send on that link.
//                   48 is revision 2: {F, 6'b0, SEC, A[7:0], D[31:0]}.
//   +frames=N       run at least this many frames after the last write
//
// Also checked here, because they are properties of the frame and not of the
// register map: a transaction with the wrong bit count is DISCARDED (DR 0007
// section 1), and the status word reads back its constant ID and version.
`timescale 1ns/1ps
module tb_ctl;
    parameter GO_CYCLE = 8;
    reg clk = 0, rst_n = 0;
    reg sck = 0, mosi = 0, cs_n = 1;
    wire miso;

    // ---- the frame the chip runs on (synth_top's, so the drain is the real one) ----
    reg [7:0]  cyc = 0;
    reg [15:0] frame = 0;
    wire tick = (cyc == 8'd0);
    always @(posedge clk) if (rst_n) begin
        cyc <= cyc + 8'd1;
        if (tick) frame <= frame + 16'd1;
    end

    wire        wr_valid, wr_flag, wr_sec;
    wire [7:0]  wr_addr;
    wire [31:0] wr_data;
    wire        fresh, overflow;
    wire [2:0]  q_count;
    spi_ctl dut (.clk(clk), .rst_n(rst_n), .sck(sck), .mosi(mosi), .cs_n(cs_n), .miso(miso),
                 .tick(tick), .frame(frame), .overrun(1'b0),
                 .wr_valid(wr_valid), .wr_flag(wr_flag), .wr_sec(wr_sec),
                 .wr_addr(wr_addr), .wr_data(wr_data),
                 .fresh(fresh), .overflow(overflow), .q_count(q_count));
    always #40.69 clk = ~clk;                              // 12.288 MHz

    // ---- record every write that reaches the port ---------------------------------
    integer fd = 0, nseen = 0, drain_first = 999, drain_last = -1, late = 0, cycn = 0;
    reg arm = 0;                                           // set once the priming NOP is past
    always @(posedge clk) if (rst_n && wr_valid && arm) begin
        cycn = cyc;
        nseen = nseen + 1;
        if (cycn < drain_first) drain_first = cycn;
        if (cycn > drain_last)  drain_last  = cycn;
        if (cycn >= GO_CYCLE) late = late + 1;             // applied after `go`: too late for this frame
        if (fd) $fdisplay(fd, "%0d %0d %0d %0d %0d", wr_flag, wr_sec, wr_addr, wr_data, cycn);
    end

    // ---- SPI master, mode 0, MSB first, SCK = clk/8 = 1.536 MHz --------------------
    reg [47:0] shifted;
    reg [31:0] miso_word;
    integer   fbits;
    task spi_xfer(input integer nbits, input [47:0] word);
        integer b;
        begin
            cs_n = 0; #200;
            for (b = nbits - 1; b >= 0; b = b - 1) begin
                mosi = word[b]; #325.5; sck = 1;
                // the status word is 32 bits shifted out from the FIRST SCK edge,
                // whatever the frame width: index from the start of the transaction
                if (nbits - 1 - b < 32) miso_word[31 - (nbits - 1 - b)] = miso;
                #325.5; sck = 0;
            end
            #200; cs_n = 1; #700;
        end
    endtask
    task send(input flag, input sec, input [7:0] addr, input [31:0] data);
        begin
            if (fbits == 48) spi_xfer(48, {flag, 6'b0, sec, addr, data});
            else             spi_xfer(32, {16'b0, flag, addr[6:0], data[23:0]});
        end
    endtask

    // ---- the script ---------------------------------------------------------------
    parameter MAXW = 1 << 12;
    reg [63:0] wr [0:MAXW-1];
    reg [8*256-1:0] wfile, outfile;
    integer nw, wi, run_frames, ticks = 0, t0, i;
    always @(posedge clk) if (rst_n && tick) ticks = ticks + 1;
    task wait_ticks(input integer n); begin t0 = ticks; wait (ticks >= t0 + n); end endtask

    initial begin
        if (!$value$plusargs("writes=%s", wfile))  wfile = "build/ctl_writes.hex";
        if (!$value$plusargs("out=%s", outfile))   outfile = "build/ctl_rtl_out.txt";
        if (!$value$plusargs("bits=%d", fbits))    fbits = 48;
        if (!$value$plusargs("frames=%d", run_frames)) run_frames = 8;
        for (i = 0; i < MAXW; i = i + 1) wr[i] = {64{1'bx}};
        $readmemh(wfile, wr);
        nw = 0; while (nw < MAXW && wr[nw] !== {64{1'bx}}) nw = nw + 1;
        fd = $fopen(outfile, "w");
        repeat (8) @(posedge clk); rst_n = 1; repeat (4) @(posedge clk);

        // the status word on the first transaction after reset: ID 'M', version, fresh = 1
        send(0, 0, 8'h3F, 32'd0);                          // NOP, voice page
        $display("tb_ctl: status word on MISO = %08x (ID %02x ver %0x flags %0x frame %0d)",
                 miso_word, miso_word[31:24], miso_word[23:20], miso_word[19:16], miso_word[15:0]);
        if (miso_word[31:24] !== 8'h4D) $display("tb_ctl: STATUS ID WRONG (expected 4D)");
        if (miso_word[19:16] !== 4'b0001) $display("tb_ctl: STATUS FLAGS WRONG (expected fresh only)");
        wait_ticks(2); arm = 1;                            // from here on, every write is scripted

        for (wi = 0; wi < nw; wi = wi + 1) begin
            if (wr[wi][63:48] != 0) wait_ticks(wr[wi][63:48]);
            send(wr[wi][44], wr[wi][40], wr[wi][39:32], wr[wi][31:0]);
        end
        wait_ticks(run_frames);

        // a short and a long transaction must both be DISCARDED (DR 0007 section 1)
        i = nseen;
        spi_xfer(fbits - 1, 48'h5555_5555_5555);
        spi_xfer(fbits > 40 ? 40 : 24, 48'hAAAA_AAAA_AAAA);
        wait_ticks(4);
        $display("tb_ctl: writes accepted from two mis-sized transactions: %0d (must be 0)", nseen - i);

        $fclose(fd);
        $display("tb_ctl: %0d transactions sent at %0d bits, %0d writes reached the port, drain cycles %0d..%0d, after go: %0d",
                 nw, fbits, nseen, drain_first, drain_last, late);
        $display("tb_ctl: fresh %0d overflow %0d q_count %0d", fresh, overflow, q_count);
        $finish;
    end
endmodule
