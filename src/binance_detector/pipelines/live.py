from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from binance_detector.config.market_registry import PolymarketMarketSpec, get_market_spec
from binance_detector.config.settings import settings
from binance_detector.connectors.binance.client import BinanceClient
from binance_detector.connectors.polymarket.client import PolymarketClient
from binance_detector.domain.market import SettleReference
from binance_detector.domain.signals import TradingSignal
from binance_detector.execution.paper import PaperExecutionConfig, PaperExecutionEngine
from binance_detector.features.state import build_round_features
from binance_detector.models.baseline import BaselineProbabilityModel
from binance_detector.rounds.manager import CanonicalRoundManager
from binance_detector.signals.detectors import compute_detector_state
from binance_detector.strategy.entry_policy import EntryPolicy
from binance_detector.strategy.guards import BasisGuardConfig, evaluate_entry_guards


@dataclass(slots=True)
class LivePaperRunner:
    symbol: str = settings.symbol
    market_key: str = "btc_updown_5m"
    allow_demo_fallback: bool = True
    market_spec: PolymarketMarketSpec | None = field(default=None, init=False)
    binance: BinanceClient | None = field(default=None, init=False)
    polymarket: PolymarketClient | None = field(default=None, init=False)
    model: BaselineProbabilityModel | None = field(default=None, init=False)
    round_manager: CanonicalRoundManager | None = field(default=None, init=False)
    policy: EntryPolicy | None = field(default=None, init=False)
    guard_config: BasisGuardConfig | None = field(default=None, init=False)
    paper_engine: PaperExecutionEngine | None = field(default=None, init=False)
    _previous_snapshot: object | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.market_spec = get_market_spec(settings.pm_market_registry_path, self.market_key)
        if self.market_spec is None:
            raise ValueError(f"market_key not found in registry: {self.market_key}")
        self.binance = BinanceClient(symbol=self.symbol)
        self.polymarket = PolymarketClient(market_slug=self.market_spec.market_slug or self.market_key)
        self.model = BaselineProbabilityModel()
        self.round_manager = CanonicalRoundManager()
        self.policy = EntryPolicy.from_json(settings.entry_policy_path)
        self.guard_config = BasisGuardConfig.from_json(settings.basis_guards_path)
        self.paper_engine = PaperExecutionEngine(PaperExecutionConfig.from_json(settings.paper_execution_path))
        self._previous_snapshot = None

    def evaluate_once(self) -> TradingSignal | None:
        now_ts = datetime.now(timezone.utc)
        with ThreadPoolExecutor(max_workers=2) as executor:
            f_snap = executor.submit(
                self.binance.fetch_signal_snapshot,
                allow_demo_fallback=self.allow_demo_fallback,
            )
            f_quote = executor.submit(
                self.polymarket.get_quote_for_spec_at,
                self.market_spec,
                now_ts,
            )
            snapshot = f_snap.result()
            quote = f_quote.result()

        if snapshot.snapshot_source != "live":
            round_id = self.round_manager.canonical_round_id(
                ts=snapshot.ts,
                market_slug=self.market_spec.market_key,
            )
            return TradingSignal(
                action="NO",
                confidence=0.0,
                reason=f"snapshot_source_demo; fallback={snapshot.fallback_reason}",
                round_id=round_id,
                signal_tier="weak",
                time_bucket="",
                distance_bucket="",
                snapshot_source=snapshot.snapshot_source,
                fallback_reason=snapshot.fallback_reason,
                policy_reason="demo_fallback_skip",
                guard_reasons=tuple(),
                paper_reasons=tuple(),
                should_enter=False,
                market_price=snapshot.market_price,
                round_open_price=0.0,
                basis_bps=0.0,
                pm_quote_age_seconds=0.0,
                pm_book_liquidity=0.0,
                pm_spread_bps=0.0,
                expected_slippage_bps=0.0,
                raw_score=0.0,
                probability_edge=0.0,
                calibration_version=self.model.tier_calibration.version,
            )

        current_round = self.round_manager.track(
            market_slug=self.market_spec.market_key,
            ts=snapshot.ts,
            current_market_price=snapshot.market_price,
        )
        detector_state = compute_detector_state(snapshot, self._previous_snapshot)
        self._previous_snapshot = snapshot
        features = build_round_features(
            round_state=current_round,
            snapshot=snapshot,
            detector_state=detector_state,
        )
        prediction = self.model.predict(features=features, round_id=current_round.round_id)
        action = "YES" if prediction.p_up_total >= 0.5 else "NO"
        confidence = prediction.p_up_total if action == "YES" else prediction.p_down_total
        guard_decision = evaluate_entry_guards(
            current_market_price=snapshot.market_price,
            settle_reference=SettleReference(price=snapshot.market_price, age_seconds=0.0),
            pm_quote=quote,
            time_left_seconds=features.time_left_seconds,
            side=action,
            config=self.guard_config,
        )
        policy_decision = self.policy.evaluate(
            time_bucket=features.time_left_bucket,
            distance_bucket=features.distance_bucket,
            signal_tier=prediction.signal_tier,
        )
        paper_decision = self.paper_engine.evaluate_entry(
            side=action,
            confidence=confidence,
            quote=quote,
            time_left_seconds=features.time_left_seconds,
        )
        guard_reasons = tuple(guard_decision.block_reasons)
        paper_reasons = tuple(paper_decision.block_reasons)
        should_enter = policy_decision.allowed and guard_decision.allowed and paper_decision.allowed
        return TradingSignal(
            action=action,
            confidence=confidence,
            reason=(
                f"tier={prediction.signal_tier}; policy={policy_decision.reason}; "
                f"guards={'ok' if guard_decision.allowed else ','.join(guard_reasons)}; "
                f"paper={'ok' if paper_decision.allowed else ','.join(paper_reasons)}; "
                f"snapshot_source={snapshot.snapshot_source}"
            ),
            round_id=current_round.round_id,
            signal_tier=prediction.signal_tier,
            time_bucket=features.time_left_bucket,
            distance_bucket=features.distance_bucket,
            snapshot_source=snapshot.snapshot_source,
            fallback_reason=snapshot.fallback_reason,
            policy_reason=policy_decision.reason,
            guard_reasons=guard_reasons,
            paper_reasons=paper_reasons,
            should_enter=should_enter,
            market_price=snapshot.market_price,
            round_open_price=current_round.round_open_price,
            basis_bps=guard_decision.basis_bps,
            pm_quote_age_seconds=quote.quote_age_seconds,
            pm_book_liquidity=quote.book_liquidity,
            pm_spread_bps=quote.spread_bps(action),
            expected_slippage_bps=paper_decision.expected_slippage_bps,
            pm_entry_price=quote.ask_price(action),
            raw_score=float(prediction.debug_components.get("raw_score", 0.0)),
            probability_edge=prediction.probability_edge,
            calibration_version=prediction.calibration_version,
        )

    def current_market_spec(self) -> PolymarketMarketSpec:
        return self.market_spec


def run_live_round(symbol: str, market_slug: str) -> TradingSignal | None:
    market_key = market_slug if get_market_spec(settings.pm_market_registry_path, market_slug) else "btc_updown_5m"
    runner = LivePaperRunner(symbol=symbol, market_key=market_key)
    return runner.evaluate_once()
