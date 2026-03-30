---
name: commit
description: >
  Use this skill whenever the user wants to commit, save, or push changes in this project.
  Trigger on: "закоммить", "сохрани изменения", "commit", "запушь", "push", "сделай коммит",
  "добавь в git", "зафиксируй", "cherry-pick на main", or any request to save/record work.

  This project has TWO branches with strict rules:
  - `dev` = development branch: commits everything (code + docs/stages/ + scripts)
  - `main` = VPS/production: only runnable code, NO docs/stages/

  Always use this skill for any git commit operation to avoid committing the wrong
  files to the wrong branch.
---

# Project Commit Skill

## Branch rules (read first)

| branch | what it holds | what to NEVER commit here |
|--------|--------------|--------------------------|
| `dev` | src/, scripts/, configs/, docs/stages/, docs/roadmap/, CLAUDE.md, *_Lardio.md | data/logs/, docs/reports/, .venv/, __pycache__ |
| `main` | src/, scripts/, configs/, requirements*.txt, docs/README.md, docs/VPS_QUICKSTART.md | docs/stages/, *_Lardio.md, docs/roadmap/, .claude/, skills-lock.json |

Always gitignored on BOTH branches (never commit):
- `data/logs/*.jsonl` — live data, transferred via scp
- `docs/reports/*.md` — auto-generated reports
- `__pycache__/`, `.venv/`, `*.pyc`

## Step 1 — Detect context

Run these in parallel:
```bash
git branch --show-current
git status --short
git log --oneline -3
```

Read the output carefully:
- What branch are we on?
- What files are changed/untracked?
- What was the last commit message (to maintain style)?

## Step 2 — Classify changes

Group detected changes into categories:
- **code**: src/, scripts/*.py, configs/
- **stage_docs**: docs/stages/*.md, *_Lardio.md
- **roadmap**: docs/roadmap/
- **project_meta**: CLAUDE.md, requirements*.txt, .gitignore, README.md
- **reports** (gitignored — skip): docs/reports/*.md
- **data** (gitignored — skip): data/logs/

Tell the user what you found: "Вижу изменения в: [список категорий]"

## Step 3 — Execute based on branch

### If on `dev`

Stage ALL relevant files (excluding always-ignored ones):
```bash
git add src/ scripts/ configs/ docs/stages/ docs/roadmap/ CLAUDE.md requirements*.txt .gitignore
# add any specific new files that are untracked
git add <specific untracked files>
```

Do NOT run `git add -A` or `git add .` — too broad, can catch ignored files by accident.

Check staged result: `git status --short`

Build commit message (see format below), commit, then ask:
> "Закоммичено на dev. Хочешь запушить на origin dev? И нужно ли cherry-pick на main?"

### If on `main`

Stage ONLY code files:
```bash
git add src/ scripts/ configs/ requirements*.txt
# NEVER add docs/stages/ on main
```

Verify with `git status --short` before committing that no docs/stages/ or Lardio files slipped in.

After commit, ask:
> "Закоммичено на main. Хочешь запушить на origin main?"

### Cherry-pick workflow (dev → main)

When user confirms cherry-pick:
1. Get the commit hash just made on dev: `git log --oneline -1`
2. `git checkout main`
3. `git cherry-pick <hash>`
4. Verify no docs/stages files got through: `git show --name-only HEAD | grep docs/stages` — if any appear, warn the user
5. Offer to push: `git push origin main`
6. Return to dev: `git checkout dev`

## Commit message format

```
<type>: <short description>

- bullet: what changed and why
- bullet: another change

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

**Types:** `stage NN` (analysis stage), `feat` (new feature), `fix` (bug fix), `chore` (cleanup/config), `docs` (documentation only)

**Examples:**

Stage doc commit on dev:
```
stage 21: 500-round revalidation results

- добавлен stage doc с результатами сравнения двух прогонов
- roadmap перемещён в docs/roadmap/

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

Code change cherry-picked to main:
```
feat: add pm_entry_price logging + DNS retry guard

- domain/signals.py: новое поле pm_entry_price в TradingSignal
- run_live_paper_loop.py: try/except вокруг evaluate_once (30s backoff)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

Always use heredoc to avoid shell quoting issues:
```bash
git commit -m "$(cat <<'EOF'
type: description

- bullet 1
- bullet 2

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

## Push

After committing, always offer push explicitly. Use:
```bash
git push origin <branch>
```

Never force-push without explicit user confirmation.

## What to report back

After the full operation, summarise in one short block:
```
✓ dev: <commit hash> "<message>"
✓ push origin dev
✓ main: cherry-picked <hash>
✓ push origin main
```
Only include lines for actions that actually happened.
