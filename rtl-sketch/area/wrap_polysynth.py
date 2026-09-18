#!/usr/bin/env python3
"""Textually wrap the sibling gf180-polysynth core so its parser, command FIFO,
mixer, the two ROM includes and the two multipliers become named submodules --
no logic change -- so `synth_area.py` (no flatten) can report each one.
docs/area-budget.md section 1 is measured on this copy.

  wrap_polysynth.py <gf180-polysynth>/rtl <out-dir>

Written for the sibling at its commit of 2026-09-17 (synth_core.v / synth_voice.v
as in NUMERIC-CONTRACT rev 1); every replacement asserts it matched, so a
changed upstream fails loudly rather than measuring something else.
"""
import os, sys
src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
def rep(s, old, new):
    assert s.count(old) == 1, f'pattern not found exactly once:\n{old[:120]}'
    return s.replace(old, new)
for f in ('uart_rx.v', 'note_inc_rom.vh', 'sine_q_rom.vh'):
    open(os.path.join(out, f), 'w').write(open(os.path.join(src, f)).read())

v = open(os.path.join(src, 'synth_voice.v')).read()
v = rep(v, '    `include "sine_q_rom.vh"\n', '    wire [15:0] sine_q_val;\n    sine_q_rom u_sine (.sine_q_idx(sine_q_idx), .val(sine_q_val));\n')
v = rep(v, '    `include "note_inc_rom.vh"\n', '    wire [23:0] note_inc_val;\n    note_inc_rom u_note (.note_inc_idx(note_inc_idx), .val(note_inc_val));\n')
v = rep(v, "    wire        [22:0] envvel = s1_env * s1_vel;                 // u16*u7 = u23; g = [22:7]\n    wire        [32:0] prod   = $signed(s2_osc) * $signed({1'b0, s2_g}); // s16*u16 -> s33; out = [31:16]\n",
           "    wire        [22:0] envvel; mul_u16u7  u_mul_env (.a(s1_env), .b(s1_vel), .p(envvel));\n    wire        [32:0] prod;   mul_s16u16 u_mul_out (.a(s2_osc), .b(s2_g), .p(prod));\n")
v += '''
module sine_q_rom (input wire [8:0] sine_q_idx, output wire [15:0] val);
    `include "sine_q_rom.vh"
    assign val = sine_q_val;
endmodule
module note_inc_rom (input wire [6:0] note_inc_idx, output wire [23:0] val);
    `include "note_inc_rom.vh"
    assign val = note_inc_val;
endmodule
module mul_u16u7 (input wire [15:0] a, input wire [6:0] b, output wire [22:0] p);
    assign p = a * b;
endmodule
module mul_s16u16 (input wire [15:0] a, input wire [15:0] b, output wire [32:0] p);
    assign p = $signed(a) * $signed({1'b0, b});
endmodule
'''
open(os.path.join(out, 'synth_voice.v'), 'w').write(v)

c = open(os.path.join(src, 'synth_core.v')).read()
c = rep(c, '''    wire [17:0] mix = {{2{vo[0][15]}}, vo[0]} + {{2{vo[1][15]}}, vo[1]}
                    + {{2{vo[2][15]}}, vo[2]} + {{2{vo[3][15]}}, vo[3]};
    wire [15:0] mix_sat = ($signed(mix) > 18'sd32767)  ? 16'h7FFF :
                          ($signed(mix) < -18'sd32768) ? 16'h8000 : mix[15:0];
''', '''    wire [15:0] mix_sat;
    mixer4 u_mixer (.v0(vo[0]), .v1(vo[1]), .v2(vo[2]), .v3(vo[3]), .mix_sat(mix_sat));
''')
c = rep(c, '''    reg [34:0] q_mem [0:7];
    reg [2:0]  q_wr, q_rd;
    reg [3:0]  q_cnt;
    wire       q_empty = (q_cnt == 4'd0);
    wire       q_full  = q_cnt[3];
    wire       q_push  = cmd_push & ~q_full;
    wire       q_pop   = ~q_empty & ~tick;
    wire [34:0] q_head = q_mem[q_rd];

    always @(posedge clk) begin
        if (!rst_n) begin
            q_wr <= 3'd0; q_rd <= 3'd0; q_cnt <= 4'd0; dbg_fifo_overflow <= 1'b0;
        end else begin
            if (q_push) begin
                q_mem[q_wr] <= {c_op, c_voice, c_s0, c_s1, c_s2, c_s3};
                q_wr <= q_wr + 3'd1;
            end
            if (q_pop) q_rd <= q_rd + 3'd1;
            case ({q_push, q_pop})
                2'b10:   q_cnt <= q_cnt + 4'd1;
                2'b01:   q_cnt <= q_cnt - 4'd1;
                default: ;
            endcase
            if (cmd_push & q_full) dbg_fifo_overflow <= 1'b1;
        end
    end
''', '''    wire        q_empty, q_full, q_pop;
    wire [34:0] q_head;
    cmd_fifo8 u_fifo (.clk(clk), .rst_n(rst_n), .push(cmd_push), .din({c_op, c_voice, c_s0, c_s1, c_s2, c_s3}),
                      .tick(tick), .pop(q_pop), .head(q_head), .empty(q_empty), .full(q_full));
    always @(posedge clk) if (!rst_n) dbg_fifo_overflow <= 1'b0; else if (cmd_push & q_full) dbg_fifo_overflow <= 1'b1;
''')
start = c.index('    // ---- byte parser (contract 10.2 - 10.4)')
end = c.index('    // ---- command FIFO (depth 8)')
parser_body = c[start:end]
c = c[:start] + '''    // ---- byte parser (contract 10.2 - 10.4), as a submodule ----------------------
    wire        cmd_push;
    wire [4:0]  c_op;  wire [1:0] c_voice;  wire [6:0] c_s0, c_s1, c_s2, c_s3;
    byte_parser u_parser (.clk(clk), .rst_n(rst_n), .byte_valid(byte_valid), .byte_in(byte_in),
        .cmd_push(cmd_push), .c_op(c_op), .c_voice(c_voice), .c_s0(c_s0), .c_s1(c_s1), .c_s2(c_s2), .c_s3(c_s3));

''' + c[end:]
c += '''
module byte_parser (
    input  wire       clk, input wire rst_n, input wire byte_valid, input wire [7:0] byte_in,
    output wire       cmd_push, output wire [4:0] c_op, output wire [1:0] c_voice,
    output wire [6:0] c_s0, c_s1, c_s2, c_s3);
''' + parser_body + '''endmodule

module cmd_fifo8 (
    input wire clk, input wire rst_n, input wire push, input wire [34:0] din, input wire tick,
    output wire pop, output wire [34:0] head, output wire empty, output wire full);
    reg [34:0] q_mem [0:7];
    reg [2:0]  q_wr, q_rd;
    reg [3:0]  q_cnt;
    assign empty = (q_cnt == 4'd0);
    assign full  = q_cnt[3];
    wire   q_push = push & ~full;
    assign pop    = ~empty & ~tick;
    assign head   = q_mem[q_rd];
    always @(posedge clk) begin
        if (!rst_n) begin
            q_wr <= 3'd0; q_rd <= 3'd0; q_cnt <= 4'd0;
        end else begin
            if (q_push) begin q_mem[q_wr] <= din; q_wr <= q_wr + 3'd1; end
            if (pop) q_rd <= q_rd + 3'd1;
            case ({q_push, pop})
                2'b10:   q_cnt <= q_cnt + 4'd1;
                2'b01:   q_cnt <= q_cnt - 4'd1;
                default: ;
            endcase
        end
    end
endmodule

module mixer4 (input wire [15:0] v0, v1, v2, v3, output wire [15:0] mix_sat);
    wire [17:0] mix = {{2{v0[15]}}, v0} + {{2{v1[15]}}, v1} + {{2{v2[15]}}, v2} + {{2{v3[15]}}, v3};
    assign mix_sat = ($signed(mix) > 18'sd32767)  ? 16'h7FFF :
                     ($signed(mix) < -18'sd32768) ? 16'h8000 : mix[15:0];
endmodule
'''
open(os.path.join(out, 'synth_core.v'), 'w').write(c)
print('wrapped into', out)
