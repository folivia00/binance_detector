from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(slots=True)
class TierCalibrationConfig:
    version: str = "default"
    medium_min_edge: float = 0.05
    strong_min_edge: float = 0.12
    very_strong_min_edge: float = 0.20
    very_strong_cap_enabled: bool = False
    very_strong_cap_edge: float = 0.45

    @classmethod
    def from_json(cls, path: Path) -> "TierCalibrationConfig":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(**payload)
