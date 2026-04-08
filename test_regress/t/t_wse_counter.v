// DESCRIPTION: Verilator: Verilog Test module for WSE backend
//
// 32-bit counter with synchronous reset.
// Reset active for first 10 cycles, then count up.
// After 1000 cycles, check counter value matches expected.
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

   reg        reset;
   reg [31:0] counter;

   // Synchronous reset and count logic
   always @(posedge clk) begin
      if (reset) begin
         counter <= 32'd0;
      end else begin
         counter <= counter + 32'd1;
      end
   end

   // Test loop
   always @(posedge clk) begin
      cyc <= cyc + 1;

      // Hold reset for first 10 cycles
      if (cyc < 10) begin
         reset <= 1'b1;
      end else begin
         reset <= 1'b0;
      end

      // Print counter value periodically
      if (cyc >= 12 && (cyc % 100 == 0)) begin
         $display("[%0t] cyc=%0d counter=%0d", $time, cyc, counter);
      end

      if (cyc == 1000) begin
         // After reset deasserts at cycle 10, counter starts incrementing at cycle 11.
         // At cycle 11: counter goes from 0->1 (reset was 0, so counter increments)
         // The counter value is registered, so at posedge of cycle N (N>=11),
         // counter holds the value from the previous cycle's computation.
         // Reset deasserts at cyc==10 (set to 0). At cyc==11 posedge, reset is 0,
         // so counter becomes 0+1=1. At cyc==12, counter becomes 1+1=2, etc.
         // At cyc==1000, counter = 1000-11 = 989. But we read counter before
         // the current cycle's always block updates it (non-blocking), so the
         // value we see at cyc==1000 is what was computed at cyc==999.
         // counter at cyc==N (for N>=11) = N - 11 (value visible at start of cycle)
         // Actually with NBA, at the posedge where cyc==1000:
         //   counter was updated at end of cyc==999 to (999-11) = 988... let's
         //   just compute: reset goes low when cyc transitions from 9 to 10.
         // Let's trace carefully:
         //   cyc 0-9:  reset=1, counter=0
         //   cyc 10:   reset transitions to 0 (NBA), counter still gets reset=1? No.
         //   The reset NBA from cyc<10 means: at cyc==9 posedge, reset<=1.
         //   At cyc==10 posedge, cyc is now 10, so reset<=0. But reset is still 1
         //   from the previous NBA. So counter<=0+1=1 (since reset is still 1 at
         //   this posedge? No - reset<=1 was assigned at cyc 9, so at cyc 10 posedge
         //   reset IS 1). Actually the condition is cyc<10, and at posedge where
         //   cyc becomes 10, the old cyc is 9, so 9<10 is true, reset<=1.
         //   Wait: cyc<=cyc+1 is also NBA. At the posedge where cyc transitions
         //   9->10, the if(cyc<10) sees cyc==9 (old value), so reset<=1.
         //   At posedge where cyc==10 (old value), 10<10 is false, so reset<=0.
         //   So reset becomes 0 at end of the cycle where cyc was 10.
         //   At that same posedge (cyc==10), counter sees reset==1 (old), counter<=0.
         //   At posedge cyc==11 (old), reset is now 0, counter <= 0+1 = 1.
         //   At posedge cyc==12, counter <= 1+1 = 2.
         //   At posedge cyc==N (N>=11), counter <= (N-11) + 1 = N-10.
         //   But we READ counter at posedge cyc==N before NBA resolves, so
         //   counter's value is from previous cycle: at cyc==N, counter = N-11.
         //   Hmm, actually both always blocks execute at the same posedge.
         //   The read of counter in $display reads the OLD value.
         //   At cyc==1000, counter old value = 1000-11 = 989.
         //
         // To avoid confusion, let's just check with a generous margin and
         // use a golden value. The expected value is 989.
         $display("[%0t] Final: cyc=%0d counter=%0d", $time, cyc, counter);
         if (counter !== 32'd989) begin
            $display("%%Error: counter=%0d, expected 989", counter);
            $stop;
         end
         $write("*-* All Finished *-*\n");
         $finish;
      end
   end

endmodule
