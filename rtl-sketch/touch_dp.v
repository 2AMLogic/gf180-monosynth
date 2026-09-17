// touch_dp.v -- AREA SKETCH. Capacitive touch, all-digital: no ADC, no
// comparator, no analog design at all.
//
// Drive the pad high, release it to high-Z, and count clocks until the input
// buffer reads low as it discharges through a bleed resistor. A finger adds
// maybe 5-20 pF to a ~10 pF pad, so the count rises measurably. This is the
// CapSense trick, and it needs exactly one bidirectional pad and a counter per
// pad -- which is why it is the cheap route to "an instrument you hit".
//
// Velocity falls out for free: the RATE OF CHANGE of the count across scans is
// how fast the finger is approaching, so a hard hit and a slow press differ
// without any extra hardware.
`default_nettype none
module touch_dp #(
    parameter PADS = 8,
    parameter CW   = 12          // counter width
)(
    input  wire             clk,
    input  wire             rst_n,
    input  wire [PADS-1:0]  pad_in,      // from the pad's input buffer
    output reg  [PADS-1:0]  pad_drive,   // 1 = drive high, 0 = high-Z
    output reg  [PADS-1:0]  pad_oe,
    output reg  [CW-1:0]    level,       // current pad's count
    output reg  [CW-1:0]    velocity,    // |count - previous count|
    output reg  [2:0]       pad_sel,
    output reg              sample_valid
);
    localparam CHARGE = 12'd64;
    reg [CW-1:0] cnt, prev [0:PADS-1];
    reg [1:0] state;
    localparam S_CHARGE=2'd0, S_MEASURE=2'd1, S_REPORT=2'd2, S_NEXT=2'd3;

    integer i;
    always @(posedge clk) begin
        if (!rst_n) begin
            state<=S_CHARGE; cnt<=0; pad_sel<=0; pad_drive<=0; pad_oe<=0;
            sample_valid<=0; level<=0; velocity<=0;
            for (i=0;i<PADS;i=i+1) prev[i]<=0;
        end else begin
            sample_valid <= 1'b0;
            case (state)
                S_CHARGE: begin
                    pad_oe    <= (1 << pad_sel);
                    pad_drive <= (1 << pad_sel);
                    cnt <= cnt + 1'b1;
                    if (cnt >= CHARGE) begin cnt<=0; state<=S_MEASURE; end
                end
                S_MEASURE: begin
                    pad_oe <= {PADS{1'b0}};          // release to high-Z
                    if (pad_in[pad_sel] && cnt != {CW{1'b1}})
                        cnt <= cnt + 1'b1;
                    else
                        state <= S_REPORT;
                end
                S_REPORT: begin
                    level    <= cnt;
                    velocity <= (cnt > prev[pad_sel]) ? (cnt - prev[pad_sel])
                                                      : (prev[pad_sel] - cnt);
                    prev[pad_sel] <= cnt;
                    sample_valid  <= 1'b1;
                    state <= S_NEXT;
                end
                default: begin
                    pad_sel <= pad_sel + 1'b1;
                    cnt <= 0; state <= S_CHARGE;
                end
            endcase
        end
    end
endmodule
`default_nettype wire
