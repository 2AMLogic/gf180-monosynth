// drum_regs.v -- the drum section's control image (contract 15.1) as RTL.
//
// This is the piece that was missing between the link and the drum engine.
// `drum_kit.v` takes its whole control image as flat buses and holds no
// registers of its own; until now the only thing that drove those buses was
// the bench (tb_drums.v's `apply` task), so the engine could be shown
// bit-exact against model/drums_fx.py and still not be reachable from a pin.
// This module is that bench task as hardware, addressed by DR 0007
// revision 2's drum page (SEC = 1).
//
//   0x00      STOPS            8
//   0x10 + s  ACCENT[s]       16 u     s = 0..7
//   0x20 + i  OSC_INC[i]      24 u     i = 0..5
//   0x40 + 4e ENV_CTL[e]      27       e = 0..ENVS-1   <- 27 bits: the register that
//   0x41 + 4e ENV_PEAK[e]     24 u                        does not fit a 24-bit datum
//   0x42 + 4e ENV_RATE[e]     16 u
//   0x80 + p  PATH[p]         22       p = 0..PATHS-1
//   0xC0 + 4m MODE_A1[m]      26 s     m = 0..MODES-1  <- 26 bits, likewise
//   0xC1 + 4m MODE_A2[m]      26 s
//   0xC2 + 4m MODE_AMP[m]     16 u
//   0xC3 + 4m MODE_NUM[m]      2
//   0xFF      RESET           --       every register and state of 15.8
//
// An address that names no register is ignored (15.1). `soft_rst` is
// combinational from the write port, exactly as the voice's RESET is at the
// top: it gates rst_n for this module AND for drum_kit, so one write clears
// the control image and the engine's state together, which is what
// DrumsFx.write(A_RESET) does in the model.
//
// Every register resets to 0 (15.8) and the section is silent until
// programmed, so a chip that is never told about drums makes none.
`default_nettype none
module drum_regs #(
    parameter ENVS  = 12,
    parameter PATHS = 16,
    parameter MODES = 12
)(
    input  wire        clk,
    input  wire        rst_n,
    // the drum page of the register write port (already gated on SEC = 1)
    input  wire        wr_valid,
    input  wire [7:0]  wr_addr,
    input  wire [31:0] wr_data,
    output wire        soft_rst,                 // address 0xFF, combinational
    // the control image, as drum_kit.v wants it
    output reg  [7:0]              stops,
    output wire [8*16-1:0]         accent_bus,
    output wire [6*24-1:0]         osc_inc_bus,
    output wire [ENVS*27-1:0]      env_ctl_bus,
    output wire [ENVS*24-1:0]      env_peak_bus,
    output wire [ENVS*16-1:0]      env_rate_bus,
    output wire [PATHS*22-1:0]     path_bus,
    output wire [MODES*26-1:0]     a1_bus,
    output wire [MODES*26-1:0]     a2_bus,
    output wire [MODES*16-1:0]     amp_bus,
    output wire [MODES*2-1:0]      num_bus
);
    assign soft_rst = wr_valid && (wr_addr == 8'hFF);

    reg [15:0] accent [0:7];
    reg [23:0] osc    [0:5];
    reg [26:0] ectl   [0:ENVS-1];
    reg [23:0] peak   [0:ENVS-1];
    reg [15:0] rate   [0:ENVS-1];
    reg [21:0] path   [0:PATHS-1];
    reg [25:0] a1     [0:MODES-1];
    reg [25:0] a2     [0:MODES-1];
    reg [15:0] amp    [0:MODES-1];
    reg [1:0]  num    [0:MODES-1];

    genvar gi;
    generate
        for (gi = 0; gi < 8; gi = gi + 1)     assign accent_bus[gi*16 +: 16]  = accent[gi];
        for (gi = 0; gi < 6; gi = gi + 1)     assign osc_inc_bus[gi*24 +: 24] = osc[gi];
        for (gi = 0; gi < ENVS; gi = gi + 1)  begin : g_env
            assign env_ctl_bus[gi*27 +: 27]  = ectl[gi];
            assign env_peak_bus[gi*24 +: 24] = peak[gi];
            assign env_rate_bus[gi*16 +: 16] = rate[gi];
        end
        for (gi = 0; gi < PATHS; gi = gi + 1) assign path_bus[gi*22 +: 22] = path[gi];
        for (gi = 0; gi < MODES; gi = gi + 1) begin : g_mode
            assign a1_bus[gi*26 +: 26]  = a1[gi];
            assign a2_bus[gi*26 +: 26]  = a2[gi];
            assign amp_bus[gi*16 +: 16] = amp[gi];
            assign num_bus[gi*2 +: 2]   = num[gi];
        end
    endgenerate

    wire [7:0] e_idx = (wr_addr - 8'h40) >> 2;
    wire [7:0] m_idx = (wr_addr - 8'hC0) >> 2;
    wire [1:0] fld   = wr_addr[1:0];

    integer i;
    always @(posedge clk) begin
        if (!rst_n) begin
            stops <= 8'd0;
            for (i = 0; i < 8; i = i + 1)     accent[i] <= 16'd0;
            for (i = 0; i < 6; i = i + 1)     osc[i]    <= 24'd0;
            for (i = 0; i < ENVS; i = i + 1)  begin ectl[i] <= 27'd0; peak[i] <= 24'd0; rate[i] <= 16'd0; end
            for (i = 0; i < PATHS; i = i + 1) path[i] <= 22'd0;
            for (i = 0; i < MODES; i = i + 1) begin a1[i] <= 26'd0; a2[i] <= 26'd0; amp[i] <= 16'd0; num[i] <= 2'd0; end
        end else if (wr_valid) begin
            if (wr_addr == 8'h00)                                        stops <= wr_data[7:0];
            else if (wr_addr >= 8'h10 && wr_addr < 8'h18)                accent[wr_addr[2:0]] <= wr_data[15:0];
            else if (wr_addr >= 8'h20 && wr_addr < 8'h26)                osc[wr_addr[2:0]]    <= wr_data[23:0];
            else if (wr_addr >= 8'h40 && wr_addr < 8'h40 + ENVS * 4) begin
                if      (fld == 2'd0) ectl[e_idx] <= wr_data[26:0];      // 27 bits
                else if (fld == 2'd1) peak[e_idx] <= wr_data[23:0];
                else if (fld == 2'd2) rate[e_idx] <= wr_data[15:0];
            end
            else if (wr_addr >= 8'h80 && wr_addr < 8'h80 + PATHS)        path[wr_addr[3:0]] <= wr_data[21:0];
            else if (wr_addr >= 8'hC0 && wr_addr < 8'hC0 + MODES * 4) begin
                if      (fld == 2'd0) a1[m_idx]  <= wr_data[25:0];       // 26 bits
                else if (fld == 2'd1) a2[m_idx]  <= wr_data[25:0];
                else if (fld == 2'd2) amp[m_idx] <= wr_data[15:0];
                else                  num[m_idx] <= wr_data[1:0];
            end
            // any other address: no register, the write is ignored (15.1)
        end
    end
endmodule
`default_nettype wire
