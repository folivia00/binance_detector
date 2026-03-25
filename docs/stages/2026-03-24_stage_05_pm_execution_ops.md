# Stage 05 PM Execution And Ops

## Scope

Этот этап закрывает оставшийся execution/ops scaffold по roadmap:

- `M9` real PM market data + paper execution;
- `M10` broker hardening state machine;
- `M11` live canary runner;
- `M12` redeem-service separation;
- `M13` production observability baseline.

## Added Elements

### Polymarket Public Data

- public Gamma/CLOB client: [client.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/connectors/polymarket/client.py)

### Paper Execution

- paper execution engine: [paper.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/execution/paper.py)

### Broker Hardening

- order-status normalization and pending/replenish logic: [broker.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/execution/broker.py)

### Canary

- minimal canary entrypoint: [run_live_canary.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/run_live_canary.py)

### Redeem Separation

- resolved-market scanner: [redeem.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/services/redeem.py)
- service entrypoint: [run_redeem_service.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/run_redeem_service.py)

### Observability

- observability state model: [state.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/src/binance_detector/observability/state.py)
- local debug server: [run_observability_server.py](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/scripts/run_observability_server.py)

## Current Reality

- PM quotes уже можно тянуть с публичного order book;
- paper execution уже умеет оценивать taker/passive feasibility и block reasons;
- broker hardening пока локальный state machine, без настоящего live order placement;
- redeem flow отделён от trading loop, но реальный onchain redemption ещё не реализован;
- observability пока файловая + локальный HTTP JSON server, без внешнего metrics stack.

## Next Step

Следующий практический шаг — связать canary loop и observability server в длительный процесс и начать смотреть на последовательные round summaries по живым snapshot-данным.
