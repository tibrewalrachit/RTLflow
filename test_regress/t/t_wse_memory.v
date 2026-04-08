// DESCRIPTION: Verilator: Verilog Test module for WSE backend
//
// 256x32-bit synchronous RAM. Write pattern, then read back and verify.
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

   // RAM signals
   reg         we;
   reg  [7:0]  addr;
   reg  [31:0] wdata;
   reg  [31:0] rdata;

   // 256x32 synchronous RAM
   reg [31:0] mem [0:255];

   always @(posedge clk) begin
      if (we) begin
         mem[addr] <= wdata;
      end
      rdata <= mem[addr];
   end

   // Test phases
   localparam PHASE_RESET = 0;
   localparam PHASE_WRITE = 1;
   localparam PHASE_READ  = 2;
   localparam PHASE_CHECK = 3;

   reg [1:0]  phase;
   reg [8:0]  idx;       // 0..255, use 9 bits to detect overflow
   reg [31:0] error_count;
   reg [31:0] check_addr;
   reg [31:0] expected_data;

   always @(posedge clk) begin
      cyc <= cyc + 1;

      if (cyc < 2) begin
         // Reset
         phase <= PHASE_WRITE;
         idx   <= 9'd0;
         we    <= 1'b0;
         addr  <= 8'd0;
         wdata <= 32'd0;
         error_count <= 32'd0;
         check_addr <= 32'd0;
      end
      else if (phase == PHASE_WRITE) begin
         // Write pattern: addr -> (addr * 0xDEAD + 0xBEEF)
         we    <= 1'b1;
         addr  <= idx[7:0];
         wdata <= {idx[7:0], 8'h00, idx[7:0] ^ 8'hFF, 8'hAA};
         // Pattern: {addr, 0x00, ~addr, 0xAA}

         if (idx == 9'd255) begin
            phase <= PHASE_READ;
            idx   <= 9'd0;
            $display("[%0t] Write phase complete", $time);
         end else begin
            idx <= idx + 9'd1;
         end
      end
      else if (phase == PHASE_READ) begin
         we   <= 1'b0;
         addr <= idx[7:0];

         // One cycle after setting addr, check the read data
         if (idx > 9'd0) begin
            expected_data = {(idx[7:0] - 8'd1), 8'h00,
                             (idx[7:0] - 8'd1) ^ 8'hFF, 8'hAA};
            if (rdata !== expected_data) begin
               $display("%%Error: addr=%0d read=%h expected=%h",
                        idx - 9'd1, rdata, expected_data);
               error_count <= error_count + 32'd1;
            end
         end

         if (idx == 9'd256) begin
            phase <= PHASE_CHECK;
            $display("[%0t] Read phase complete", $time);
         end else begin
            idx <= idx + 9'd1;
         end

         if (idx % 64 == 0)
            $display("[%0t] Reading addr=%0d", $time, idx);
      end
      else if (phase == PHASE_CHECK) begin
         // Check the last read
         expected_data = {8'hFF, 8'h00, 8'hFF ^ 8'hFF, 8'hAA};
         if (rdata !== expected_data && check_addr == 32'd0) begin
            $display("%%Error: final addr=255 read=%h expected=%h",
                     rdata, expected_data);
            error_count <= error_count + 32'd1;
         end
         check_addr <= check_addr + 32'd1;
      end

      if (cyc == 199) begin
         $display("[%0t] Memory test: errors=%0d", $time, error_count);
         if (error_count !== 32'd0) begin
            $display("%%Error: Memory test failed with %0d errors", error_count);
            $stop;
         end
         $write("*-* All Finished *-*\n");
         $finish;
      end
   end

endmodule
