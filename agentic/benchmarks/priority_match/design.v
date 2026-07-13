// priority_match: 8-entry pattern matcher with priority resolution.
// Baseline style: each entry does a masked wide compare, and the winner is
// picked by a serial nested-ternary priority cascade whose comparisons sit
// in series — inviting parallel one-hot matching plus a shallow encoder.
module priority_match (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [31:0] key,
    input  wire [31:0] pat0, input wire [31:0] mask0,
    input  wire [31:0] pat1, input wire [31:0] mask1,
    input  wire [31:0] pat2, input wire [31:0] mask2,
    input  wire [31:0] pat3, input wire [31:0] mask3,
    input  wire [31:0] pat4, input wire [31:0] mask4,
    input  wire [31:0] pat5, input wire [31:0] mask5,
    input  wire [31:0] pat6, input wire [31:0] mask6,
    input  wire [31:0] pat7, input wire [31:0] mask7,
    output reg  [2:0]  idx,
    output reg         hit
);
    wire [2:0] pick =
        ((key & mask0) == (pat0 & mask0)) ? 3'd0 :
        ((key & mask1) == (pat1 & mask1)) ? 3'd1 :
        ((key & mask2) == (pat2 & mask2)) ? 3'd2 :
        ((key & mask3) == (pat3 & mask3)) ? 3'd3 :
        ((key & mask4) == (pat4 & mask4)) ? 3'd4 :
        ((key & mask5) == (pat5 & mask5)) ? 3'd5 :
        ((key & mask6) == (pat6 & mask6)) ? 3'd6 :
                                            3'd7;
    wire any =
        ((key & mask0) == (pat0 & mask0)) |
        ((key & mask1) == (pat1 & mask1)) |
        ((key & mask2) == (pat2 & mask2)) |
        ((key & mask3) == (pat3 & mask3)) |
        ((key & mask4) == (pat4 & mask4)) |
        ((key & mask5) == (pat5 & mask5)) |
        ((key & mask6) == (pat6 & mask6)) |
        ((key & mask7) == (pat7 & mask7));

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            idx <= 3'd0;
            hit <= 1'b0;
        end else begin
            idx <= pick;
            hit <= any;
        end
    end
endmodule
