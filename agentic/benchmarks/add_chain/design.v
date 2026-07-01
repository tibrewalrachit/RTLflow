// add_chain: sums 8 input operands into an accumulator each cycle.
// Baseline implementation uses a serial ripple chain of adders, creating a
// long critical path — a classic target for tree-restructuring optimization.
module add_chain (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        en,
    input  wire [15:0] in0,
    input  wire [15:0] in1,
    input  wire [15:0] in2,
    input  wire [15:0] in3,
    input  wire [15:0] in4,
    input  wire [15:0] in5,
    input  wire [15:0] in6,
    input  wire [15:0] in7,
    output reg  [19:0] acc
);
    wire [19:0] s0 = {4'b0, in0};
    wire [19:0] s1 = s0 + {4'b0, in1};
    wire [19:0] s2 = s1 + {4'b0, in2};
    wire [19:0] s3 = s2 + {4'b0, in3};
    wire [19:0] s4 = s3 + {4'b0, in4};
    wire [19:0] s5 = s4 + {4'b0, in5};
    wire [19:0] s6 = s5 + {4'b0, in6};
    wire [19:0] s7 = s6 + {4'b0, in7};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            acc <= 20'd0;
        else if (en)
            acc <= acc + s7;
    end
endmodule
