// tb_top_bx.v -- synth_top.v through its PINS, logged for a bit-exact
// comparison against model/synth_top_model.py.
//
// tb_synth_top.v measures the schedule and checks the I2S stream against the
// DUT'S OWN sample stream. That check is circular: a bit shift or a channel
// swap in i2s_tx changes both sides of the comparison and it still passes --
// and a channel swap is exactly what shipped broken in the sibling's trial 1.
// This bench does not compare anything. It LOGS what the pins and the taps
// did, and verify_synth_top.py compares every line against the model:
//
//   SMP  f off sample mixed ae fe cut k_eff y19 drum_bus d19 out_v out_d
//        one line per sample_valid. `sample` is the chip's output word.
//   I2S  f slot nbits word
//        one line per completed LRCLK slot, DECODED FROM SDATA the way a
//        PCM5102A does. slot 0 = left (LRCLK low), 1 = right.
//   CSN  f off flag addr data
//        the frame and cycle at which CS_N was first seen HIGH at the pin.
//        The link's rule (DR 0007 section 5) turns this into the frame the
//        write lands in; the model uses that and WR checks the chip agrees.
//   WR   f off flag addr data          every write the register port applied.
//   END  frames busy_at_tick overrun overflow xsample
//
// The SPI master is CLOCK-DRIVEN, SCK = clk/(2*SCKH), so a transaction takes
// exactly 68*SCKH core cycles from the CS_N fall to the CS_N rise and a
// command can place its landing edge at any cycle of any frame -- including
// the last three, where the write belongs to the frame after next.
`timescale 1ns/1ps
module tb_top_bx;
    parameter SCKH_DEF = 4;                    // SCK half-period in core cycles (clk/8 = 1.536 MHz)
    reg clk = 0, rst_n = 0;
    reg sck = 0, mosi = 0, cs_n = 1;
    wire miso, bclk, lrclk, sdata;
    synth_top dut (.clk(clk), .rst_n_pad(rst_n), .sck(sck), .mosi(mosi), .cs_n(cs_n), .miso(miso),
                   .bclk(bclk), .lrclk(lrclk), .sdata(sdata));
    always #40.69 clk = ~clk;                  // 12.288 MHz

    integer lfd = 0, fidx = -1, foff = 0, busy_at_tick = 0, xsample = 0, nsmp = 0;
    reg [8*512-1:0] logfile, cmdfile;
    integer sckh = SCKH_DEF;
    reg cs_n_q = 1;
    integer pend_flag = 0, pend_addr = 0, pend_data = 0;
    integer lat_flag = 0, lat_addr = 0, lat_data = 0;

    // ---- the frame index and the cycle within it ---------------------------------
    // dut.cyc is the DUT's own counter; foff tracks it so that foff == dut.cyc
    // and fidx counts ticks from the first one after reset.
    always @(posedge clk) begin
        // dut.cyc is HELD at 0 through reset, so dut.tick is true on every one
        // of those cycles: the frame counter must not start until the DUT's
        // synchronised reset is released.
        if (!dut.rst_n) begin fidx = -1; foff = 0; end
        else if (dut.tick) begin fidx = fidx + 1; foff = 0; end
        else foff = foff + 1;
        if (fidx >= 1) begin
            if (dut.tick && (dut.voice_busy || dut.drum_busy)) busy_at_tick = busy_at_tick + 1;
            // ---- the register port ----
            if (dut.wr_valid === 1'b1)
                $fdisplay(lfd, "WR %0d %0d %0d %0d %0d", fidx, foff, dut.wr_flag, dut.wr_addr, dut.wr_data);
            // ---- the sample and the taps ----
            if (dut.sample_valid === 1'b1) begin
                nsmp = nsmp + 1;
                if (^dut.sample === 1'bx) begin
                    xsample = xsample + 1;
                    $fdisplay(lfd, "SMP %0d %0d x x x x x x x x x x x", fidx, foff);
                end else
                    $fdisplay(lfd, "SMP %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d",
                              fidx, foff, $signed(dut.sample), $signed(dut.u_voice.mixed),
                              dut.u_voice.ae, dut.u_voice.fe, dut.u_voice.cut, dut.u_voice.k_eff,
                              $signed(dut.u_voice.y19), $signed(dut.drum_bus), $signed(dut.u_voice.d19),
                              $signed(dut.u_voice.out_v), $signed(dut.u_voice.out_d));
            end
            // ---- the CS_N rising edge at the pin ----
            if (cs_n === 1'b1 && cs_n_q === 1'b0)
                $fdisplay(lfd, "CSN %0d %0d %0d %0d %0d", fidx, foff, lat_flag, lat_addr, lat_data);
        end
        if (cs_n === 1'b0 && cs_n_q === 1'b1) begin     // latch at the FALL: the script can
            lat_flag = pend_flag;                       // start the next transaction before the
            lat_addr = pend_addr;                       // posedge that observes this rise
            lat_data = pend_data;
        end
        cs_n_q <= cs_n;
    end

    // ---- I2S receiver: sample SDATA on BCLK's rising edge, as a DAC does ----------
    // 32 BCLK per slot: rising edge 0 carries the delay bit, 1..16 the 16 data
    // bits MSB first, the rest zero. Nothing here looks at dut.sample.
    reg [15:0] cap = 0; integer nbit = 0;
    reg last_lr = 0;
    always @(posedge bclk) begin
        if (lrclk !== last_lr) begin                       // slot boundary: the previous slot is done
            // A slot is detected at the first BCLK edge AFTER it ends: the left
            // slot of period f ends at cycle 130 of frame f, the right slot at
            // cycle 2 of frame f+1. Tag both with the period they belong to.
            if (fidx >= 1) $fdisplay(lfd, "I2S %0d %0d %0d %0d", last_lr ? fidx - 1 : fidx,
                                     last_lr, nbit, $signed(cap));
            nbit = 0; cap = 0; last_lr = lrclk;
        end
        if (nbit >= 1 && nbit <= 16) cap = {cap[14:0], sdata};
        nbit = nbit + 1;
    end

    // ---- the clock-driven SPI master, mode 0, MSB first ---------------------------
    task spi_xfer(input flag, input [6:0] addr, input [23:0] data);
        integer b;
        reg [31:0] word;
        begin
            word = {flag, addr, data};
            pend_flag = flag; pend_addr = addr; pend_data = data;
            @(negedge clk); cs_n = 1'b0;
            repeat (2 * sckh) @(negedge clk);
            for (b = 31; b >= 0; b = b - 1) begin
                mosi = word[b];
                repeat (sckh) @(negedge clk);
                sck = 1'b1;
                repeat (sckh) @(negedge clk);
                sck = 1'b0;
            end
            repeat (2 * sckh) @(negedge clk);
            cs_n = 1'b1;
        end
    endtask

    // ---- the script --------------------------------------------------------------
    integer cmd_fd, rc, w_frame, w_off, flag_i, addr_i, data_i, n_sent = 0, run_frames = 1200;
    task wait_until(input integer wf, input integer wo);
        begin
            while (fidx < wf) @(posedge clk);
            while (!(fidx == wf && foff == wo) && fidx <= wf) @(posedge clk);
        end
    endtask
    initial begin
        if (!$value$plusargs("log=%s", logfile)) logfile = "build/top_bx_log.txt";
        if (!$value$plusargs("cmd=%s", cmdfile)) cmdfile = "build/top_bx_cmds.txt";
        if ($value$plusargs("frames=%d", run_frames)) ;
        if ($value$plusargs("sckh=%d", sckh)) ;
        lfd = $fopen(logfile, "w");
        repeat (8) @(posedge clk); rst_n = 1;
        cmd_fd = $fopen(cmdfile, "r");
        if (cmd_fd == 0) begin $display("tb_top_bx: cannot open %0s", cmdfile); $finish; end
        while (!$feof(cmd_fd)) begin
            rc = $fscanf(cmd_fd, "%d %d %d %d %d\n", w_frame, w_off, flag_i, addr_i, data_i);
            if (rc == 5) begin
                wait_until(w_frame, w_off);
                spi_xfer(flag_i[0], addr_i[6:0], data_i[23:0]);
                n_sent = n_sent + 1;
            end
        end
        $fclose(cmd_fd);
        while (fidx < run_frames) @(posedge clk);
        $fdisplay(lfd, "END %0d %0d %0d %0d %0d %0d", fidx, n_sent, busy_at_tick,
                  dut.overrun, dut.u_spi.overflow, xsample);
        $display("tb_top_bx: %0d frames, %0d writes sent, %0d samples, busy-at-tick %0d, overrun %0d, overflow %0d, X samples %0d",
                 fidx, n_sent, nsmp, busy_at_tick, dut.overrun, dut.u_spi.overflow, xsample);
        $fclose(lfd);
        $finish;
    end
endmodule
