# DALE

DALE is a local desktop editor that prepares transparent PNG floor overlays from Dungeon Alchemist scene images and Foundry scene JSON. Keep the ground-level scene image intact, extract upper-floor regions with editable contours, and clean the raster with an eraser. Development is directed through chat, with English technical documentation and an agent-oriented repository index.

DALE — локальный редактор для подготовки прозрачных PNG этажей из изображения сцены Dungeon Alchemist и JSON сцены Foundry VTT. Изображение уровня земли остаётся целым, а области верхних этажей выделяются по редактируемым контурам и очищаются ластиком. Разработкой можно управлять через чат; техническая документация ведётся на английском.

The application title is **Dungeon Alchemist Levels Export (v.x.xx.xxx)**. Each Windows build automatically advances only the revision; major and minor versions change only on the owner's explicit instruction.

The owner's supplied ICO is used unchanged for application windows and the Windows executable. Both the ICO and original PNG reference are preserved in [application assets](src/dale/assets/README.md).

## Development status

Working prototype. Six real Dungeon Alchemist pairs have been inspected and opened, and one 13,500 × 16,200 source image has passed the PNG pipeline check. Verification in the owner's Foundry installation is pending. The workflow uses contour geometry and manual cleanup; semantic terrain recognition is not implemented. See [the observed export profile](docs/sample-formats.md) for sample findings and current limitations.

Implemented: three tool sets **Contours / Regions / Raster**, **File / Edit / About** menus, one text-only contextual toolbar, embedded per-tool numeric controls, and right **Project / Settings / Information** blocks at 1024 x 768. Project nests Regions and File information; the global-settings checkbox follows Language. Draw circular contours by dragging a radius: 0.5/1/2 cells use 4/6/8 vertices, then density grows with size. Directional local/whole-map auto-close uses white previews and confirmation; no-op explanations have only Close. Edit points with Alt vector constraint, select minimum cells, and move/scale selected geometry and rotate it with a dedicated plain-wheel tool. Show contours off retains only active selection/highlights. Raster stays fixed. The left Artwork offset adds/cuts actual scene image pixels around contours. PNG alpha receives light bicubic smoothing, and exact crops retain every nonzero alpha pixel, including 1/255, clipped to JPG bounds. There is no fixed 3px guard or global transparent-padding parameter. Current-format `.dale` projects preserve source assets, undo/redo and complete line/contact ancestry. The JSON command loads a scene JSON directly or from a DALE project document list. Language, Foundry 13/14, related-line choice and independent input/output folders persist. All eight numeric values persist in projects or optional global settings: enabling copies current values, project loading retains globals, disabling restores project values. Clear selection follows Hand (Ctrl+Shift+A). Bottom Information lists current gestures and all enabled window shortcuts; action names identify their subject. Configure actual elevation in Foundry. **Older project formats are unsupported.**

The owner-supplied Foundry 13.351 scene has been analyzed: [scene/contour/Region/teleport field atlas](docs/foundry-scene-format.md), [v13/v14 export feasibility](docs/foundry-export-feasibility.md), and [machine-readable profile](project/foundry-format-profile.json). Semantic scene generation remains future work. The additional locked Tile is documented in [Tile format and PNG floor design](docs/foundry-tile-format.md). Large exact PNG information calculations run in the background; unchanged raster previews are reused during contour edits. The reported unwanted line connections during region transforms are tracked separately as NEXT-009.

## Run on Windows

Open **`DALE/DALE.exe`** in the local portable package. Python installation and launch scripts are not required. Copy the **entire `DALE` folder**, including `_internal`, to move the program. `UserData/settings.json` retains language, Foundry version, related-line choice, two input/output folders and optional global numeric tool values. Switch language in the right Settings block; hover over controls for help.

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

Foundry has no single fixed map size. Image limits depend on each participant's GPU/browser; its documentation describes approximately 8,000 pixels per side on older hardware and 16,000 on newer hardware. DALE accepts JPGs up to **16,384 × 16,384 pixels** and warns above **8,192** on either side. Export applies the left Artwork offset, smooths alpha with minimal 2x/bicubic sampling and crops to every nonzero final alpha pixel, clipped to JPG. Source RGB remains at native resolution and `placement.json` records exact coordinates. This is a DALE coordinate manifest, not a Foundry scene import. Large individual objects remain subject to client limits. See [research and sources](docs/research.md).

## Repository navigation

Start at [AGENTS.md](AGENTS.md), [project/index.json](project/index.json), and [project/state.json](project/state.json). Technical decisions live in [architecture](docs/architecture.md); canonical names and Russian aliases live in [the glossary](docs/glossary.md). Current archive/ancestry contracts live in [project format](docs/project-format.md). Put private example pairs in [examples/](examples/README.md); they are ignored by Git.

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
