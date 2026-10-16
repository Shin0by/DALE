# DALE

DALE is a local desktop editor that turns Dungeon Alchemist JPG + JSON exports into transparent PNG overlays for multi-floor Foundry VTT maps. Keep the ground-level map intact, remove areas inside or outside wall contours, close gaps with temporary editor lines, and clean up with an eraser brush. Development is directed through chat, with English technical documentation and an agent-oriented repository index.

DALE — локальный редактор, который превращает экспорт Dungeon Alchemist (JPG + JSON) в прозрачные PNG для многоэтажных карт Foundry VTT. Полная карта остаётся на уровне земли, а верхние этажи очищаются по контурам стен и кистью. Разработкой можно управлять через чат; техническая документация ведётся на английском.

## Development status

Initial prototype. Real Dungeon Alchemist sample validation and verification in the owner's Foundry installation are pending. The initial workflow uses wall geometry and manual cleanup; semantic terrain recognition is not implemented.

Implemented: wall overlays, temporary snapped polyline closures, inside/outside masking, erase/restore brushes, undo/redo, right-button drag panning in every tool, Foundry 13/14 selection, and a floor-elevation dropdown with 5-ft presets and custom integer feet. PNG metadata retains elevation intent; placement in Foundry is still configured separately.

## Run on Windows

Requires 64-bit Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m dale
```

Generate an optional synthetic demonstration (not a Dungeon Alchemist export):

```powershell
.\.venv\Scripts\python.exe tools/create_demo.py
```

Open the generated `artifacts/demo/demo.jpg` and `demo.json` in the editor. See [the workflow](docs/workflow.md) for editing controls and [requirements](docs/requirements.md) for scope and acceptance criteria.

## Map dimensions

Foundry has no single fixed map size. Image limits depend on each participant's GPU/browser; its documentation describes approximately 8,000 pixels per side on older hardware and 16,000 on newer hardware. DALE targets up to **16,384 × 16,384 pixels**, warns above **8,192** on either side, and preserves dimensions without cropping or resizing. This does not guarantee that every Foundry client can load the result. Large PNGs also take more time to distribute. See [research and sources](docs/research.md).

## Repository navigation

Start at [AGENTS.md](AGENTS.md), [project/index.json](project/index.json), and [project/state.json](project/state.json). Technical decisions live in [architecture](docs/architecture.md); canonical names and Russian aliases live in [the glossary](docs/glossary.md). Put private example pairs in [examples/](examples/README.md); they are ignored by Git.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe tools/check_repository.py
```

Offscreen visual review and the optional maximum-size synthetic check:

```powershell
.\.venv\Scripts\python.exe tools/preview_demo.py
.\.venv\Scripts\python.exe tools/verify_large_map.py --size 16384
```

The 16,384-square synthetic export passed locally (about 1.1 GiB peak process memory). This is an image-pipeline check, not a guarantee of Foundry-client compatibility.

GitHub Actions runs the standard checks on Windows. The large-map check is opt-in and is not run on every push.
