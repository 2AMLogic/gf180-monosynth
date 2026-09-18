// 7-track copy of OpenROAD-flow-scripts platforms/gf180/cells_adders.v (26Q3-296-gda37dce1c), with
// gf180mcu_fd_sc_mcu9t5v0 -> gf180mcu_fd_sc_mcu7t5v0. The stock ORFS gf180 platform hard-codes the 9t
// cell names in its techmap files, so TRACK_OPTION=7t produces undriven adder outputs (yosys 'check
// -assert' fails with hundreds of 'is used but has no driver'). Selected via ADDER_MAP_FILE / LATCH_MAP_FILE.

(* techmap_celltype = "$fa" *)
module _tech_fa (A, B, C, X, Y);
  parameter WIDTH = 1;
  (* force_downto *)
    input [WIDTH-1 : 0] A, B, C;
  (* force_downto *)
    output [WIDTH-1 : 0] X, Y;
  
  parameter _TECHMAP_CONSTVAL_A_ = WIDTH'bx;
  parameter _TECHMAP_CONSTVAL_B_ = WIDTH'bx;
  parameter _TECHMAP_CONSTVAL_C_ = WIDTH'bx;
  
  genvar i;
  generate for (i = 0; i < WIDTH; i = i + 1) begin
      if (_TECHMAP_CONSTVAL_A_[i] === 1'b0 || _TECHMAP_CONSTVAL_B_[i] === 1'b0 || _TECHMAP_CONSTVAL_C_[i] === 1'b0) begin
        if (_TECHMAP_CONSTVAL_C_[i] === 1'b0) begin
          gf180mcu_fd_sc_mcu7t5v0__addh_1 halfadder_Cconst (
              .A(A[i]),
              .B(B[i]),
              .CO(X[i]), .S(Y[i])
            );
        end 
        else begin
          if (_TECHMAP_CONSTVAL_B_[i] === 1'b0) begin
            gf180mcu_fd_sc_mcu7t5v0__addh_1 halfadder_Bconst (
                .A(A[i]),
                .B(C[i]),
                .CO(X[i]), .S(Y[i])
              );
          end
          else begin
            gf180mcu_fd_sc_mcu7t5v0__addh_1 halfadder_Aconst (
                .A(B[i]),
                .B(C[i]),
                .CO(X[i]), .S(Y[i])
              );
          end
        end
      end
      else begin
        gf180mcu_fd_sc_mcu7t5v0__addf_1 fulladder (
            .A(A[i]), .B(B[i]), .CI(C[i]), .CO(X[i]), .S(Y[i])
          );
      end
    end endgenerate

endmodule
