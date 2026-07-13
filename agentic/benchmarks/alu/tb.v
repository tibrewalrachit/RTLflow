`timescale 1ns/1ps
module tb;
    reg clk, rst_n;
    reg [2:0] op;
    reg [15:0] a, b;
    wire [15:0] y;
    wire zero;
    reg [15:0] exp;
    integer i, errors;

    alu dut (.*);

    initial clk = 0;
    always #5 clk = ~clk;

    task expected(input [2:0] o, input [15:0] x, input [15:0] w, output [15:0] r);
        case (o)
            3'd0: r = x + w;
            3'd1: r = x - w;
            3'd2: r = x & w;
            3'd3: r = x | w;
            3'd4: r = x ^ w;
            3'd5: r = {15'b0, $signed(x) < $signed(w)};
            3'd6: r = x << w[3:0];
            default: r = x >> w[3:0];
        endcase
    endtask

    initial begin
        errors = 0;
        rst_n = 0; op = 0; a = 0; b = 0;
        repeat (3) @(posedge clk);
        rst_n = 1;
        for (i = 0; i < 2000; i = i + 1) begin
            @(negedge clk);
            op = $random; a = $random; b = $random;
            @(posedge clk);
            #1;
            expected(op, a, b, exp);
            if (y !== exp || zero !== (exp == 16'd0)) begin
                $display("MISMATCH op=%0d a=%h b=%h y=%h exp=%h", op, a, b, y, exp);
                errors = errors + 1;
            end
        end
        if (errors == 0) $display("TEST PASSED");
        else $display("TEST FAILED: %0d errors", errors);
        $finish;
    end
endmodule
