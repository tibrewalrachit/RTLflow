// DESCRIPTION: Verilator: Verilog Test module for WSE backend
//
// 4-stage pipeline (fetch, decode, execute, writeback).
// Each stage is a register. Pipeline data through and verify
// output matches input delayed by 4 cycles.
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

   // Pipeline registers
   reg [31:0] pipe_in;
   reg [31:0] stage_fetch;
   reg [31:0] stage_decode;
   reg [31:0] stage_execute;
   reg [31:0] stage_writeback;

   // Pipeline valid bits
   reg        valid_in;
   reg        valid_fetch;
   reg        valid_decode;
   reg        valid_execute;
   reg        valid_writeback;

   // Pipeline logic
   always @(posedge clk) begin
      if (cyc < 2) begin
         stage_fetch     <= 32'd0;
         stage_decode    <= 32'd0;
         stage_execute   <= 32'd0;
         stage_writeback <= 32'd0;
         valid_fetch     <= 1'b0;
         valid_decode    <= 1'b0;
         valid_execute   <= 1'b0;
         valid_writeback <= 1'b0;
      end else begin
         // Stage 1: Fetch
         stage_fetch  <= pipe_in;
         valid_fetch  <= valid_in;
         // Stage 2: Decode
         stage_decode <= stage_fetch;
         valid_decode <= valid_fetch;
         // Stage 3: Execute
         stage_execute <= stage_decode;
         valid_execute <= valid_decode;
         // Stage 4: Writeback
         stage_writeback <= stage_execute;
         valid_writeback <= valid_execute;
      end
   end

   // Reference delay line for checking
   reg [31:0] ref_d1, ref_d2, ref_d3, ref_d4;
   reg        ref_v1, ref_v2, ref_v3, ref_v4;

   always @(posedge clk) begin
      if (cyc < 2) begin
         ref_d1 <= 32'd0; ref_d2 <= 32'd0; ref_d3 <= 32'd0; ref_d4 <= 32'd0;
         ref_v1 <= 1'b0;  ref_v2 <= 1'b0;  ref_v3 <= 1'b0;  ref_v4 <= 1'b0;
      end else begin
         ref_d1 <= pipe_in;  ref_d2 <= ref_d1;  ref_d3 <= ref_d2;  ref_d4 <= ref_d3;
         ref_v1 <= valid_in; ref_v2 <= ref_v1;  ref_v3 <= ref_v2;  ref_v4 <= ref_v3;
      end
   end

   // Test stimulus and verification
   reg [31:0] error_count;

   always @(posedge clk) begin
      cyc <= cyc + 1;

      if (cyc < 2) begin
         pipe_in <= 32'd0;
         valid_in <= 1'b0;
         error_count <= 32'd0;
      end
      // Feed sequential values into the pipeline
      else if (cyc >= 2 && cyc < 900) begin
         pipe_in <= cyc[31:0];
         valid_in <= 1'b1;
      end else begin
         pipe_in <= 32'd0;
         valid_in <= 1'b0;
      end

      // Verify pipeline output matches reference
      if (cyc >= 7 && cyc < 905) begin
         if (valid_writeback !== ref_v4) begin
            $display("%%Error: cyc=%0d valid mismatch: pipe=%b ref=%b",
                     cyc, valid_writeback, ref_v4);
            error_count <= error_count + 32'd1;
         end
         if (valid_writeback && (stage_writeback !== ref_d4)) begin
            $display("%%Error: cyc=%0d data mismatch: pipe=%h ref=%h",
                     cyc, stage_writeback, ref_d4);
            error_count <= error_count + 32'd1;
         end
      end

      // Periodic display
      if (cyc >= 6 && cyc < 20) begin
         $display("[%0t] cyc=%0d in=%0d wb=%0d valid_wb=%b",
                  $time, cyc, pipe_in, stage_writeback, valid_writeback);
      end
      if (cyc % 200 == 0 && cyc > 0) begin
         $display("[%0t] cyc=%0d pipeline running, errors=%0d",
                  $time, cyc, error_count);
      end

      if (cyc == 1000) begin
         if (error_count !== 32'd0) begin
            $display("%%Error: %0d pipeline errors detected", error_count);
            $stop;
         end
         $display("[%0t] Pipeline test passed with 0 errors", $time);
         $write("*-* All Finished *-*\n");
         $finish;
      end
   end

endmodule
