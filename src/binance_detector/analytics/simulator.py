from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import fmean

from binance_detector.analytics.reverse_exit import ReverseExitRecord, analyze_reverse_exit
from binance_detector.domain.market import BinanceSignalSnapshot, PolymarketQuote, SettleReference
from binance_detector.domain.rounds import RoundResult
from binance_detector.execution.paper import PaperExecutionEngine
from binance_detector.features.state import build_round_features
from binance_detector.models.baseline import BaselineProbabilityModel
from binance_detector.rounds.manager import CanonicalRoundManager
from binance_detector.signals.detectors import compute_detector_state
from binance_detector.strategy.entry_policy import EntryPolicy
from binance_detector.strategy.guards import BasisGuardConfig, evaluate_entry_guards


@dataclass(slots=True)
class SimulationTick:
    ts: datetime
    market_price: float
    best_bid: float
    best_ask: float
    microprice: float
    queue_imbalance: float
    velocity_short: float
    microprice_delta: float
    volatility_recent: float
    settle_reference_price: float
    settle_reference_age_seconds: float
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    pm_book_liquidity: float
    pm_quote_age_seconds: float
    bid_depth_top: float = 0.0
    ask_depth_top: float = 0.0
    bid_wall_change: float = 0.0
    ask_wall_change: float = 0.0
    bid_full_remove: float = 0.0
    ask_full_remove: float = 0.0
    aggressive_buy_flow: float = 0.0
    aggressive_sell_flow: float = 0.0
    rebound_strength: float = 0.0


@dataclass(slots=True)
class SimulationEvent:
    event_type: str
    round_id: str
    ts: datetime
    side: str
    signal_tier: str
    time_bucket: str
    distance_bucket: str
    reason: str
    probability_up: float
    basis_bps: float


@dataclass(slots=True)
class PositionState:
    round_id: str
    side: str
    entry_price: float
    entry_time: datetime
    signal_tier: str
    time_bucket: str
    distance_bucket: str
    reversed: bool = False
    realized_exit_pnl: float | None = None


@dataclass(slots=True)
class RoundSummary:
    round_id: str
    open_price: float
    settle_price: float
    winner: str
    entry_side: str | None
    outcome: str
    pnl: float
    avg_edge_at_entry: float
    time_bucket: str | None
    distance_bucket: str | None
    signal_tier: str | None
    shadow_opportunities: int
    blocked_entries: int
    reverse_exit_saved_loss: float
    reverse_exit_cut_winner: float


@dataclass(slots=True)
class SimulationReport:
    round_summaries: list[RoundSummary] = field(default_factory=list)
    events: list[SimulationEvent] = field(default_factory=list)
    reverse_exit_records: list[ReverseExitRecord] = field(default_factory=list)
    tick_debug_rows: list[dict[str, float | str]] = field(default_factory=list)

    def metrics(self) -> dict[str, float]:
        if not self.round_summaries:
            return {
                "rounds": 0,
                "pnl": 0.0,
                "winrate": 0.0,
                "avg_edge_at_entry": 0.0,
                "avg_late_damage": 0.0,
            }

        with_entries = [summary for summary in self.round_summaries if summary.entry_side is not None]
        late_losses = [
            abs(summary.pnl)
            for summary in with_entries
            if summary.pnl < 0 and summary.time_bucket in {"late", "final"}
        ]
        return {
            "rounds": float(len(self.round_summaries)),
            "pnl": sum(summary.pnl for summary in self.round_summaries),
            "winrate": (
                sum(1 for summary in with_entries if summary.pnl > 0) / len(with_entries)
                if with_entries
                else 0.0
            ),
            "avg_edge_at_entry": (
                fmean(summary.avg_edge_at_entry for summary in with_entries) if with_entries else 0.0
            ),
            "avg_late_damage": fmean(late_losses) if late_losses else 0.0,
        }


class RoundSimulator:
    def __init__(
        self,
        *,
        market_slug: str,
        model: BaselineProbabilityModel,
        policy: EntryPolicy,
        guard_config: BasisGuardConfig,
        paper_engine: PaperExecutionEngine | None = None,
        enable_reverse_exit: bool = True,
    ) -> None:
        self.market_slug = market_slug
        self.model = model
        self.policy = policy
        self.guard_config = guard_config
        self.paper_engine = paper_engine or PaperExecutionEngine()
        self.enable_reverse_exit = enable_reverse_exit
        self.round_manager = CanonicalRoundManager()

    def run(self, ticks: list[SimulationTick]) -> SimulationReport:
        report = SimulationReport()
        current_round_id: str | None = None
        current_position: PositionState | None = None
        blocked_candidates: list[SimulationEvent] = []
        last_tick_for_round: dict[str, SimulationTick] = {}
        entry_edges: dict[str, list[float]] = {}
        previous_snapshot: BinanceSignalSnapshot | None = None

        for tick in sorted(ticks, key=lambda item: item.ts):
            snapshot = BinanceSignalSnapshot(
                ts=tick.ts,
                market_price=tick.market_price,
                best_bid=tick.best_bid,
                best_ask=tick.best_ask,
                microprice=tick.microprice,
                queue_imbalance=tick.queue_imbalance,
                velocity_short=tick.velocity_short,
                microprice_delta=tick.microprice_delta,
                volatility_recent=tick.volatility_recent,
                bid_depth_top=tick.bid_depth_top,
                ask_depth_top=tick.ask_depth_top,
                bid_wall_change=tick.bid_wall_change,
                ask_wall_change=tick.ask_wall_change,
                bid_full_remove=tick.bid_full_remove,
                ask_full_remove=tick.ask_full_remove,
                aggressive_buy_flow=tick.aggressive_buy_flow,
                aggressive_sell_flow=tick.aggressive_sell_flow,
                rebound_strength=tick.rebound_strength,
            )
            pm_quote = PolymarketQuote(
                ts=tick.ts,
                yes_bid=tick.yes_bid,
                yes_ask=tick.yes_ask,
                no_bid=tick.no_bid,
                no_ask=tick.no_ask,
                book_liquidity=tick.pm_book_liquidity,
                quote_age_seconds=tick.pm_quote_age_seconds,
            )
            settle_reference = SettleReference(
                price=tick.settle_reference_price,
                age_seconds=tick.settle_reference_age_seconds,
            )

            round_state = self.round_manager.track(
                market_slug=self.market_slug,
                ts=tick.ts,
                current_market_price=tick.market_price,
            )
            last_tick_for_round[round_state.round_id] = tick

            if current_round_id is not None and round_state.round_id != current_round_id:
                result = self.round_manager.resolve(
                    market_slug=self.market_slug,
                    settle_price=last_tick_for_round[current_round_id].settle_reference_price,
                    resolved_at=last_tick_for_round[current_round_id].ts,
                    resolution_source="settle_reference",
                )
                if result is not None:
                    self._close_round(
                        report=report,
                        result=result,
                        position=current_position if current_position and current_position.round_id == current_round_id else None,
                        blocked_candidates=blocked_candidates,
                        entry_edges=entry_edges.get(current_round_id, []),
                    )
                current_position = None
                blocked_candidates = []

            current_round_id = round_state.round_id
            detector_state = compute_detector_state(snapshot, previous_snapshot)
            previous_snapshot = snapshot
            features = build_round_features(
                round_state=round_state,
                snapshot=snapshot,
                detector_state=detector_state,
            )
            prediction = self.model.predict(features=features, round_id=round_state.round_id)
            report.tick_debug_rows.append(
                {
                    "ts": tick.ts.isoformat(),
                    "round_id": round_state.round_id,
                    "market_price": tick.market_price,
                    "round_open_price": round_state.round_open_price,
                    "distance_to_open_bps": features.distance_to_open_bps,
                    "time_left_bucket": features.time_left_bucket,
                    "distance_bucket": features.distance_bucket,
                    "velocity_short": features.velocity_short,
                    "queue_imbalance": features.queue_imbalance,
                    "microprice_delta": features.microprice_delta,
                    "volatility_recent": features.volatility_recent,
                    **detector_state.debug_columns(),
                    "p_up_total": prediction.p_up_total,
                    "p_down_total": prediction.p_down_total,
                    "signal_tier": prediction.signal_tier,
                }
            )
            side = "YES" if prediction.p_up_total >= 0.5 else "NO"
            edge = abs(prediction.p_up_total - 0.5)
            if edge < 0.05:
                continue

            report.events.append(
                SimulationEvent(
                    event_type="candidate_entry",
                    round_id=round_state.round_id,
                    ts=tick.ts,
                    side=side,
                    signal_tier=prediction.signal_tier,
                    time_bucket=features.time_left_bucket,
                    distance_bucket=features.distance_bucket,
                    reason="candidate",
                    probability_up=prediction.p_up_total,
                    basis_bps=0.0,
                )
            )

            policy_decision = self.policy.evaluate(
                time_bucket=features.time_left_bucket,
                distance_bucket=features.distance_bucket,
                signal_tier=prediction.signal_tier,
            )
            guard_decision = evaluate_entry_guards(
                current_market_price=tick.market_price,
                settle_reference=settle_reference,
                pm_quote=pm_quote,
                time_left_seconds=features.time_left_seconds,
                side=side,
                config=self.guard_config,
            )
            paper_decision = self.paper_engine.evaluate_entry(
                side=side,
                confidence=prediction.p_up_total if side == "YES" else prediction.p_down_total,
                quote=pm_quote,
                time_left_seconds=features.time_left_seconds,
            )

            if current_position is None and policy_decision.allowed and guard_decision.allowed and paper_decision.allowed:
                current_position = PositionState(
                    round_id=round_state.round_id,
                    side=side,
                    entry_price=pm_quote.ask_price(side),
                    entry_time=tick.ts,
                    signal_tier=prediction.signal_tier,
                    time_bucket=features.time_left_bucket,
                    distance_bucket=features.distance_bucket,
                )
                entry_edges.setdefault(round_state.round_id, []).append(edge)
                report.events.append(
                    SimulationEvent(
                        event_type="actual_entry",
                        round_id=round_state.round_id,
                        ts=tick.ts,
                        side=side,
                        signal_tier=prediction.signal_tier,
                        time_bucket=features.time_left_bucket,
                        distance_bucket=features.distance_bucket,
                        reason="entry_filled",
                        probability_up=prediction.p_up_total,
                        basis_bps=guard_decision.basis_bps,
                    )
                )
                continue

            if current_position is None:
                reason = policy_decision.reason
                if not guard_decision.allowed:
                    reason = ",".join(guard_decision.block_reasons)
                elif not paper_decision.allowed:
                    reason = ",".join(paper_decision.block_reasons)
                blocked_event = SimulationEvent(
                    event_type="blocked_entry",
                    round_id=round_state.round_id,
                    ts=tick.ts,
                    side=side,
                    signal_tier=prediction.signal_tier,
                    time_bucket=features.time_left_bucket,
                    distance_bucket=features.distance_bucket,
                    reason=reason,
                    probability_up=prediction.p_up_total,
                    basis_bps=guard_decision.basis_bps,
                )
                blocked_candidates.append(blocked_event)
                report.events.append(blocked_event)
                continue

            if (
                self.enable_reverse_exit
                and current_position.round_id == round_state.round_id
                and side != current_position.side
                and prediction.signal_tier in {"strong", "very_strong"}
                and not current_position.reversed
            ):
                exit_price = pm_quote.bid_price(current_position.side)
                if exit_price > 0:
                    current_position.reversed = True
                    current_position.realized_exit_pnl = exit_price - current_position.entry_price
                    report.events.append(
                        SimulationEvent(
                            event_type="reverse_exit",
                            round_id=round_state.round_id,
                            ts=tick.ts,
                            side=current_position.side,
                            signal_tier=prediction.signal_tier,
                            time_bucket=features.time_left_bucket,
                            distance_bucket=features.distance_bucket,
                            reason="opposite_strong_signal",
                            probability_up=prediction.p_up_total,
                            basis_bps=guard_decision.basis_bps,
                        )
                    )

        if current_round_id is not None and current_round_id in last_tick_for_round:
            result = self.round_manager.resolve(
                market_slug=self.market_slug,
                settle_price=last_tick_for_round[current_round_id].settle_reference_price,
                resolved_at=last_tick_for_round[current_round_id].ts,
                resolution_source="settle_reference",
            )
            if result is not None:
                self._close_round(
                    report=report,
                    result=result,
                    position=current_position if current_position and current_position.round_id == current_round_id else None,
                    blocked_candidates=blocked_candidates,
                    entry_edges=entry_edges.get(current_round_id, []),
                )

        return report

    def _close_round(
        self,
        *,
        report: SimulationReport,
        result: RoundResult,
        position: PositionState | None,
        blocked_candidates: list[SimulationEvent],
        entry_edges: list[float],
    ) -> None:
        winner = result.winner
        shadow_opportunities = sum(1 for event in blocked_candidates if event.side == winner)
        pnl = 0.0
        outcome = "no_entry"
        reverse_exit_saved_loss = 0.0
        reverse_exit_cut_winner = 0.0

        if position is not None:
            settle_payoff = 1.0 if position.side == winner else 0.0
            hold_to_settle_pnl = settle_payoff - position.entry_price
            pnl = hold_to_settle_pnl
            outcome = "win" if pnl > 0 else "loss" if pnl < 0 else "flat"
            if position.reversed and position.realized_exit_pnl is not None:
                pnl = position.realized_exit_pnl
                outcome = "reversed_exit"
                reverse_record = analyze_reverse_exit(
                    round_id=result.round_id,
                    signal_tier=position.signal_tier,
                    time_left_bucket=position.time_bucket,
                    distance_bucket=position.distance_bucket,
                    realized_exit_pnl=position.realized_exit_pnl,
                    hold_to_settle_pnl=hold_to_settle_pnl,
                )
                reverse_exit_saved_loss = reverse_record.saved_loss
                reverse_exit_cut_winner = reverse_record.cut_winner
                report.reverse_exit_records.append(reverse_record)

        report.round_summaries.append(
            RoundSummary(
                round_id=result.round_id,
                open_price=result.open_price,
                settle_price=result.settle_price,
                winner=winner,
                entry_side=position.side if position is not None else None,
                outcome=outcome,
                pnl=pnl,
                avg_edge_at_entry=fmean(entry_edges) if entry_edges else 0.0,
                time_bucket=position.time_bucket if position is not None else None,
                distance_bucket=position.distance_bucket if position is not None else None,
                signal_tier=position.signal_tier if position is not None else None,
                shadow_opportunities=shadow_opportunities,
                blocked_entries=len(blocked_candidates),
                reverse_exit_saved_loss=reverse_exit_saved_loss,
                reverse_exit_cut_winner=reverse_exit_cut_winner,
            )
        )
