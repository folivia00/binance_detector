from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path


@dataclass(slots=True)
class EntryPolicyDecision:
    allowed: bool
    reason: str
    allowed_tiers: tuple[str, ...]


@dataclass(slots=True)
class EntryPolicy:
    default_allowed_tiers: tuple[str, ...]
    by_time: dict[str, tuple[str, ...]] = field(default_factory=dict)
    by_distance: dict[str, tuple[str, ...]] = field(default_factory=dict)
    by_time_distance: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: Path) -> "EntryPolicy":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            default_allowed_tiers=tuple(payload.get("default_allowed_tiers", [])),
            by_time={key: tuple(value) for key, value in payload.get("by_time", {}).items()},
            by_distance={key: tuple(value) for key, value in payload.get("by_distance", {}).items()},
            by_time_distance={
                key: tuple(value) for key, value in payload.get("by_time_distance", {}).items()
            },
        )

    def allowed_tiers_for(self, time_bucket: str, distance_bucket: str) -> tuple[str, ...]:
        allowed = self.default_allowed_tiers
        if time_bucket in self.by_time:
            allowed = self.by_time[time_bucket]
        if distance_bucket in self.by_distance:
            allowed = tuple(sorted(set(allowed).intersection(self.by_distance[distance_bucket])))
        composite_key = f"{time_bucket}|{distance_bucket}"
        if composite_key in self.by_time_distance:
            allowed = self.by_time_distance[composite_key]
        return allowed

    def evaluate(self, time_bucket: str, distance_bucket: str, signal_tier: str) -> EntryPolicyDecision:
        allowed_tiers = self.allowed_tiers_for(time_bucket=time_bucket, distance_bucket=distance_bucket)
        if signal_tier in allowed_tiers:
            return EntryPolicyDecision(True, "policy_allowed", allowed_tiers)
        return EntryPolicyDecision(False, f"tier_blocked:{time_bucket}:{distance_bucket}", allowed_tiers)
