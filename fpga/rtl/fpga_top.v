// fpga_top.v -- board wrapper around rtl-sketch/synth_top.v for an open FPGA flow.
//
// NOTHING HERE IS PART OF THE ASIC. This file exists so that the same RTL that
// ORFS synthesises for gf180mcu can be placed and routed by nextpnr, and so
// that the resource and Fmax numbers in fpga/reports/ are numbers for the real
// top level rather than for a block.
//
// What it adds, and why each is a wrapper concern and not a design change:
//   * a power-on reset counter, because a board may have no reset button and
//     synth_top's `rst_n_pad` is an asynchronous input the MCU drives on the chip;
//   * nothing else. The SPI and I2S pins go straight out.
//
// CLOCKING -- read this before quoting the sample rate.
// synth_top wants 12.288 MHz: 256 cycles per frame, LRCLK = clk/256 = 48 kHz
// exactly, BCLK = clk/4. It is the I2S MASTER, so the board clock SETS the
// sample rate and therefore the pitch; it is not slaved to a codec. A board
// that supplies 12.288 MHz gives exactly 48 kHz. Anything else scales
// everything by the same ratio (a 25 MHz ECP5 board driving its PLL to
// 12.2807 MHz is 47.97 kHz, 1.05 cents flat -- inaudible, but it is a
// deviation and it is recorded here rather than hidden).
// The iCE40 PLL cannot help at all: its output range starts at 16 MHz
// (`icepll -i 12 -o 12.288` refuses), so on iCE40 the board must carry a
// 12.288 MHz or 24.576 MHz oscillator.
`default_nettype none
module fpga_top #(
    parameter POR_BITS = 8      // hold reset for 2^POR_BITS clocks after configuration
)(
    input  wire clk,            // 12.288 MHz (see above)
    input  wire btn_rst_n,      // active-low; tie high if the board has no button
    input  wire sck,
    input  wire mosi,
    input  wire cs_n,
    output wire miso,
    output wire bclk,
    output wire lrclk,
    output wire sdata
);
    reg [POR_BITS-1:0] por = {POR_BITS{1'b0}};
    wire por_done = &por;
    always @(posedge clk) if (!por_done) por <= por + 1'b1;

    synth_top u_synth (
        .clk(clk), .rst_n_pad(btn_rst_n & por_done),
        .sck(sck), .mosi(mosi), .cs_n(cs_n), .miso(miso),
        .bclk(bclk), .lrclk(lrclk), .sdata(sdata));
endmodule
`default_nettype wire
