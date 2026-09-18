// spi_ctl.v -- the control link of DR 0007: an SPI slave (mode 0, 32-bit
// transactions framed by CS_N), a four-deep write queue, the status word on
// MISO, and the drain that applies queued writes one per cycle at the start
// of each frame.
//
// STATUS: REAL RTL, written to DR 0007. Exercised by tb_synth_top.v through
// the pins (pin-to-acceptance latency and the drain cycles are measured
// there). Not yet compared against a model of the link -- there is none; the
// contract's obligation on the link is only 4.3, which is the drain below.
//
// Timing rule (contract 4.3, DR 0007 section 5):
//   * everything is sampled in the core clock domain through two-flop
//     synchronisers; SCK edges are detected on the synchronised signal, so
//     SCK must be <= f_core / 4 (guaranteed <= 2 MHz in the record);
//   * a transaction is ACCEPTED in the cycle the synchronised CS_N rising
//     edge is registered with exactly 32 bits clocked in; anything else is
//     discarded;
//   * at `tick` the queue occupancy is snapshotted and that many writes are
//     popped in the following cycles, one per cycle, oldest first. A write
//     accepted in the tick cycle or later belongs to the new frame.
//   * the queue cannot overflow at the specified SCK (at most two writes can
//     complete per 256-cycle frame); if it does, the write is dropped and
//     `overflow` is set (sticky, reported in the status word and cleared when
//     the word is loaded).
//
// Status word, MSB first: {8'h4D, 4'h1, overrun, queue_nonempty, overflow,
// fresh, frame[15:0]}, loaded at the falling edge of CS_N.
`default_nettype none
module spi_ctl (
    input  wire        clk,
    input  wire        rst_n,
    // pins
    input  wire        sck,
    input  wire        mosi,
    input  wire        cs_n,
    output reg         miso,
    // frame timing
    input  wire        tick,          // cycle 0 of a frame
    input  wire [15:0] frame,         // frame counter, for the status word
    input  wire        overrun,       // scheduler's sticky flag, for the status word
    // the register write port of contract 16.2: one write per cycle, drained at the tick
    output reg         wr_valid,
    output reg         wr_flag,
    output reg  [6:0]  wr_addr,
    output reg  [23:0] wr_data,
    // for the status word / debug
    output reg         fresh,         // no write accepted since reset
    output reg         overflow,      // sticky: a write was dropped
    output wire [2:0]  q_count
);
    // ---- synchronisers and edge detectors ---------------------------------
    reg [1:0] sck_q, mosi_q, csn_q;
    reg       sck_p, csn_p;
    wire sck_s  = sck_q[1], mosi_s = mosi_q[1], csn_s = csn_q[1];
    wire sck_rise = sck_s & ~sck_p;
    wire sck_fall = ~sck_s & sck_p;
    wire csn_fall = ~csn_s & csn_p;
    wire csn_rise = csn_s & ~csn_p;

    // ---- shift registers and bit count ------------------------------------
    reg [31:0] sr;                    // MOSI in
    reg [31:0] osr;                   // MISO out (status word)
    reg [5:0]  bitcnt;                // saturates at 63

    // ---- the queue: 4 x 32 ---------------------------------------------------
    reg [31:0] q [0:3];
    reg [2:0]  wp, rp;
    reg [2:0]  drain;                 // writes still to pop this frame
    assign q_count = wp - rp;
    wire accept = csn_rise && (bitcnt == 6'd32);
    wire push   = accept && (q_count != 3'd4);
    wire pop    = (drain != 3'd0) && (q_count != 3'd0);

    wire [31:0] status = {8'h4D, 4'h1, overrun, (q_count != 3'd0), overflow, fresh, frame};

    integer i;
    always @(posedge clk) begin
        if (!rst_n) begin
            sck_q <= 2'b00; mosi_q <= 2'b00; csn_q <= 2'b11; sck_p <= 1'b0; csn_p <= 1'b1;
            sr <= 32'd0; osr <= 32'd0; bitcnt <= 6'd0; miso <= 1'b0;
            wp <= 3'd0; rp <= 3'd0; drain <= 3'd0;
            wr_valid <= 1'b0; wr_flag <= 1'b0; wr_addr <= 7'd0; wr_data <= 24'd0;
            fresh <= 1'b1; overflow <= 1'b0;
            for (i = 0; i < 4; i = i + 1) q[i] <= 32'd0;
        end else begin
            sck_q <= {sck_q[0], sck}; mosi_q <= {mosi_q[0], mosi}; csn_q <= {csn_q[0], cs_n};
            sck_p <= sck_s; csn_p <= csn_s;

            // ---- the link ----
            if (csn_fall) begin                              // start of a transaction
                bitcnt <= 6'd0;
                osr    <= {status[30:0], 1'b0};
                miso   <= status[31];
                overflow <= 1'b0;                            // reported once, then cleared
            end else if (!csn_s) begin
                if (sck_rise) begin
                    sr <= {sr[30:0], mosi_s};
                    if (bitcnt != 6'd63) bitcnt <= bitcnt + 6'd1;
                end
                if (sck_fall) begin
                    miso <= osr[31];
                    osr  <= {osr[30:0], 1'b0};
                end
            end
            if (accept) begin
                fresh <= 1'b0;
                if (q_count != 3'd4) begin q[wp[1:0]] <= sr; wp <= wp + 3'd1; end
                else overflow <= 1'b1;
            end

            // ---- the drain: snapshot at the tick, pop one per cycle ----
            wr_valid <= 1'b0;
`ifdef INJECT_BUG_TOP_SPI_TICK_RACE
            // NEGATIVE CONTROL: the snapshot counts the write being accepted in
            // the tick cycle itself, so a transaction whose CS_N edge lands in
            // the last cycles of a frame is applied a frame EARLY. The queue
            // pointer has not moved yet, so the drain also pops a stale word.
            if (tick) drain <= q_count + (accept ? 3'd1 : 3'd0);
`else
            if (tick) drain <= q_count;                      // writes accepted before this cycle
`endif
            else if (pop) begin
                drain    <= drain - 3'd1;
                rp       <= rp + 3'd1;
                wr_valid <= 1'b1;
                wr_flag  <= q[rp[1:0]][31];
                wr_addr  <= q[rp[1:0]][30:24];
                wr_data  <= q[rp[1:0]][23:0];
            end
        end
    end
endmodule
`default_nettype wire
