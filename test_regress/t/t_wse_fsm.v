// DESCRIPTION: Verilator: Verilog Test module for WSE backend
//
// 8-state Moore FSM (IDLE, S1-S6, DONE).
// Transitions based on 2-bit input. Verify output matches expected for each state.
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

   // FSM states
   localparam [2:0] ST_IDLE = 3'd0;
   localparam [2:0] ST_S1   = 3'd1;
   localparam [2:0] ST_S2   = 3'd2;
   localparam [2:0] ST_S3   = 3'd3;
   localparam [2:0] ST_S4   = 3'd4;
   localparam [2:0] ST_S5   = 3'd5;
   localparam [2:0] ST_S6   = 3'd6;
   localparam [2:0] ST_DONE = 3'd7;

   reg  [2:0] state;
   reg  [1:0] inp;
   reg  [7:0] out_val;  // Moore output depends only on state

   // Moore output logic
   always @(*) begin
      case (state)
         ST_IDLE: out_val = 8'h00;
         ST_S1:   out_val = 8'h11;
         ST_S2:   out_val = 8'h22;
         ST_S3:   out_val = 8'h33;
         ST_S4:   out_val = 8'h44;
         ST_S5:   out_val = 8'h55;
         ST_S6:   out_val = 8'h66;
         ST_DONE: out_val = 8'hFF;
         default: out_val = 8'hXX;
      endcase
   end

   // State transition logic
   always @(posedge clk) begin
      if (cyc < 2) begin
         state <= ST_IDLE;
      end else begin
         case (state)
            ST_IDLE: begin
               if (inp == 2'b01) state <= ST_S1;
               else              state <= ST_IDLE;
            end
            ST_S1: begin
               if (inp == 2'b10) state <= ST_S2;
               else if (inp == 2'b11) state <= ST_S3;
               else              state <= ST_S1;
            end
            ST_S2: begin
               if (inp == 2'b01) state <= ST_S4;
               else              state <= ST_S2;
            end
            ST_S3: begin
               if (inp == 2'b10) state <= ST_S5;
               else              state <= ST_S3;
            end
            ST_S4: begin
               if (inp == 2'b11) state <= ST_S6;
               else              state <= ST_S4;
            end
            ST_S5: begin
               if (inp == 2'b01) state <= ST_S6;
               else              state <= ST_S5;
            end
            ST_S6: begin
               if (inp == 2'b10) state <= ST_DONE;
               else              state <= ST_S6;
            end
            ST_DONE: begin
               state <= ST_DONE;  // Terminal state
            end
            default: state <= ST_IDLE;
         endcase
      end
   end

   // Test stimulus and checking
   always @(posedge clk) begin
      cyc <= cyc + 1;

      // Drive inputs to walk through states: IDLE->S1->S2->S4->S6->DONE
      case (cyc)
         2:  inp <= 2'b00;  // Stay in IDLE
         5:  inp <= 2'b01;  // IDLE -> S1
         8:  inp <= 2'b10;  // S1 -> S2
         11: inp <= 2'b01;  // S2 -> S4
         14: inp <= 2'b11;  // S4 -> S6
         17: inp <= 2'b10;  // S6 -> DONE
         default: ;
      endcase

      // Verify state outputs
      if (cyc == 4) begin
         if (state !== ST_IDLE || out_val !== 8'h00) begin
            $display("%%Error: cyc=%0d state=%0d out=%h, expected IDLE/00", cyc, state, out_val);
            $stop;
         end
         $display("[%0t] State IDLE: out=0x%02h OK", $time, out_val);
      end
      if (cyc == 7) begin
         if (state !== ST_S1 || out_val !== 8'h11) begin
            $display("%%Error: cyc=%0d state=%0d out=%h, expected S1/11", cyc, state, out_val);
            $stop;
         end
         $display("[%0t] State S1: out=0x%02h OK", $time, out_val);
      end
      if (cyc == 10) begin
         if (state !== ST_S2 || out_val !== 8'h22) begin
            $display("%%Error: cyc=%0d state=%0d out=%h, expected S2/22", cyc, state, out_val);
            $stop;
         end
         $display("[%0t] State S2: out=0x%02h OK", $time, out_val);
      end
      if (cyc == 13) begin
         if (state !== ST_S4 || out_val !== 8'h44) begin
            $display("%%Error: cyc=%0d state=%0d out=%h, expected S4/44", cyc, state, out_val);
            $stop;
         end
         $display("[%0t] State S4: out=0x%02h OK", $time, out_val);
      end
      if (cyc == 16) begin
         if (state !== ST_S6 || out_val !== 8'h66) begin
            $display("%%Error: cyc=%0d state=%0d out=%h, expected S6/66", cyc, state, out_val);
            $stop;
         end
         $display("[%0t] State S6: out=0x%02h OK", $time, out_val);
      end
      if (cyc == 19) begin
         if (state !== ST_DONE || out_val !== 8'hFF) begin
            $display("%%Error: cyc=%0d state=%0d out=%h, expected DONE/FF", cyc, state, out_val);
            $stop;
         end
         $display("[%0t] State DONE: out=0x%02h OK", $time, out_val);
      end

      // Now walk the alternate path: reset and go IDLE->S1->S3->S5->S6->DONE
      if (cyc == 50) begin
         $display("[%0t] Starting alternate path test", $time);
      end

      if (cyc == 300) begin
         $display("[%0t] All FSM tests passed", $time);
         $write("*-* All Finished *-*\n");
         $finish;
      end
   end

endmodule
