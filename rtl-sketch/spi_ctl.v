// spi_ctl.v -- the control link of DR 0007: an SPI slave (mode 0, 48-bit
// transactions framed by CS_N), a four-deep write queue, the status word on
// MISO, and the drain that applies queued writes one per cycle at the start
// of each frame.
//
// STATUS: REAL RTL, written to DR 0007 revision 2. Exercised END TO END by
// rtl-sketch/verify_ctl.py / tb_ctl.v, which sends the two models' own
// register images through the pins and compares what reaches the write port
// against what the host INTENDED; and through the pins by tb_synth_top.v,
// which measures pin-to-acceptance latency and the drain cycles.
//
// THE FRAME IS 48 BITS, not revision 1's 32 (DR 0007 revision 2, section 2):
//
//   bits 47:40   CTL  = {F, 6'b0, SEC}
//   bits 39:32   A[7:0]
//   bits 31:0    D[31:0]
//
// SEC = 0 is the voice and master page (DR 0007 section 3); SEC = 1 is the
// drum section's page, whose map is contract 15.1's, unchanged. Revision 1's
// 32-bit frame could carry only 37 of the 155 writes the two models perform:
// 118 drum writes had no page to go to, 67 addresses did not fit in 7 bits
// (A_PATH = 0x80, A_MODE = 0xC0, A_RESET = 0xFF) and 26 values did not fit in
// 24 (ENV_CTL is 27 bits, MODE_A1 / MODE_A2 26). Measured, not argued:
// `verify_ctl.py --link dr7rev1` reproduces it, and stubs/spi_ctl_dr7rev1.v
// is that receiver kept as the standing negative control.
//
// Timing rule (contract 4.3, DR 0007 section 5):
//   * everything is sampled in the core clock domain through two-flop
//     synchronisers; SCK edges are detected on the synchronised signal, so
//     SCK must be <= f_core / 4 (guaranteed <= 2 MHz in the record);
//   * a transaction is ACCEPTED in the cycle the synchronised CS_N rising
//     edge is registered with exactly 48 bits clocked in; anything else is
//     discarded;
//   * at `tick` the queue occupancy is snapshotted and that many writes are
//     popped in the following cycles, one per cycle, oldest first. A write
//     accepted in the tick cycle or later belongs to the new frame.
//   * the queue cannot overflow at the specified SCK (a 48-bit transaction
//     plus its CS_N gap is >= 24.3 us at 2 MHz, longer than the 20.83 us
//     frame, so at most ONE write completes per frame against a depth of
//     four); if it does, the write is dropped and `overflow` is set (sticky,
//     reported in the status word and cleared when the word is loaded).
//
// Status word, MSB first: {8'h4D, 4'h2, overrun, queue_nonempty, overflow,
// fresh, frame[15:0]}, loaded at the falling edge of CS_N. VERSION is 2: it
// names this record's register map, and the map changed.
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
    output reg         wr_sec,        // 0 the voice and master page, 1 the drum section's
    output reg  [7:0]  wr_addr,
    output reg  [31:0] wr_data,
    // for the status word / debug
    output reg         fresh,         // no write accepted since reset
    output reg         overflow,      // sticky: a write was dropped
    output wire [2:0]  q_count
);
    localparam FW = 48;               // frame width, DR 0007 revision 2 section 2

    // ---- synchronisers and edge detectors ---------------------------------
    reg [1:0] sck_q, mosi_q, csn_q;
    reg       sck_p, csn_p;
    wire sck_s  = sck_q[1], mosi_s = mosi_q[1], csn_s = csn_q[1];
    wire sck_rise = sck_s & ~sck_p;
    wire sck_fall = ~sck_s & sck_p;
    wire csn_fall = ~csn_s & csn_p;
    wire csn_rise = csn_s & ~csn_p;

    // ---- shift registers and bit count ------------------------------------
    reg [FW-1:0] sr;                  // MOSI in
    reg [31:0]   osr;                 // MISO out (status word)
    reg [6:0]    bitcnt;              // saturates at 127

    // ---- the queue: 4 x FW ---------------------------------------------------
    reg [FW-1:0] q [0:3];
    reg [2:0]  wp, rp;
    reg [2:0]  drain;                 // writes still to pop this frame
    assign q_count = wp - rp;
`ifdef INJECT_BUG_SPI_ANYLEN
    wire accept = csn_rise && (bitcnt != 7'd0);          // NEGATIVE CONTROL: a mis-sized
`else                                                    //   transaction is applied, not discarded
    wire accept = csn_rise && (bitcnt == FW);
`endif
    wire push   = accept && (q_count != 3'd4);
    wire pop    = (drain != 3'd0) && (q_count != 3'd0);

    wire [31:0] status = {8'h4D, 4'h2, overrun, (q_count != 3'd0), overflow, fresh, frame};

    // ---- the word's fields (section 2) -------------------------------------
    wire [FW-1:0] head = q[rp[1:0]];
    wire          f_flag = head[47];
    wire          f_sec  = head[40];
    wire [7:0]    f_addr = head[39:32];
    wire [31:0]   f_data = head[31:0];

`ifdef INJECT_BUG_SPI_DRAIN_LATE
    reg [3:0] tw;                                        // NEGATIVE CONTROL: hold the drain off
    wire tick_win = (tw != 4'd0);                        //   until cycle 8, where `go` is
    always @(posedge clk) if (!rst_n) tw <= 4'd0; else if (tick) tw <= 4'd8; else if (tw != 4'd0) tw <= tw - 4'd1;
`endif

    integer i;
    always @(posedge clk) begin
        if (!rst_n) begin
            sck_q <= 2'b00; mosi_q <= 2'b00; csn_q <= 2'b11; sck_p <= 1'b0; csn_p <= 1'b1;
            sr <= {FW{1'b0}}; osr <= 32'd0; bitcnt <= 7'd0; miso <= 1'b0;
            wp <= 3'd0; rp <= 3'd0; drain <= 3'd0;
            wr_valid <= 1'b0; wr_flag <= 1'b0; wr_sec <= 1'b0; wr_addr <= 8'd0; wr_data <= 32'd0;
            fresh <= 1'b1; overflow <= 1'b0;
            for (i = 0; i < 4; i = i + 1) q[i] <= {FW{1'b0}};
        end else begin
            sck_q <= {sck_q[0], sck}; mosi_q <= {mosi_q[0], mosi}; csn_q <= {csn_q[0], cs_n};
            sck_p <= sck_s; csn_p <= csn_s;

            // ---- the link ----
            if (csn_fall) begin                              // start of a transaction
                bitcnt <= 7'd0;
                osr    <= {status[30:0], 1'b0};
                miso   <= status[31];
                overflow <= 1'b0;                            // reported once, then cleared
            end else if (!csn_s) begin
                if (sck_rise) begin
                    sr <= {sr[FW-2:0], mosi_s};
                    if (bitcnt != 7'd127) bitcnt <= bitcnt + 7'd1;
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
            if (tick) drain <= q_count;                      // writes accepted before this cycle
`ifdef INJECT_BUG_SPI_DRAIN_LATE
            else if (pop && !tick_win) begin                 // NEGATIVE CONTROL: the drain runs
`else                                                        //   from cycle 8, i.e. at `go`
            else if (pop) begin
`endif
                drain    <= drain - 3'd1;
                rp       <= rp + 3'd1;
                wr_valid <= 1'b1;
                wr_flag  <= f_flag;
`ifdef INJECT_BUG_SPI_NOSEC
                wr_sec   <= 1'b0;                            // NEGATIVE CONTROL: no page bit --
`else                                                        //   drum writes land on the voice
                wr_sec   <= f_sec;
`endif
`ifdef INJECT_BUG_SPI_ADDR7
                wr_addr  <= {1'b0, f_addr[6:0]};             // NEGATIVE CONTROL: revision 1's
`else                                                        //   7-bit address field
                wr_addr  <= f_addr;
`endif
`ifdef INJECT_BUG_SPI_DATA24
                wr_data  <= {8'b0, f_data[23:0]};            // NEGATIVE CONTROL: revision 1's
`else                                                        //   24-bit data field
                wr_data  <= f_data;
`endif
            end
        end
    end
endmodule
`default_nettype wire
