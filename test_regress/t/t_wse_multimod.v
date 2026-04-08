// DESCRIPTION: Verilator: Verilog Test module for WSE backend
//
// 3 sub-modules connected with simple handshake signals (valid/ready/data).
// Producer sends data to processor, processor forwards to consumer.
// Verify data integrity.
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

   reg         reset;

   // Producer -> Processor interface
   wire        p2proc_valid;
   wire        p2proc_ready;
   wire [31:0] p2proc_data;

   // Processor -> Consumer interface
   wire        proc2c_valid;
   wire        proc2c_ready;
   wire [31:0] proc2c_data;

   // Consumer output for verification
   wire        consumer_done;
   wire [31:0] consumer_data_out;
   wire        consumer_data_valid;

   producer u_producer (
      .clk     (clk),
      .reset   (reset),
      .valid   (p2proc_valid),
      .ready   (p2proc_ready),
      .data    (p2proc_data)
   );

   processor u_processor (
      .clk       (clk),
      .reset     (reset),
      .in_valid  (p2proc_valid),
      .in_ready  (p2proc_ready),
      .in_data   (p2proc_data),
      .out_valid (proc2c_valid),
      .out_ready (proc2c_ready),
      .out_data  (proc2c_data)
   );

   consumer u_consumer (
      .clk        (clk),
      .reset      (reset),
      .valid      (proc2c_valid),
      .ready      (proc2c_ready),
      .data       (proc2c_data),
      .done       (consumer_done),
      .data_out   (consumer_data_out),
      .data_valid (consumer_data_valid)
   );

   // Verification
   reg [31:0] expected_val;
   reg [31:0] received_count;
   reg [31:0] error_count;

   always @(posedge clk) begin
      cyc <= cyc + 1;

      if (cyc < 3) begin
         reset <= 1'b1;
         expected_val <= 32'd1;
         received_count <= 32'd0;
         error_count <= 32'd0;
      end else begin
         reset <= 1'b0;
      end

      // Check consumer output
      if (!reset && consumer_data_valid) begin
         received_count <= received_count + 32'd1;
         if (consumer_data_out !== expected_val) begin
            $display("%%Error: cyc=%0d received=%0d expected=%0d",
                     cyc, consumer_data_out, expected_val);
            error_count <= error_count + 32'd1;
         end
         expected_val <= expected_val + 32'd1;
      end

      if (cyc % 100 == 0 && cyc > 0) begin
         $display("[%0t] cyc=%0d received=%0d errors=%0d",
                  $time, cyc, received_count, error_count);
      end

      if (cyc == 500) begin
         $display("[%0t] Final: received=%0d errors=%0d",
                  $time, received_count, error_count);
         if (error_count !== 32'd0) begin
            $display("%%Error: Data integrity check failed");
            $stop;
         end
         if (received_count == 32'd0) begin
            $display("%%Error: No data received");
            $stop;
         end
         $write("*-* All Finished *-*\n");
         $finish;
      end
   end

endmodule

// Producer: generates sequential data values with valid/ready handshake
module producer(
   input  wire        clk,
   input  wire        reset,
   output reg         valid,
   input  wire        ready,
   output reg  [31:0] data
);
   always @(posedge clk) begin
      if (reset) begin
         valid <= 1'b0;
         data  <= 32'd1;
      end else begin
         valid <= 1'b1;
         if (valid && ready) begin
            data <= data + 32'd1;
         end
      end
   end
endmodule

// Processor: accepts data, adds a 1-cycle latency, forwards to output
module processor(
   input  wire        clk,
   input  wire        reset,
   input  wire        in_valid,
   output wire        in_ready,
   input  wire [31:0] in_data,
   output reg         out_valid,
   input  wire        out_ready,
   output reg  [31:0] out_data
);
   // Simple pass-through with 1 cycle latency
   // Accept input when output is ready or we have no data
   assign in_ready = out_ready || !out_valid;

   always @(posedge clk) begin
      if (reset) begin
         out_valid <= 1'b0;
         out_data  <= 32'd0;
      end else begin
         if (in_ready) begin
            out_valid <= in_valid;
            out_data  <= in_data;
         end
      end
   end
endmodule

// Consumer: accepts data, outputs it for verification
module consumer(
   input  wire        clk,
   input  wire        reset,
   input  wire        valid,
   output reg         ready,
   input  wire [31:0] data,
   output reg         done,
   output reg  [31:0] data_out,
   output reg         data_valid
);
   reg [3:0] throttle_cnt;

   always @(posedge clk) begin
      if (reset) begin
         ready        <= 1'b0;
         done         <= 1'b0;
         data_out     <= 32'd0;
         data_valid   <= 1'b0;
         throttle_cnt <= 4'd0;
      end else begin
         // Throttle: ready most of the time, occasionally deassert
         throttle_cnt <= throttle_cnt + 4'd1;
         ready <= (throttle_cnt != 4'd7);  // Deassert ready 1 out of every 8 cycles

         data_valid <= 1'b0;
         if (valid && ready) begin
            data_out   <= data;
            data_valid <= 1'b1;
         end
      end
   end
endmodule
