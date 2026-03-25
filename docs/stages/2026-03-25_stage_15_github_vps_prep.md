# Stage 15 GitHub And VPS Prep

## Scope

Этот этап подготавливает проект к нормальной публикации в GitHub и дальнейшему запуску на VPS.

До этого проект жил как рабочая директория внутри более широкого git-root, что неудобно и опасно:

- `git status` тянул посторонние файлы из `C:\Users\Lardio`;
- не было локального `.gitignore` для project-specific артефактов;
- generated logs и reports могли случайно попасть в историю;
- не было отдельного quickstart под Linux/VPS.

## Added

### Git hygiene

Добавлен локальный:

- [.gitignore](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/.gitignore)

Он исключает:

- `.env`
- виртуальные окружения
- `__pycache__`
- generated `json/jsonl/csv`
- raw live captures
- generated markdown reports
- локальные model artifacts

При этом stage-доки в `docs/stages/` остаются versioned.

### Simple install path for VPS

Добавлен:

- [requirements.txt](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/requirements.txt)

Он использует editable install:

- `-e .`

Это даёт простой VPS flow через `pip install -r ./requirements.txt`.

### VPS quickstart

Добавлен:

- [VPS_QUICKSTART.md](c:/Users/Lardio/Desktop/wall_signal_bot/binance_detector/docs/VPS_QUICKSTART.md)

В нём описаны:

- clone;
- venv setup;
- install;
- unit tests;
- live paper loop;
- report generation;
- observability server.

## Result

После этого этапа проект уже можно без грязного окружения оформлять как отдельный GitHub repository и затем клонировать на VPS.

## Next Step

Следующий практический шаг:

1. инициализировать отдельный git repo в корне `binance_detector`;
2. сделать первый clean commit;
3. привязать нужный GitHub remote;
4. push и потом clone на VPS.
