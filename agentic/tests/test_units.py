"""Fast unit tests (no LLM, minimal yosys).

Run:  python3 tests/test_units.py   (from the agentic/ directory)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rtlagent.eda.metrics import PPAResult, composite_score  # noqa: E402
from rtlagent.harness.skills import SkillMemory  # noqa: E402
from rtlagent.llm import create_backend, extract_json, extract_verilog  # noqa: E402

FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILURES.append(msg)
        print("FAIL:", msg)
    else:
        print("ok:  ", msg)


def test_scoring() -> None:
    base = PPAResult(ok=True, wns=-0.45, tns=-12.3, area=12000)
    # Improvement: less-negative WNS/TNS, tiny area growth (Dr.RTL example).
    cand = PPAResult(ok=True, wns=-0.32, tns=-7.5, area=12200)
    s = composite_score(cand, base)
    check(s.total < 0, "improved candidate scores negative")
    check(abs(s.wns_norm - (0.32 - 0.45) / 0.45) < 1e-6, "WNS_norm matches Dr.RTL formula")
    check(s.penalty == 0, "no area penalty under 10% growth")

    bloated = PPAResult(ok=True, wns=-0.32, tns=-7.5, area=14000)
    s2 = composite_score(bloated, base)
    check(s2.penalty == 0.5, "0.5 penalty when area grows >10%")

    worse = PPAResult(ok=True, wns=-0.60, tns=-16.0, area=12000)
    check(composite_score(worse, base).total > 0, "regressed candidate scores positive")
    check(composite_score(cand, base, verified=False).total > 5, "unverified candidates penalized")


def test_extractors() -> None:
    v = extract_verilog("blah\n```verilog\nmodule m(input a, output y);\nassign y=a;\nendmodule\n```\n")
    check(v is not None and "module m" in v, "verilog extraction from fence")
    v2 = extract_verilog("module top(); endmodule some trailing text")
    check(v2 is not None and v2.strip().endswith("endmodule"), "bare module extraction")
    check(extract_verilog("no code here") is None, "no false verilog extraction")
    check(extract_json('x {"a": [1,2]} y') == {"a": [1, 2]}, "brace-span json extraction")


def test_skills() -> None:
    with tempfile.TemporaryDirectory() as td:
        mem = SkillMemory(Path(td) / "s.json")
        check(len(mem.skills) >= 6, "starter skills seeded")
        mem.record_outcome("balance-operator-tree", True)
        mem.record_outcome("balance-operator-tree", False)
        s = mem.skills["balance-operator-tree"]
        check(s.attempts == 2 and s.successes == 1, "skill stats updated")
        mem.record_failed_transform("d1", "bad transform xyz")
        check("bad transform xyz" in mem.render_anti_patterns("d1"), "failed transform remembered")
        mem2 = SkillMemory(Path(td) / "s.json")
        check(mem2.skills["balance-operator-tree"].attempts == 2, "skill memory persists")


def test_backend_registry() -> None:
    b = create_backend("mock:")
    r = b.chat("hello")
    check(r.text != "", "mock backend replies")
    try:
        create_backend("bogus:model")
        check(False, "bogus provider rejected")
    except ValueError:
        check(True, "bogus provider rejected")


def main() -> int:
    test_scoring()
    test_extractors()
    test_skills()
    test_backend_registry()
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURES")
        return 1
    print("\nALL UNIT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
