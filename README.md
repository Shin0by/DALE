# DALE

DALE is a local desktop editor that turns Dungeon Alchemist JPG + JSON exports into transparent PNG overlays for multi-floor Foundry VTT maps. Keep the ground-level map intact, remove areas inside or outside wall contours, close gaps with temporary editor lines, and clean up with an eraser brush. Development is directed through chat, with English technical documentation and an agent-oriented repository index.

DALE — локальный редактор, который превращает экспорт Dungeon Alchemist (JPG + JSON) в прозрачные PNG для многоэтажных карт Foundry VTT. Полная карта остаётся на уровне земли, а верхние этажи очищаются по контурам стен и кистью. Разработкой можно управлять через чат; техническая документация ведётся на английском.

The application title is **Dungeon Alchemist Levels Export (v.x.xx.xxx)**. Each Windows build automatically advances only the revision; major and minor versions change only on the owner's explicit instruction.

The owner's supplied ICO is used unchanged for application windows and the Windows executable. Both the ICO and original PNG reference are preserved in [application assets](src/dale/assets/README.md).

## Development status

Working prototype. Six real Dungeon Alchemist pairs have been inspected and opened, and one 13,500 × 16,200 source image has passed the PNG pipeline check. Verification in the owner's Foundry installation is pending. The workflow uses wall geometry and manual cleanup; semantic terrain recognition is not implemented. See [the observed export profile](docs/sample-formats.md) for sample findings and current limitations.

Implemented: unframed text commands in the first top row; tool-set selection, Hand, Fit, and Walls in the second. The left tool column contains separate line/vertex eraser buttons, each 1.5 times normal height, with an independent editable size caption and small gray side arrows under its icon. Pixel size and Snapping (px) use dedicated tiles. The Photoshop-inspired dark-gray UI has localized help for every control, a single-row footer, and a 1024 x 768 minimum window. Editing includes cyan closed/pure-red open contours with 3-pixel black-edged strokes, draggable vertices, new lines, directional Auto-close with independent distance and white hover edges, vertex-first snapping, geometry and pixel erasers, Ctrl+wheel sizing, gap joining, signed offsets, masking, undo/redo, and right-drag pan. Save complete `.dale` projects and export selected or all separate PNGs with 3-pixel guards. The footer shows dimensions, closed/open counts, region selection, and language. Foundry 13/14 selection is remembered between launches; integer-foot height retains placement intent. Configure placement separately in Foundry.

## Run on Windows

Open **`DALE/DALE.exe`** in the local portable package. Python installation and launch scripts are not required. Copy the **entire `DALE` folder**, including `_internal`, to move the program. `UserData/settings.json` retains language and selected Foundry version. English and Russian can be switched in the footer; hover over controls for help.

The generated portable folder is ignored by Git. Repository updates must rebuild it using the command below. Build provenance is recorded in `DALE/build-info.json`; refresh preserves `UserData` and user projects. See [portable startup notes](docs/portable-start.txt) and [the workflow](docs/workflow.md).

## Development and packaging

The implementation uses Python 3.11+, native Qt widgets via PySide6, Pillow, and Shapely. This Python environment is for development only:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m dale
```

After project changes, run checks, then refresh the complete portable package:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.lock
powershell -NoProfile -ExecutionPolicy Bypass -File tools/build_windows.ps1
```

Packaging uses PyInstaller's directory bundle, including the Python runtime and native libraries. An optional `-Mode onefile` build is a separate artifact; the maintained user delivery is `DALE/`. `tools/run_development.cmd` is a development convenience only.

`tools/build_windows.ps1` first runs `tools/bump_revision.py`, synchronizing the new revision in the package, `pyproject.toml`, and project state before packaging. Keep these generated version updates in the source commit. Version display pads minor to two digits and revision to three; revision never automatically rolls over major/minor.

Generate an optional synthetic demonstration (not a Dungeon Alchemist export):

```powershell
.\.venv\Scripts\python.exe tools/create_demo.py
```

Open the generated `artifacts/demo/demo.jpg` and `demo.json` in the editor. See [the workflow](docs/workflow.md) for editing controls and [requirements](docs/requirements.md) for scope and acceptance criteria.

## Map dimensions

Foundry has no single fixed map size. Image limits depend on each participant's GPU/browser; its documentation describes approximately 8,000 pixels per side on older hardware and 16,000 on newer hardware. DALE accepts JPGs up to **16,384 × 16,384 pixels** and warns above **8,192** on either side. Export crops each closed object with a 3-pixel guard, preserving native pixel resolution and recording placement in `placement.json`. This is a DALE coordinate manifest, not a Foundry scene import. Large individual objects remain subject to client limits. See [research and sources](docs/research.md).

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
