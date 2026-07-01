"""rtlagent command-line interface.

    python -m rtlagent.cli synth    benchmarks/add_chain
    python -m rtlagent.cli proxy    benchmarks/add_chain
    python -m rtlagent.cli optimize benchmarks/add_chain --harness agentic \\
        --backend glm:glm-5.2 --rounds 6
    python -m rtlagent.cli eval     benchmarks/* --backend anthropic:claude-sonnet-5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .eda import synthesize
from .harness import DesignSpec, DrRTLBaseline, HarnessConfig, RTLFlowAgent
from .llm import create_backend, default_backend_spec


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("design", help="benchmark directory (contains spec.json)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rtlagent")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_synth = sub.add_parser("synth", help="synthesize and print the PPA/timing report")
    _add_common(p_synth)
    p_synth.add_argument("--paths", type=int, default=5)

    p_proxy = sub.add_parser("proxy", help="run the MasterRTL-style SOG proxy")
    _add_common(p_proxy)

    p_opt = sub.add_parser("optimize", help="run an optimization harness on a design")
    _add_common(p_opt)
    p_opt.add_argument("--harness", choices=["baseline", "agentic"], default="agentic")
    p_opt.add_argument("--backend", default=None, help="e.g. anthropic:claude-sonnet-5, glm:glm-5.2, mock:")
    p_opt.add_argument("--rounds", type=int, default=None)
    p_opt.add_argument("--candidates", type=int, default=None)
    p_opt.add_argument("--minors", type=int, default=None)
    p_opt.add_argument("--work", default="runs")

    p_eval = sub.add_parser("eval", help="run baseline vs agentic on designs and compare")
    p_eval.add_argument("designs", nargs="+")
    p_eval.add_argument("--backend", default=None)
    p_eval.add_argument("--rounds", type=int, default=4)
    p_eval.add_argument("--work", default="runs/eval")
    p_eval.add_argument("--json-out", default=None)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if not args.verbose else logging.DEBUG,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.cmd == "synth":
        spec = DesignSpec.load(args.design)
        res = synthesize(spec.files, spec.top, spec.clock_period, max_paths=args.paths)
        print(res.timing_report(max_paths=args.paths))
        return 0 if res.ok else 1

    if args.cmd == "proxy":
        from .proxy import sog_features

        spec = DesignSpec.load(args.design)
        feats = sog_features(spec.files, spec.top, spec.clock_period)
        if feats is None:
            print("SOG extraction failed", file=sys.stderr)
            return 1
        print(feats.render())
        return 0

    if args.cmd == "optimize":
        spec = DesignSpec.load(args.design)
        backend = create_backend(args.backend or default_backend_spec())
        cfg = HarnessConfig()
        if args.rounds:
            cfg.max_major_rounds = args.rounds
        if args.candidates:
            cfg.candidates_per_round = args.candidates
        if args.minors:
            cfg.minors_per_round = args.minors
        cls = DrRTLBaseline if args.harness == "baseline" else RTLFlowAgent
        result = cls(spec, backend, args.work, cfg).run()
        print(result.summary())
        return 0

    if args.cmd == "eval":
        from .eval import run_eval

        rows = run_eval(
            [DesignSpec.load(d) for d in args.designs],
            backend_spec=args.backend or default_backend_spec(),
            rounds=args.rounds,
            work_root=args.work,
        )
        print(rows.render())
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(rows.to_dict(), indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
