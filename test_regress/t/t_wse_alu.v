// DESCRIPTION: Verilator: Verilog Test module for WSE backend
//
// 32-bit ALU supporting ADD, SUB, AND, OR, XOR, SHL, SHR operations.
// Cycle through all operations with test vectors, verify results.
//
// This file ONLY is placed under the Creative Commons Public Domain, for
// any use, without warranty, 2026 by Wilson Snyder.
// SPDX-License-Identifier: CC0-1.0

module t(/*AUTOARG*/
   // Inputs
   clk
   );
   input clk;

   integer cyc = 0;

   // ALU operation codes
   localparam [2:0] OP_ADD = 3'd0;
   localparam [2:0] OP_SUB = 3'd1;
   localparam [2:0] OP_AND = 3'd2;
   localparam [2:0] OP_OR  = 3'd3;
   localparam [2:0] OP_XOR = 3'd4;
   localparam [2:0] OP_SHL = 3'd5;
   localparam [2:0] OP_SHR = 3'd6;

   reg  [2:0]  op;
   reg  [31:0] a;
   reg  [31:0] b;
   wire [31:0] result;

   // ALU logic (combinational)
   reg [31:0] alu_out;
   always @(*) begin
      case (op)
         OP_ADD: alu_out = a + b;
         OP_SUB: alu_out = a - b;
         OP_AND: alu_out = a & b;
         OP_OR:  alu_out = a | b;
         OP_XOR: alu_out = a ^ b;
         OP_SHL: alu_out = a << b[4:0];
         OP_SHR: alu_out = a >> b[4:0];
         default: alu_out = 32'd0;
      endcase
   end
   assign result = alu_out;

   // Registered result for checking (one cycle delay)
   reg [31:0] result_r;
   reg [2:0]  op_r;
   reg [31:0] a_r, b_r;
   always @(posedge clk) begin
      result_r <= result;
      op_r <= op;
      a_r <= a;
      b_r <= b;
   end

   reg error_found;

   // Test sequence
   always @(posedge clk) begin
      cyc <= cyc + 1;
      error_found <= 1'b0;

      // Apply test vectors
      case (cyc)
         // ADD tests
         0: begin op <= OP_ADD; a <= 32'h0000_0001; b <= 32'h0000_0002; end
         1: begin op <= OP_ADD; a <= 32'hFFFF_FFFF; b <= 32'h0000_0001; end
         2: begin op <= OP_ADD; a <= 32'h8000_0000; b <= 32'h8000_0000; end
         3: begin op <= OP_ADD; a <= 32'h1234_5678; b <= 32'h8765_4321; end
         // SUB tests
         10: begin op <= OP_SUB; a <= 32'h0000_0005; b <= 32'h0000_0003; end
         11: begin op <= OP_SUB; a <= 32'h0000_0000; b <= 32'h0000_0001; end
         12: begin op <= OP_SUB; a <= 32'hAAAA_AAAA; b <= 32'h5555_5555; end
         // AND tests
         20: begin op <= OP_AND; a <= 32'hFF00_FF00; b <= 32'h0F0F_0F0F; end
         21: begin op <= OP_AND; a <= 32'hFFFF_FFFF; b <= 32'h1234_5678; end
         // OR tests
         30: begin op <= OP_OR; a <= 32'hFF00_0000; b <= 32'h0000_00FF; end
         31: begin op <= OP_OR; a <= 32'hAAAA_AAAA; b <= 32'h5555_5555; end
         // XOR tests
         40: begin op <= OP_XOR; a <= 32'hFFFF_FFFF; b <= 32'hFFFF_FFFF; end
         41: begin op <= OP_XOR; a <= 32'hAAAA_AAAA; b <= 32'h5555_5555; end
         // SHL tests
         50: begin op <= OP_SHL; a <= 32'h0000_0001; b <= 32'h0000_0004; end
         51: begin op <= OP_SHL; a <= 32'hDEAD_BEEF; b <= 32'h0000_0010; end
         // SHR tests
         60: begin op <= OP_SHR; a <= 32'h8000_0000; b <= 32'h0000_0004; end
         61: begin op <= OP_SHR; a <= 32'hDEAD_BEEF; b <= 32'h0000_0010; end
         default: begin op <= OP_ADD; a <= 32'd0; b <= 32'd0; end
      endcase

      // Verify results (one cycle later, using combinational result directly)
      // We verify on the same cycle using the combinational output
      case (cyc)
         // Verify ADD results (checking previous cycle's inputs which are now in a_r/b_r)
         1: begin
            if (result_r !== 32'h0000_0003) begin
               $display("%%Error: ADD 1+2=%h, expected 3", result_r);
               $stop;
            end
            $display("[%0t] ADD: 0x00000001 + 0x00000002 = 0x%08h OK", $time, result_r);
         end
         2: begin
            if (result_r !== 32'h0000_0000) begin
               $display("%%Error: ADD FFFFFFFF+1=%h, expected 0", result_r);
               $stop;
            end
            $display("[%0t] ADD: 0xFFFFFFFF + 0x00000001 = 0x%08h OK", $time, result_r);
         end
         11: begin
            if (result_r !== 32'h0000_0002) begin
               $display("%%Error: SUB 5-3=%h, expected 2", result_r);
               $stop;
            end
            $display("[%0t] SUB: 0x00000005 - 0x00000003 = 0x%08h OK", $time, result_r);
         end
         12: begin
            if (result_r !== 32'hFFFF_FFFF) begin
               $display("%%Error: SUB 0-1=%h, expected FFFFFFFF", result_r);
               $stop;
            end
            $display("[%0t] SUB: 0x00000000 - 0x00000001 = 0x%08h OK", $time, result_r);
         end
         21: begin
            if (result_r !== 32'h0F00_0F00) begin
               $display("%%Error: AND=%h, expected 0F000F00", result_r);
               $stop;
            end
            $display("[%0t] AND: 0xFF00FF00 & 0x0F0F0F0F = 0x%08h OK", $time, result_r);
         end
         31: begin
            if (result_r !== 32'hFF00_00FF) begin
               $display("%%Error: OR=%h, expected FF0000FF", result_r);
               $stop;
            end
            $display("[%0t] OR:  0xFF000000 | 0x000000FF = 0x%08h OK", $time, result_r);
         end
         32: begin
            if (result_r !== 32'hFFFF_FFFF) begin
               $display("%%Error: OR=%h, expected FFFFFFFF", result_r);
               $stop;
            end
            $display("[%0t] OR:  0xAAAAAAAA | 0x55555555 = 0x%08h OK", $time, result_r);
         end
         41: begin
            if (result_r !== 32'h0000_0000) begin
               $display("%%Error: XOR=%h, expected 0", result_r);
               $stop;
            end
            $display("[%0t] XOR: 0xFFFFFFFF ^ 0xFFFFFFFF = 0x%08h OK", $time, result_r);
         end
         42: begin
            if (result_r !== 32'hFFFF_FFFF) begin
               $display("%%Error: XOR=%h, expected FFFFFFFF", result_r);
               $stop;
            end
            $display("[%0t] XOR: 0xAAAAAAAA ^ 0x55555555 = 0x%08h OK", $time, result_r);
         end
         51: begin
            if (result_r !== 32'h0000_0010) begin
               $display("%%Error: SHL=%h, expected 10", result_r);
               $stop;
            end
            $display("[%0t] SHL: 0x00000001 << 4 = 0x%08h OK", $time, result_r);
         end
         61: begin
            if (result_r !== 32'h0800_0000) begin
               $display("%%Error: SHR=%h, expected 08000000", result_r);
               $stop;
            end
            $display("[%0t] SHR: 0x80000000 >> 4 = 0x%08h OK", $time, result_r);
         end
      endcase

      if (cyc == 200) begin
         $display("[%0t] All ALU tests passed", $time);
         $write("*-* All Finished *-*\n");
         $finish;
      end
   end

endmodule
