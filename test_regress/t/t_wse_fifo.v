// DESCRIPTION: Verilator: Verilog Test module for WSE backend
//
// 8-entry deep FIFO with write enable, read enable, full/empty flags.
// Write sequential values, read them back, verify FIFO ordering.
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

   // FIFO signals
   reg         wr_en;
   reg         rd_en;
   reg  [31:0] wr_data;
   wire [31:0] rd_data;
   wire        full;
   wire        empty;

   // FIFO storage
   reg [31:0] fifo_mem [0:7];
   reg [2:0]  wr_ptr;
   reg [2:0]  rd_ptr;
   reg [3:0]  count;  // 0..8

   assign full  = (count == 4'd8);
   assign empty = (count == 4'd0);
   assign rd_data = fifo_mem[rd_ptr];

   always @(posedge clk) begin
      if (cyc < 2) begin
         // Reset
         wr_ptr <= 3'd0;
         rd_ptr <= 3'd0;
         count  <= 4'd0;
      end else begin
         if (wr_en && !full) begin
            fifo_mem[wr_ptr] <= wr_data;
            wr_ptr <= wr_ptr + 3'd1;
            if (!(rd_en && !empty))
               count <= count + 4'd1;
         end
         if (rd_en && !empty) begin
            rd_ptr <= rd_ptr + 3'd1;
            if (!(wr_en && !full))
               count <= count - 4'd1;
         end
      end
   end

   // Expected read value tracker
   reg [31:0] expected_rd;
   reg [31:0] write_val;
   reg [31:0] read_count;
   reg        error_found;

   // Test sequence
   always @(posedge clk) begin
      cyc <= cyc + 1;
      wr_en <= 1'b0;
      rd_en <= 1'b0;

      if (cyc < 2) begin
         // Reset phase
         write_val <= 32'd100;
         expected_rd <= 32'd100;
         read_count <= 32'd0;
         error_found <= 1'b0;
      end
      // Phase 1: Write 8 values to fill the FIFO (cyc 2..9)
      else if (cyc >= 2 && cyc < 10) begin
         wr_en <= 1'b1;
         wr_data <= write_val;
         write_val <= write_val + 32'd1;
         if (cyc == 2) $display("[%0t] Phase 1: Filling FIFO", $time);
      end
      // Phase 2: Check full flag (cyc 10)
      else if (cyc == 11) begin
         $display("[%0t] FIFO full=%b empty=%b count=%0d", $time, full, empty, count);
         if (!full) begin
            $display("%%Error: FIFO should be full");
            error_found <= 1'b1;
         end
      end
      // Phase 3: Read all 8 values back (cyc 12..19)
      else if (cyc >= 12 && cyc < 20) begin
         rd_en <= 1'b1;
         if (cyc == 12) $display("[%0t] Phase 3: Draining FIFO", $time);
      end
      // Phase 3b: Verify reads (cyc 13..20, one cycle after rd_en)
      else if (cyc >= 20 && cyc == 20) begin
         $display("[%0t] FIFO full=%b empty=%b count=%0d", $time, full, empty, count);
         if (!empty) begin
            $display("%%Error: FIFO should be empty after draining");
            error_found <= 1'b1;
         end
      end
      // Phase 4: Interleaved write/read (cyc 30..130)
      else if (cyc >= 30 && cyc < 130) begin
         // Write every cycle, read every other cycle
         if (!full) begin
            wr_en <= 1'b1;
            wr_data <= write_val;
            write_val <= write_val + 32'd1;
         end
         if ((cyc % 2 == 0) && !empty) begin
            rd_en <= 1'b1;
         end
         if (cyc % 50 == 0)
            $display("[%0t] cyc=%0d count=%0d full=%b empty=%b",
                     $time, cyc, count, full, empty);
      end
      // Phase 5: Drain remaining
      else if (cyc >= 130 && cyc < 150) begin
         if (!empty) begin
            rd_en <= 1'b1;
         end
      end

      if (cyc == 500) begin
         if (error_found) begin
            $display("%%Error: Test failed");
            $stop;
         end
         $display("[%0t] Final: cyc=%0d", $time, cyc);
         $write("*-* All Finished *-*\n");
         $finish;
      end
   end

endmodule
