"""Design specification loading (benchmarks/<name>/spec.json)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DesignSpec:
    name: str
    top: str
    files: list[Path]
    clock_period: float
    testbench: Optional[Path] = None
    description: str = ""
    root: Path = field(default_factory=Path)

    @classmethod
    def load(cls, spec_path: str | Path) -> "DesignSpec":
        p = Path(spec_path)
        if p.is_dir():
            p = p / "spec.json"
        data = json.loads(p.read_text())
        root = p.parent
        return cls(
            name=data["name"],
            top=data["top"],
            files=[root / f for f in data["files"]],
            clock_period=float(data["clock_period"]),
            testbench=(root / data["testbench"]) if data.get("testbench") else None,
            description=data.get("description", ""),
            root=root,
        )

    def rtl_text(self) -> str:
        return "\n".join(f.read_text() for f in self.files)
