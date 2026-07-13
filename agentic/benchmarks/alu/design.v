// alu: 16-bit ALU with a registered result.
// Baseline style: a serial priority-mux cascade selects the result, and the
// slt/comparison logic sits in series with the adder — inviting one-hot
// pre-decoding, parallel case restructuring, and condition pre-computation.
module alu (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [2:0]  op,
    input  wire [15:0] a,
    input  wire [15:0] b,
    output reg  [15:0] y,
    output reg         zero
);
    wire [16:0] sum  = {1'b0, a} + {1'b0, b};
    wire [16:0] diff = {1'b0, a} - {1'b0, b};
    wire        slt  = ($signed(a) < $signed(b));

    wire [15:0] result =
        (op == 3'd0) ? sum[15:0] :
        (op == 3'd1) ? diff[15:0] :
        (op == 3'd2) ? (a & b) :
        (op == 3'd3) ? (a | b) :
        (op == 3'd4) ? (a ^ b) :
        (op == 3'd5) ? {15'b0, slt} :
        (op == 3'd6) ? (a << b[3:0]) :
                       (a >> b[3:0]);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            y    <= 16'd0;
            zero <= 1'b0;
        end else begin
            y    <= result;
            zero <= (result == 16'd0);
        end
    end
endmodule
