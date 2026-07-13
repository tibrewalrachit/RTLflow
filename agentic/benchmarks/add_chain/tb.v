`timescale 1ns/1ps
module tb;
    reg clk, rst_n, en;
    reg [15:0] in0, in1, in2, in3, in4, in5, in6, in7;
    wire [19:0] acc;
    reg [19:0] model;
    integer i, errors;

    add_chain dut (.*);

    initial clk = 0;
    always #5 clk = ~clk;

    task apply_random;
        begin
            in0 = $random; in1 = $random; in2 = $random; in3 = $random;
            in4 = $random; in5 = $random; in6 = $random; in7 = $random;
            en  = ($random & 3) != 0;
        end
    endtask

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) model <= 0;
        else if (en) model <= model + in0 + in1 + in2 + in3 + in4 + in5 + in6 + in7;
    end

    initial begin
        errors = 0;
        rst_n = 0; en = 0;
        {in0, in1, in2, in3, in4, in5, in6, in7} = 0;
        repeat (4) @(posedge clk);
        rst_n = 1;
        for (i = 0; i < 1000; i = i + 1) begin
            @(negedge clk);
            apply_random;
            @(posedge clk);
            #1;
            if (acc !== model) begin
                $display("MISMATCH t=%0t acc=%h model=%h", $time, acc, model);
                errors = errors + 1;
            end
        end
        if (errors == 0) $display("TEST PASSED");
        else $display("TEST FAILED: %0d errors", errors);
        $finish;
    end
endmodule
