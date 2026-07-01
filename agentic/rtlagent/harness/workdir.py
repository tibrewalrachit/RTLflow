"""Versioned run directory, mirroring Dr.RTL's syn_flow layout.

    runs/<design>/
        v0.v, v1.v, ...            promoted major versions
        attempts/v1.3.v            candidate RTL per minor attempt
        attempts/v1.3.json         attempt record (ppa, verify, score)
        history.json               round-by-round record
        skills.json                per-run skill memory snapshot

Unlike Dr.RTL — where the orchestrator LLM does the arithmetic, JSON edits
and file renames in-context — all bookkeeping here is deterministic Python.
"""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path
from typing import Any, Optional

from ..eda.metrics import PPAResult, Score


class WorkDir:
    def __init__(self, root: str | Path, design_name: str):
        self.root = Path(root) / design_name
        self.attempts_dir = self.root / "attempts"
        self.attempts_dir.mkdir(parents=True, exist_ok=True)
        self.history_path = self.root / "history.json"
        self.history: dict[str, Any] = {
            "design": design_name,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            "baseline": None,
            "best_version": "v0",
            "best_ppa": None,
            "end_reason": None,
            "major_rounds": [],
            "llm_usage": {},
        }

    # -- versions -----------------------------------------------------------

    def version_file(self, version: str) -> Path:
        return self.root / f"{version}.v"

    def write_version(self, version: str, rtl: str) -> Path:
        p = self.version_file(version)
        p.write_text(rtl)
        return p

    def write_attempt(self, tag: str, rtl: str) -> Path:
        p = self.attempts_dir / f"{tag}.v"
        p.write_text(rtl)
        return p

    def record_attempt(self, tag: str, record: dict[str, Any]) -> None:
        (self.attempts_dir / f"{tag}.json").write_text(json.dumps(record, indent=2, default=_jsonable))

    # -- history --------------------------------------------------------------

    def set_baseline(self, ppa: PPAResult) -> None:
        self.history["baseline"] = {"wns": ppa.wns, "tns": ppa.tns, "area": ppa.area}
        self.save()

    def add_round(self, round_record: dict[str, Any]) -> None:
        self.history["major_rounds"].append(round_record)
        self.save()

    def finish(self, end_reason: str, best_version: str, best_ppa: Optional[PPAResult], usage: dict) -> None:
        self.history["end_reason"] = end_reason
        self.history["best_version"] = best_version
        if best_ppa:
            self.history["best_ppa"] = {"wns": best_ppa.wns, "tns": best_ppa.tns, "area": best_ppa.area}
        self.history["llm_usage"] = usage
        self.history["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.save()

    def save(self) -> None:
        self.history_path.write_text(json.dumps(self.history, indent=2, default=_jsonable))


def _jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (Score, PPAResult)):
        return dataclasses.asdict(obj)
    return str(obj)
