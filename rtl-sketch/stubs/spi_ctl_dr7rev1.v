// spi_ctl_dr7rev1.v -- THE STANDING NEGATIVE CONTROL for the control frame
// format: the receiver exactly as DR 0007 revision 1 specified it (a 32-bit
// transaction, {F, A[6:0], D[23:0]}), wearing revision 2's port shape so the
// same bench can drive both.
//
// This is not dead code and it is not a stub with no behaviour: it is the
// shipped receiver, kept so `verify_ctl.py --link dr7rev1` can be run at any
// time and produce the measured failure that motivated revision 2 --
// 59 of the reference kit's 100 register writes corrupted, 58 by address
// truncation (A_PATH = 0x80, A_MODE = 0xC0, A_RESET = 0xFF all alias into
// 0x00-0x7F) and 21 by data truncation (ENV_CTL is 27 bits, MODE_A1/A2 26,
// against a 24-bit D).
//
// The host cannot do better than this on a 32-bit frame: it packs the low 7
// address bits and the low 24 data bits, which is what `pack32` in the bench
// does. `wr_sec` is tied to 0 because revision 1 has no section bit.
`default_nettype none
module spi_ctl (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        sck,
    input  wire        mosi,
    input  wire        cs_n,
    output reg         miso,
    input  wire        tick,
    input  wire [15:0] frame,
    input  wire        overrun,
    output reg         wr_valid,
    output reg         wr_flag,
    output wire        wr_sec,
    output reg  [7:0]  wr_addr,
    output reg  [31:0] wr_data,
    output reg         fresh,
    output reg         overflow,
    output wire [2:0]  q_count
);
    localparam FW = 32;                        // revision 1's frame width
    assign wr_sec = 1'b0;                      // revision 1 has no section bit

    reg [1:0] sck_q, mosi_q, csn_q;
    reg       sck_p, csn_p;
    wire sck_s  = sck_q[1], mosi_s = mosi_q[1], csn_s = csn_q[1];
    wire sck_rise = sck_s & ~sck_p;
    wire sck_fall = ~sck_s & sck_p;
    wire csn_fall = ~csn_s & csn_p;
    wire csn_rise = csn_s & ~csn_p;

    reg [FW-1:0] sr;
    reg [31:0]   osr;
    reg [6:0]    bitcnt;

    reg [FW-1:0] q [0:3];
    reg [2:0]  wp, rp;
    reg [2:0]  drain;
    assign q_count = wp - rp;
    wire accept = csn_rise && (bitcnt == FW);
    wire push   = accept && (q_count != 3'd4);
    wire pop    = (drain != 3'd0) && (q_count != 3'd0);

    wire [31:0] status = {8'h4D, 4'h1, overrun, (q_count != 3'd0), overflow, fresh, frame};

    integer i;
    always @(posedge clk) begin
        if (!rst_n) begin
            sck_q <= 2'b00; mosi_q <= 2'b00; csn_q <= 2'b11; sck_p <= 1'b0; csn_p <= 1'b1;
            sr <= 0; osr <= 32'd0; bitcnt <= 7'd0; miso <= 1'b0;
            wp <= 3'd0; rp <= 3'd0; drain <= 3'd0;
            wr_valid <= 1'b0; wr_flag <= 1'b0; wr_addr <= 8'd0; wr_data <= 32'd0;
            fresh <= 1'b1; overflow <= 1'b0;
            for (i = 0; i < 4; i = i + 1) q[i] <= 0;
        end else begin
            sck_q <= {sck_q[0], sck}; mosi_q <= {mosi_q[0], mosi}; csn_q <= {csn_q[0], cs_n};
            sck_p <= sck_s; csn_p <= csn_s;
            if (csn_fall) begin
                bitcnt <= 7'd0;
                osr    <= {status[30:0], 1'b0};
                miso   <= status[31];
                overflow <= 1'b0;
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
            wr_valid <= 1'b0;
            if (tick) drain <= q_count;
            else if (pop) begin
                drain    <= drain - 3'd1;
                rp       <= rp + 3'd1;
                wr_valid <= 1'b1;
                wr_flag  <= q[rp[1:0]][31];
                wr_addr  <= {1'b0, q[rp[1:0]][30:24]};
                wr_data  <= {8'b0, q[rp[1:0]][23:0]};
            end
        end
    end
endmodule
`default_nettype wire
