// tb_synth_top.v -- drives synth_top through its PINS: an SPI master (mode 0,
// 32-bit transactions, SCK = clk/8 = 1.536 MHz) sends the writes listed in
// +cmd=<file> (one per line: "wait_frames flag addr data", waiting that many
// frame ticks before the transaction starts), an I2S receiver decodes SDATA
// as a DAC does, and the bench measures the frame schedule:
//
//   * cycles from the tick to the voice's sample strobe (mean / worst) and to
//     the drum bus (drum_done), and that the datapath is idle at every tick;
//   * pin-to-acceptance latency of the link and the cycles the drain uses;
//   * that every decoded I2S word equals the sample strobed one LRCLK period
//     earlier (contract 13, D = 1), and that both channels carry it.
//
// +out=<file> receives one line per frame: frame, sample, decoded I2S word.
// This is a schedule and plumbing bench; bit-exactness is tb_voice.v's job.
`timescale 1ns/1ps
module tb_synth_top;
    reg clk = 0, rst_n = 0;
    reg sck = 0, mosi = 0, cs_n = 1;
    wire miso, bclk, lrclk, sdata;
    synth_top dut (.clk(clk), .rst_n_pad(rst_n), .sck(sck), .mosi(mosi), .cs_n(cs_n), .miso(miso),
                   .bclk(bclk), .lrclk(lrclk), .sdata(sdata));
    always #40.69 clk = ~clk;                                      // 12.288 MHz

    // ---- observation --------------------------------------------------------------------
    integer cyc_since_tick = 0, n_frames = 0;
    integer v_sum = 0, v_worst = 0, d_sum = 0, d_worst = 0, busy_at_tick = 0;
    integer lat_sum = 0, lat_n = 0, drain_first = -1, drain_last = -1;
    reg drum_seen = 0, drum_done_q = 0;
    reg signed [15:0] last_sample = 0;
    integer last_vcyc = -1, vcyc_prev = -1, vcyc_word = -1;
    integer out_fd = 0, frame_no = -1;
    reg [8*512-1:0] out_file;
    always @(posedge clk) begin
        if (dut.tick) begin
            if (n_frames > 0 && (dut.voice_busy || dut.drum_busy)) busy_at_tick = busy_at_tick + 1;
            cyc_since_tick = 0; n_frames = n_frames + 1; drum_seen = 0;
        end else cyc_since_tick = cyc_since_tick + 1;
        if (dut.sample_valid === 1'b1 && ^dut.sample !== 1'bx) begin
            v_sum = v_sum + cyc_since_tick; if (cyc_since_tick > v_worst) v_worst = cyc_since_tick;
            last_sample = dut.sample; last_vcyc = cyc_since_tick;
        end
        if (dut.drum_done && !drum_done_q) begin                    // rising edge: this frame's bus is ready
            d_sum = d_sum + cyc_since_tick; if (cyc_since_tick > d_worst) d_worst = cyc_since_tick;
        end
        drum_done_q = dut.drum_done;
        if (dut.wr_valid) begin
            if (drain_first < 0 || cyc_since_tick < drain_first) drain_first = cyc_since_tick;
            if (cyc_since_tick > drain_last) drain_last = cyc_since_tick;
        end
    end

    // ---- I2S receiver: sample SDATA on BCLK's rising edge, as a PCM5102A does ---------
    // In a 32-BCLK slot, rising edge 0 carries the delay bit, edges 1..16 the
    // 16 data bits MSB first, the rest zero.
    reg [15:0] cap = 0; integer nbit = 0;
    reg last_lr = 0;
    reg signed [15:0] left_word = 0, right_word = 0;
    reg signed [15:0] expect_word = 0, expect_prev = 0;
    integer i2s_words = 0, i2s_bad = 0, lr_bad = 0;
    always @(posedge bclk) begin
        if (lrclk != last_lr) begin                                 // new slot: the previous one is complete
            if (nbit == 32) begin
                if (last_lr == 0) left_word = cap;
                else begin
                    right_word = cap;
                    // the word of this LRCLK period must be the sample strobed in the previous frame
                    if (frame_no >= 2) begin                        // skip the period straddling reset
                    i2s_words = i2s_words + 1;
                    if (left_word !== expect_prev) i2s_bad = i2s_bad + 1;
                    if (right_word !== left_word) lr_bad = lr_bad + 1;
                    if (out_fd) $fdisplay(out_fd, "%0d %0d %0d %0d", frame_no - 1, expect_prev, left_word, vcyc_word);
                    end
                end
            end
            nbit = 0; cap = 0; last_lr = lrclk;
        end
        if (nbit >= 1 && nbit <= 16) cap = {cap[14:0], sdata};
        nbit = nbit + 1;
    end
    // the sample the DAC should see in period f+1 is the one strobed during frame f
    always @(posedge clk) if (dut.tick === 1'b1) begin
        expect_prev = expect_word; expect_word = last_sample; frame_no = frame_no + 1;
        vcyc_word = vcyc_prev; vcyc_prev = last_vcyc;
    end

    // ---- SPI master, mode 0, MSB first, SCK = clk/8 ------------------------------------
    reg [31:0] miso_word;
    task spi_write(input flag, input [6:0] addr, input [23:0] data);
        integer b; reg [31:0] word;
        begin
            word = {flag, addr, data};
            cs_n = 0; #200;
            for (b = 31; b >= 0; b = b - 1) begin
                mosi = word[b]; #325.5; sck = 1; miso_word[b] = miso; #325.5; sck = 0;
            end
            #200; cs_n = 1; #700;
        end
    endtask
    // acceptance latency: cycles from the CS_N rising edge at the pin to the queue push
    integer csn_rise_cycle = -1, cyc_abs = 0;
    always @(posedge clk) begin
        cyc_abs = cyc_abs + 1;
        if (dut.u_spi.accept && csn_rise_cycle >= 0) begin
            lat_sum = lat_sum + (cyc_abs - csn_rise_cycle); lat_n = lat_n + 1; csn_rise_cycle = -1;
        end
    end
    always @(posedge cs_n) csn_rise_cycle = cyc_abs;

    // ---- the script ------------------------------------------------------------------------
    integer cmd_fd, rc, wait_f, flag_i, addr_i, data_i, n_sent = 0, run_frames = 2000, ticks_seen = 0;
    reg [8*512-1:0] cmd_file;
    always @(posedge clk) if (dut.tick) ticks_seen = ticks_seen + 1;
    task wait_ticks(input integer n); integer t0; begin t0 = ticks_seen; wait (ticks_seen >= t0 + n); end endtask
    initial begin
        if ($value$plusargs("out=%s", out_file)) out_fd = $fopen(out_file, "w");
        if (!$value$plusargs("cmd=%s", cmd_file)) cmd_file = "build/top_cmds.txt";
        if ($value$plusargs("frames=%d", run_frames)) ;
        repeat (8) @(posedge clk); rst_n = 1;
        repeat (4) @(posedge clk);
        cmd_fd = $fopen(cmd_file, "r");
        if (cmd_fd == 0) begin $display("tb_synth_top: cannot open %0s", cmd_file); $finish; end
        while (!$feof(cmd_fd)) begin
            rc = $fscanf(cmd_fd, "%d %d %d %d\n", wait_f, flag_i, addr_i, data_i);
            if (rc == 4) begin
                if (wait_f > 0) wait_ticks(wait_f);
                spi_write(flag_i[0], addr_i[6:0], data_i[23:0]);
                n_sent = n_sent + 1;
                if (n_sent == 1) $display("tb_synth_top: status word on MISO = %08x (ID %02x ver %0x flags %0x frame %0d)",
                                          miso_word, miso_word[31:24], miso_word[23:20], miso_word[19:16], miso_word[15:0]);
            end
        end
        $fclose(cmd_fd);
        wait_ticks(run_frames);
        $display("tb_synth_top: %0d writes sent over SPI, %0d frames observed", n_sent, n_frames);
        $display("tb_synth_top: link pin->acceptance %0d cycles (mean over %0d), drain applied writes in cycles %0d..%0d",
                 lat_n ? lat_sum / lat_n : -1, lat_n, drain_first, drain_last);
        $display("tb_synth_top: voice sample ready at cycle mean %0d worst %0d of 256; drum bus ready at mean %0d worst %0d",
                 v_sum / (n_frames - 1), v_worst, d_sum / (n_frames - 1), d_worst);
        $display("tb_synth_top: datapath busy at a tick: %0d times (must be 0); overrun flag %0d; overflow %0d",
                 busy_at_tick, dut.overrun, dut.u_spi.overflow);
        $display("tb_synth_top: I2S words decoded %0d, mismatches against the sample stream (D = 1) %0d, L/R differ %0d",
                 i2s_words, i2s_bad, lr_bad);
        $display("tb_synth_top: last sample %0d", last_sample);
        if (out_fd) $fclose(out_fd);
        $finish;
    end
endmodule
