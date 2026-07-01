"""End-to-end harness test with a scripted mock LLM (no API key, no network).

The mock plays an optimizer that knows one real trick: rebalancing
add_chain's serial adder chain into a tree.  The test asserts the improved
harness finds, verifies and promotes it, and that the Dr.RTL baseline loop
terminates cleanly when its optimizer produces no improvement.

Run:  python3 tests/test_e2e_mock.py   (from the agentic/ directory)
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rtlagent.harness import DesignSpec, DrRTLBaseline, HarnessConfig, RTLFlowAgent  # noqa: E402
from rtlagent.llm.mock_backend import MockBackend  # noqa: E402

BENCH = Path(__file__).parent.parent / "benchmarks" / "add_chain"

BALANCED_RTL = """\
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
    wire [19:0] t01 = {4'b0, in0} + {4'b0, in1};
    wire [19:0] t23 = {4'b0, in2} + {4'b0, in3};
    wire [19:0] t45 = {4'b0, in4} + {4'b0, in5};
    wire [19:0] t67 = {4'b0, in6} + {4'b0, in7};
    wire [19:0] q0  = t01 + t23;
    wire [19:0] q1  = t45 + t67;
    wire [19:0] s7  = q0 + q1;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            acc <= 20'd0;
        else if (en)
            acc <= acc + s7;
    end
endmodule
"""

ANALYSIS_JSON = """{
  "bottlenecks": [{
    "where": "s0..s7 serial adder chain feeding acc",
    "root_cause": "8-deep serial ripple of 20-bit adders",
    "amenability": "high",
    "suggested_transforms": ["balance-operator-tree"]
  }],
  "summary": "The accumulate path chains eight adders serially; a balanced tree cuts depth to log2(8)+1 adds."
}"""


def dispatch(prompt: str) -> str:
    if "Analyze the worst paths" in prompt:
        return ANALYSIS_JSON
    if "Your assignment for this attempt" in prompt:
        if "most applicable known skill" in prompt:
            return ("TRANSFORM: balance-operator-tree: rebuilt the 8-input serial adder chain "
                    "as a balanced binary tree\n```verilog\n" + BALANCED_RTL + "```\n")
        return "I found no safe additional transform.\n"  # no RTL -> dropped
    if "Extract at most 2" in prompt:
        return '{"skills": []}'
    return '{"analysis": "n/a"}'


def main() -> int:
    spec = DesignSpec.load(BENCH)
    work = Path(tempfile.mkdtemp(prefix="rtlagent_test_"))
    failures = []

    # --- improved harness must find, verify, promote the tree rewrite -----
    cfg = HarnessConfig(max_major_rounds=2, candidates_per_round=3, proxy_keep=2,
                        no_improvement_patience=0, sim_cycles=500, sec_timeout=240)
    agent = RTLFlowAgent(spec, MockBackend([dispatch] * 60), work, cfg)
    res = agent.run()
    print(res.summary())
    if res.best.wns <= res.baseline.wns + 0.3:
        failures.append(f"agentic: expected WNS improvement, got {res.baseline.wns:.3f} -> {res.best.wns:.3f}")
    if res.best_version == "v0":
        failures.append("agentic: nothing was promoted")
    if res.best_score >= 0:
        failures.append(f"agentic: score should be negative (improvement), got {res.best_score:+.4f}")

    # --- baseline harness with a no-op optimizer terminates cleanly -------
    cfg_b = HarnessConfig(max_major_rounds=2, minors_per_round=2, sim_cycles=300, sec_timeout=180)
    base = DrRTLBaseline(spec, MockBackend(), work, cfg_b)  # default mock = no-op echo
    res_b = base.run()
    print(res_b.summary())
    if res_b.end_reason != "no_improvement":
        failures.append(f"baseline: expected no_improvement stop, got {res_b.end_reason}")
    if res_b.best_version != "v0":
        failures.append("baseline: no-op optimizer must not be promoted")

    shutil.rmtree(work, ignore_errors=True)
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("\nALL E2E TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
