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

```bash
cp ./.env.example ./.env
```

Fill `.env` only if you later add authenticated execution or private keys.

Current paper/live-paper flows work with public market data.

## 4. Run tests

```bash
PYTHONPATH=./src python -m unittest discover -s ./tests/unit -v
```

## 5. Run a paper loop

```bash
python ./scripts/run_live_paper_loop.py --market-key btc_updown_5m --iterations 1800 --interval-seconds 5
```

## 6. Analyze the run

```bash
python ./scripts/analyze_live_paper_loop.py ./data/logs/<NEW_FILE>.jsonl
```

Or compare with a previous run:

```bash
python ./scripts/analyze_live_paper_loop.py ./data/logs/<NEW_FILE>.jsonl --compare-to ./data/logs/<OLD_FILE>.jsonl
```

## 7. Optional observability server

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
