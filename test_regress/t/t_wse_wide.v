// DESCRIPTION: Verilator: Verilog Test module for WSE backend
//
// Design with 64-bit signals. 64-bit counter, 64-bit arithmetic,
// verify high and low halves.
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

   // 64-bit counter
   reg [63:0] counter64;

   // 64-bit arithmetic signals
   reg [63:0] val_a;
   reg [63:0] val_b;
   reg [63:0] sum64;
   reg [63:0] diff64;
   reg [63:0] and64;
   reg [63:0] or64;
   reg [63:0] xor64;

   // High/low half extraction
   wire [31:0] counter_hi = counter64[63:32];
   wire [31:0] counter_lo = counter64[31:0];

   // 64-bit counter logic
   always @(posedge clk) begin
      if (cyc < 2) begin
         counter64 <= 64'h0000_0000_FFFF_FFF0;  // Start near 32-bit overflow
      end else begin
         counter64 <= counter64 + 64'd1;
      end
   end

   // 64-bit arithmetic
   always @(posedge clk) begin
      if (cyc < 2) begin
         val_a  <= 64'hDEAD_BEEF_CAFE_BABE;
         val_b  <= 64'h1234_5678_9ABC_DEF0;
         sum64  <= 64'd0;
         diff64 <= 64'd0;
         and64  <= 64'd0;
         or64   <= 64'd0;
         xor64  <= 64'd0;
      end else begin
         sum64  <= val_a + val_b;
         diff64 <= val_a - val_b;
         and64  <= val_a & val_b;
         or64   <= val_a | val_b;
         xor64  <= val_a ^ val_b;
      end
   end

   // Test and verification
   always @(posedge clk) begin
      cyc <= cyc + 1;

      // Check counter crosses 32-bit boundary
      if (cyc == 20) begin
         // At cyc==2, counter resets to FFF0. At cyc==3, it becomes FFF1, etc.
         // At cyc==N (N>=2), counter = FFFF_FFF0 + (N-2)
         // At cyc==20, counter = FFFF_FFF0 + 18 = 1_0000_0002
         $display("[%0t] cyc=%0d counter64=0x%016h", $time, cyc, counter64);
         $display("[%0t]   hi=0x%08h lo=0x%08h", $time, counter_hi, counter_lo);
         if (counter_hi !== 32'h0000_0001) begin
            $display("%%Error: counter_hi=%h, expected 00000001", counter_hi);
            $stop;
         end
         if (counter_lo !== 32'h0000_0002) begin
            $display("%%Error: counter_lo=%h, expected 00000002", counter_lo);
            $stop;
         end
         $display("[%0t] 64-bit counter overflow test PASSED", $time);
      end

      // Check 64-bit arithmetic (results available at cyc==3)
      if (cyc == 3) begin
         $display("[%0t] 64-bit arithmetic test:", $time);

         // ADD
         if (sum64 !== 64'hF0E2_1568_6567_99AE) begin
            $display("%%Error: sum64=%h, expected F0E21568656799AE", sum64);
            $stop;
         end
         $display("[%0t]   ADD: 0x%016h OK", $time, sum64);

         // SUB
         if (diff64 !== 64'hCC79_6877_3042_DBCE) begin
            $display("%%Error: diff64=%h, expected CC796877_3042DBCE", diff64);
            $stop;
         end
         $display("[%0t]   SUB: 0x%016h OK", $time, diff64);

         // AND
         if (and64 !== 64'h1224_1668_8A9C_9AB0) begin
            $display("%%Error: and64=%h, expected 122416688A9C9AB0", and64);
            $stop;
         end
         $display("[%0t]   AND: 0x%016h OK", $time, and64);

         // OR
         if (or64 !== 64'hDEBD_FEFF_DAFE_FEFE) begin
            $display("%%Error: or64=%h, expected DEBDFEFFDAFEFEFE", or64);
            $stop;
         end
         $display("[%0t]   OR:  0x%016h OK", $time, or64);

         // XOR
         if (xor64 !== 64'hCC99_E897_5062_644E) begin
            $display("%%Error: xor64=%h, expected CC99E89750626_44E", xor64);
            $stop;
         end
         $display("[%0t]   XOR: 0x%016h OK", $time, xor64);
      end

      // Test large 64-bit value manipulation
      if (cyc == 50) begin
         $display("[%0t] cyc=%0d counter64=0x%016h", $time, cyc, counter64);
         // counter = FFFF_FFF0 + 48 = 1_0000_0020
         if (counter64 !== 64'h0000_0001_0000_0020) begin
            $display("%%Error: counter64=%h, expected 0000000100000020", counter64);
            $stop;
         end
      end

      if (cyc == 100) begin
         $display("[%0t] cyc=%0d counter64=0x%016h", $time, cyc, counter64);
         $display("[%0t] All 64-bit tests passed", $time);
         $write("*-* All Finished *-*\n");
         $finish;
      end
   end

endmodule
