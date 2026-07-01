`timescale 1ns/1ps
module tb;
    reg clk, rst_n;
    reg [31:0] key;
    reg [31:0] pat [0:7];
    reg [31:0] mask [0:7];
    wire [2:0] idx;
    wire hit;
    reg [2:0] exp_idx;
    reg exp_hit;
    integer i, j, errors;

    priority_match dut (
        .clk(clk), .rst_n(rst_n), .key(key),
        .pat0(pat[0]), .mask0(mask[0]), .pat1(pat[1]), .mask1(mask[1]),
        .pat2(pat[2]), .mask2(mask[2]), .pat3(pat[3]), .mask3(mask[3]),
        .pat4(pat[4]), .mask4(mask[4]), .pat5(pat[5]), .mask5(mask[5]),
        .pat6(pat[6]), .mask6(mask[6]), .pat7(pat[7]), .mask7(mask[7]),
        .idx(idx), .hit(hit)
    );

    initial clk = 0;
    always #5 clk = ~clk;

    task compute_expected;
        begin
            exp_idx = 3'd7;
            exp_hit = 1'b0;
            begin : find
                for (j = 0; j < 7; j = j + 1) begin
                    if ((key & mask[j]) == (pat[j] & mask[j])) begin
                        exp_idx = j[2:0];
                        disable find;
                    end
                end
            end
            for (j = 0; j < 8; j = j + 1)
                if ((key & mask[j]) == (pat[j] & mask[j])) exp_hit = 1'b1;
        end
    endtask

    initial begin
        errors = 0;
        rst_n = 0; key = 0;
        for (j = 0; j < 8; j = j + 1) begin pat[j] = 0; mask[j] = 0; end
        repeat (3) @(posedge clk);
        rst_n = 1;
        for (i = 0; i < 2000; i = i + 1) begin
            @(negedge clk);
            key = $random;
            for (j = 0; j < 8; j = j + 1) begin
                pat[j] = $random;
                // Sparse masks so matches actually occur.
                mask[j] = $random & $random & $random;
            end
            @(posedge clk);
            #1;
            compute_expected;
            if (idx !== exp_idx || hit !== exp_hit) begin
                $display("MISMATCH key=%h idx=%0d exp=%0d hit=%b exp=%b", key, idx, exp_idx, hit, exp_hit);
                errors = errors + 1;
            end
        end
        if (errors == 0) $display("TEST PASSED");
        else $display("TEST FAILED: %0d errors", errors);
        $finish;
    end
endmodule
