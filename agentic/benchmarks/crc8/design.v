// crc8: CRC-8 (poly 0x07) over one input byte per cycle.
// Baseline style: eight explicitly chained single-bit CRC steps — a serial
// XOR/mux chain 8 stages deep, inviting XOR-tree flattening / precomputing
// the byte-parallel update matrix.
module crc8 (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       en,
    input  wire [7:0] data,
    output reg  [7:0] crc
);
    function [7:0] step;
        input [7:0] c;
        input       d;
        reg         fb;
        begin
            fb   = c[7] ^ d;
            step = {c[6:0], 1'b0} ^ (fb ? 8'h07 : 8'h00);
        end
    endfunction

    wire [7:0] s0 = step(crc, data[7]);
    wire [7:0] s1 = step(s0,  data[6]);
    wire [7:0] s2 = step(s1,  data[5]);
    wire [7:0] s3 = step(s2,  data[4]);
    wire [7:0] s4 = step(s3,  data[3]);
    wire [7:0] s5 = step(s4,  data[2]);
    wire [7:0] s6 = step(s5,  data[1]);
    wire [7:0] s7 = step(s6,  data[0]);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            crc <= 8'h00;
        else if (en)
            crc <= s7;
    end
endmodule
