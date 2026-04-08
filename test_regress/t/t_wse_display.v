// DESCRIPTION: Verilator: Verilog Test module for WSE backend
//
// Design that uses $display on every cycle. Simple counter that
// prints value each cycle. Tests display buffering.
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

   reg [31:0] counter;
   reg [31:0] accum;
   reg [7:0]  flags;

   // Counter and accumulator logic
   always @(posedge clk) begin
      if (cyc < 2) begin
         counter <= 32'd0;
         accum   <= 32'd0;
         flags   <= 8'd0;
      end else begin
         counter <= counter + 32'd1;
         accum   <= accum + counter;
         flags   <= {flags[6:0], counter[0]};
      end
   end

   // Display on every single cycle to test display buffering
   always @(posedge clk) begin
      cyc <= cyc + 1;

      $display("[%0t] cyc=%0d counter=%0d accum=%0d flags=%08b",
               $time, cyc, counter, accum, flags);

      // Additional multi-format display to stress test buffering
      if (cyc >= 2) begin
         $display("[%0t]   hex: counter=0x%08h accum=0x%08h",
                  $time, counter, accum);
      end

      // Verify accumulator: accum should be sum of 0..counter-1 = counter*(counter-1)/2
      // (with 1 cycle delay due to NBA)
      if (cyc == 30) begin
         // At cyc==30, counter was updated at end of cyc==29.
         // counter = 29-2+1 = 28 (counter starts incrementing at cyc==2, from 0).
         // At cyc==2, counter goes 0->1. At cyc==3, 1->2. At cyc==N, counter = N-2.
         // At cyc==30, counter = 28.
         // accum at cyc==30 = accum from end of cyc==29.
         // accum at cyc==N = sum of counter values seen from cyc==2 to cyc==N-1
         //                 = sum of 0,1,2,...,(N-3) = (N-3)*(N-2)/2
         // At cyc==30: accum = 27*28/2 = 378
         $display("[%0t] Verify: cyc=%0d counter=%0d accum=%0d (expect counter=28, accum=378)",
                  $time, cyc, counter, accum);
         if (counter !== 32'd28) begin
            $display("%%Error: counter=%0d expected 28", counter);
            $stop;
         end
         if (accum !== 32'd378) begin
            $display("%%Error: accum=%0d expected 378", accum);
            $stop;
         end
      end

      if (cyc == 50) begin
         $display("[%0t] Display buffering test complete after %0d display calls",
                  $time, cyc);
         $write("*-* All Finished *-*\n");
         $finish;
      end
   end

endmodule
