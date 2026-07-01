`timescale 1ns/1ps
module tb;
    reg clk, rst_n, en;
    reg [7:0] data;
    wire [7:0] crc;
    reg [7:0] model;
    integer i, j, errors;
    reg fb;

    crc8 dut (.*);

    initial clk = 0;
    always #5 clk = ~clk;

    task model_step(input [7:0] d);
        begin
            for (j = 7; j >= 0; j = j - 1) begin
                fb = model[7] ^ d[j];
                model = {model[6:0], 1'b0} ^ (fb ? 8'h07 : 8'h00);
            end
        end
    endtask

    initial begin
        errors = 0;
        rst_n = 0; en = 0; data = 0; model = 0;
        repeat (3) @(posedge clk);
        rst_n = 1;
        for (i = 0; i < 2000; i = i + 1) begin
            @(negedge clk);
            data = $random;
            en = ($random & 3) != 0;
            @(posedge clk);
            if (en) model_step(data);
            #1;
            if (crc !== model) begin
                $display("MISMATCH data=%h crc=%h model=%h", data, crc, model);
                errors = errors + 1;
            end
        end
        if (errors == 0) $display("TEST PASSED");
        else $display("TEST FAILED: %0d errors", errors);
        $finish;
    end
endmodule
