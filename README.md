# DALE

DALE is a local desktop editor that extracts separate transparent PNGs from scene images using editable closed contours. Repair imported contours, clean raster alpha, and export all connected regions or selected cells with exact pixel dimensions in filenames.

DALE - локальный редактор для извлечения отдельных прозрачных PNG по замкнутым контурам. Исправляйте контуры, очищайте растр и экспортируйте все объекты или выбранные области с точными размерами в именах файлов. Этажи и свойства стен настраиваются вручную в Foundry.

The application title is **Dungeon Alchemist Levels Export (v.x.xx.xxx)**. Each Windows build automatically advances only the revision; major and minor versions change only on the owner's explicit instruction.

The owner's supplied ICO is used unchanged for application windows and the Windows executable. Both the ICO and original PNG reference are preserved in [application assets](src/dale/assets/README.md).

## Development status

Named datasets: one top Dataset dropdown opens its image and contours together. The36px manager button on its left opens a transactional tree dialog: create empty sets, rename sets/files, delete components, drag Move/Copy with explicit replacement, append JSON contours, and import/export complete datasets between projects. Physical export filenames use the set name; internal native JSON names/paths stay unchanged. Quick JSON/PNG export and project commands remain in File. See [the workflow](docs/workflow.md#manage-named-datasets).


File > Export JSON (Ctrl+Shift+J) exports the active dataset's edited Scene JSON whenever a source JSON exists. You can move, split, add and erase walls while retaining all non-wall bytes, lights, tiles, regions, internal names/paths and opaque wall settings. Without a source JSON it exports DALE contours. Original files stay unchanged. Height filtering controls only visible editing, never export completeness. Regions move as whole independent figures; two numeric alignment toggles use Alt and the highlighted vertex nearest the cursor for both move and paste.

Экспорт JSON сохраняет прочие данные исходной сцены, включая свет, тайлы и регионы. Стены можно изменять, разбивать, добавлять и удалять. В «Областях» две кнопки привязки с Alt работают от подсвеченной вершины, ближайшей к курсору, и сдвигают фигуру целиком.

The current scope is a single-scene contour/raster editor with separate transparent PNG export. Open one image and optional scene JSON, join/close contours, select all connected objects or individual cells, and clean alpha. Every PNG filename includes its exact final pixel dimensions, for example `map-part-001-702x702px.png`; `placement.json` retains coordinates for manual placement. Levels, wall/floor presets, portals and generation of new native Foundry Scene settings remain outside the task. Configure them manually in Foundry. See [ADR-020](docs/architecture.md#adr-020-return-to-a-single-scene-png-contour-editor).

Vertices edits individual vertices and lines. Contours sits between Vertices and Regions. Click toggles one segment, double-click selects a contour connected by shared vertices, and a selection rectangle inverts intersected segments. Move, scale, rotate and copy exact selected lines, including open/disconnected contours, without changing neighbours or raster. Two numeric Alt-only alignment controls share numeric tolerances; their on/off states are independent in Vertices, Contours and Regions and save with each dataset. Regions and PNG export keep standard polygonized cells. The top Main Select all button, immediately left of Clear selection, and Ctrl+A select all current-section elements in the chosen height layer; Ctrl+Shift+A clears selection. Text fields keep ordinary text selection.

File/Edit/About and persistent Recent projects remain. Three top panels: Sections (Vertices/Contours/Regions/Raster), Main (navigation/selection/visibility/Settings) and Dataset (one set selector and manager icon). Right Project and Settings share contextual Information; language switches English/Russian. Local/whole-map directional closure with extension or shortening of free ends, vertex-first snapping, point/line/circle/rectangle tools, region selection/transforms, raster erase/restore, signed Artwork offset and undo/redo preserve source bytes and line ancestry. Exact PNG crops retain every nonzero alpha pixel, including1/255, with minimal2x/bicubic edge smoothing and native RGB/source alpha. Large exact bounds run in a cancellable background worker; contour-only edits reuse raster previews.

Current `.dale` schema7 stores exact source assets/catalog, geometry/property ownership/ancestry, history/redo/settings and immutable mask snapshots. Detached transformed region selections survive archive reopen. No templates/assignments or older-schema migrations. ADR-028 documents NEXT-009 isolation evidence; historical Foundry research is not an application-feature backlog.

Line erasing stops at intersections, including crossings without existing vertices. Point/cut contacts can explicitly connect figures or leave coincident points independent; each tool remembers its answer and reopens it on button right-click. Editing groups persist in .dale, while global Regions/masks/PNG still use all geometry. Consecutive rotation wheel updates share one undo entry.

## Run on Windows

Open **`DALE/DALE.exe`** in the local portable package. Python installation and launch scripts are not required. Copy the **entire `DALE` folder**, including `_internal`, to move the program. `UserData/settings.json` retains language, related-line choice, two input/output folders and optional global numeric tool values. Switch language in the right Settings block; hover over controls for help.

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

Foundry has no single fixed map size. Image limits depend on each participant's GPU/browser; its documentation describes approximately 8,000 pixels per side on older hardware and 16,000 on newer hardware. DALE accepts static scene images up to **16,384 × 16,384 pixels** and warns above **8,192** on either side. Export applies the left Artwork offset, smooths alpha with minimal 2x/bicubic sampling and crops to every nonzero final alpha pixel, clipped to the source image. Source RGB remains at native resolution and `placement.json` records exact coordinates. This is a DALE coordinate manifest, not a Foundry scene import. Large individual objects remain subject to client limits. See [research and sources](docs/research.md).

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

## Git push policy

Push only on a fresh explicit owner request, through the [dale-push skill](skills/dale-push/SKILL.md). The default destination is `origin/development`. Pushing `origin/release` requires an explicit release request and separate confirmation of the prepared commit. Builds, commits and CI fixes never trigger a push.

Configure the repository-local guard in each checkout with `.venv/Scripts/python.exe skills/dale-push/scripts/push.py configure`. The versioned pre-push hook blocks unplanned direct pushes; the skill helper prepares and executes a single authorized attempt. This setup does not push or create remote branches. Global Git settings are unchanged.

Dataset manager > Scene JSON > Add/Replace > select .dale recovers **Current contours (DALE)** from applied project history: Import or Save JSON separately. This snapshot is for DALE; the exact original Scene JSON stays separate. The left Vertices panel has two optional Alt-only numeric toggles with independent screen-pixel tolerances: adjacent right angles (highlighted legs and square joint marker) and contour X/Y alignment (thin dashed guides).

Regions supports **Delete region** through its left eraser button or **Del**. It deletes only selected outlines, retaining interior lines and image pixels, with normal undo/redo.
