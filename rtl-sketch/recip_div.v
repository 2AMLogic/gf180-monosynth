// recip_div.v -- the PolyBLEP reciprocal of contract 6.6.1, sequentially.
//
//   e = bit_length(inc) - 16;  m = inc >> e (or << -e), 16 bits in [2^15, 2^16)
//   r = min( floor(2^31 / m), 65535 )
//
// Exposed as `sh` = e + 15 (0..23), the amount by which {x, 15'b0} is shifted
// right to form both m (from inc) and p (from x) in 6.6.2, so no signed
// exponent is stored. inc = 0 returns (sh, r) = (15, 0), the contract's
// (e, r) = (0, 0); no division is performed.
//
// Restoring division: the dividend 2^31 has one set bit, so after its top
// fifteen bits the partial remainder is 2^14 and no quotient bit is set
// (2^14 < m); the remaining 17 quotient bits take 17 iterations with the
// remainder doubled each time. q = 2^16 (inc a power of two, m = 2^15) is the
// one case the clamp catches. 19 cycles from start to done, fixed.
//
// STATUS: REAL RTL, written to the contract; checked against voice_fx.recip_of
// by tb_recip.v over every NOTE_INC entry and the edge cases (not yet the
// full 24-bit range).
`default_nettype none
module recip_div (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    input  wire [23:0] inc,
    output reg         done,          // one cycle, with sh and r valid
    output reg  [4:0]  sh,
    output reg  [15:0] r
);
    // bit length of inc: position of the highest set bit + 1 (0 for inc = 0)
    function [4:0] bitlen(input [23:0] v);
        integer j;
        begin
            bitlen = 5'd0;
            for (j = 0; j < 24; j = j + 1) if (v[j]) bitlen = j + 1;
        end
    endfunction
    wire [4:0]  bl   = bitlen(inc);
    wire [4:0]  sh_n = bl - 5'd1;                              // e + 15
    wire [38:0] nrm  = {inc, 15'b0} >> sh_n;
    wire [15:0] m_n  = nrm[15:0];

    reg [15:0] m;
    reg [17:0] rem;
    reg [16:0] quo;
    reg [4:0]  cnt;
    reg        busy;
    wire [17:0] rem2 = {rem[16:0], 1'b0};
    wire        ge   = rem2 >= {2'b00, m};

    always @(posedge clk) begin
        if (!rst_n) begin
            done <= 1'b0; sh <= 5'd15; r <= 16'd0; m <= 16'd0; rem <= 18'd0; quo <= 17'd0; cnt <= 5'd0; busy <= 1'b0;
        end else begin
            done <= 1'b0;
            if (start && !busy) begin
                if (inc == 24'd0) begin
                    sh <= 5'd15; r <= 16'd0; done <= 1'b1;
                end else begin
                    sh <= sh_n; m <= m_n; rem <= 18'd16384; quo <= 17'd0; cnt <= 5'd17; busy <= 1'b1;
                end
            end else if (busy) begin
                rem <= ge ? (rem2 - {2'b00, m}) : rem2;
                quo <= {quo[15:0], ge};
                cnt <= cnt - 5'd1;
                if (cnt == 5'd1) begin                         // the 17th quotient bit
                    busy <= 1'b0;
                    done <= 1'b1;
                    r <= ({quo[15:0], ge} == 17'h10000) ? 16'hFFFF : {quo[14:0], ge};
                end
            end
        end
    end
endmodule
`default_nettype wire
