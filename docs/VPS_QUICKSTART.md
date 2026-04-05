# VPS Quickstart

## 1. Clone the repository

```bash
git clone <YOUR_GITHUB_REPO_URL>
cd binance_detector
```

## 2. Create virtualenv

```bash
python3 -m venv .venv
source ./.venv/bin/activate
python -m pip install --upgrade pip setuptools
python -m pip install -r ./requirements.txt
```

## 3. Configure environment

Paper loop works without any credentials (public market data only).

For **live trading**, add credentials to `~/.bashrc` (never commit to git):

```bash
# Polymarket wallet (signature_type=2 — no API keys needed)
export PM_PRIVATE_KEY=0x<your_polygon_private_key>
export PM_FUNDER_ADDRESS=0x<your_wallet_address>
export PM_SIGNATURE_TYPE=2
```

Then reload: `source ~/.bashrc`

Verify connection before first trade:
```bash
python scripts/setup_pm_api_key.py
```

## 4. Run tests

```bash
PYTHONPATH=./src python -m unittest discover -s ./tests/unit -v
```

## 5. Run a paper loop (no credentials needed)

```bash
python ./scripts/run_live_paper_loop.py --market-key btc_updown_5m --iterations 1800 --interval-seconds 5
```

## 6. Run live trading loop

Dry run first (checks everything, no real orders):
```bash
python scripts/run_live_loop.py --market-key btc_updown_5m --iterations 360
```

Enable real orders (requires PM env vars from step 3):
```bash
python scripts/run_live_loop.py --market-key btc_updown_5m --iterations 1800 --live
```

Or set `dry_run: false` in `configs/live_execution_v1.json` and run without `--live`.

## 7. Analyze the run

```bash
python ./scripts/analyze_live_paper_loop.py ./data/logs/<NEW_FILE>.jsonl
```

Or compare with a previous run:

```bash
python ./scripts/analyze_live_paper_loop.py ./data/logs/<NEW_FILE>.jsonl --compare-to ./data/logs/<OLD_FILE>.jsonl
```

## 8. Optional observability server

```bash
python ./scripts/run_observability_server.py
```

Useful endpoints:

- `/health`
- `/heartbeat`
- `/summary/latest`
- `/debug/state`
- `/debug/events`
- `/sse/state`

## Notes

- Generated logs and reports are ignored by git.
- Stage docs in `./docs/stages/` stay in the repository.
- For long VPS runs prefer `tmux` or `screen`.
