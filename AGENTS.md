# Agent entry point

## Working agreement
- Communicate with the owner in Russian. Write code, identifiers, comments, technical documentation, and commit messages in English. Maintain English and Russian UI strings and tooltips. The README introduction is English first, then Russian.
- The owner directs development through chat. Maintain the repository for efficient agent navigation; do not require the owner to curate documentation or operate developer tools.
- Read `project/index.json`, then `project/state.json`. Read only the task-relevant documents and modules listed there. Use `rg` for targeted discovery; exclude generated artifacts and private examples.
- Keep requirements traceable by stable `FR-*` / `NFR-*` IDs. Update state and relevant documentation with each substantive behavior change. State facts, assumptions, validation evidence, and remaining work separately.
- Do not spawn other agents unless the owner explicitly requests delegation.

## Product invariants
- DALE is a local desktop image editor for Dungeon Alchemist exports used in Foundry VTT.
- Source input is a JPG/JPEG plus Foundry scene JSON. Default export is separate cropped RGBA PNGs for independent closed regions, each with a mandatory 3-pixel edge guard. Record source and scene placement coordinates; do not replace this workflow with one full-map PNG. Original-size export remains an internal pipeline check only.
- Never overwrite imported JPG/JSON or write temporary closure lines into Foundry JSON. Closures and brushes belong to DALE editing sessions only.
- Automatic gap joins and signed contour offsets also remain editor-only. Distances use original image pixels, not screen pixels; exact and near T junctions must be supported.
- Point handles are fixed 10-screen-pixel circles. Minimum insertion spacing is one handle diameter; shared graph nodes and T junctions move together. Point edits are undoable working geometry only.
- Render closed geometry cyan and unresolved/open contours red, with 2-screen-pixel cosmetic lines at every zoom. This latest color requirement supersedes the earlier outer-red/interior-cyan request and the original diagnostic colors.
- Use two text-only top rows: general actions first; tool-set selection, contextual size, and snapping second. Show the active geometry/pixel set in a single column left of the map, using square icon-only buttons with localized name/help tooltips. Keep filled/bordered buttons and a neutral dark-gray, Photoshop-inspired theme. Ctrl+wheel adjusts sizes globally; Alt-click adds free closure corners.
- Every application control must have English/Russian hover help, including embedded numeric editors, selectors, scrollbars, overflow buttons, and menu controls. Keep icon-only action names in their tooltips and preserve language-independent internal tool keys.
- New line uses press/drag/release. Configurable snapping uses screen pixels and prioritizes vertices over segment interiors, including when moving existing points. Geometry erasers have a circular screen-space footprint, sweep fast drags, and commit one undoable gesture.
- Keep map dimensions, guarded export dimensions, current closed/open counts, region selection, and the language dropdown in the footer. Count open contours as connected unresolved groups, not guessed missing polygons or raw segment counts. Use the same crop-bounds function for display and export.
- Save portable `.dale` ZIP projects with exact source assets, operations, redo stack, settings, and unfinished closure points. Never commit a user's project archive or source artwork.
- After every project update, rebuild and refresh the complete portable package at `DALE/` using `tools/build_windows.ps1`. Deliver `DALE/DALE.exe` with its runtime libraries and startup notes. Preserve `DALE/UserData` and user projects. Do not report an update complete while the portable package is stale.
- Ordinary Windows users launch `DALE/DALE.exe` directly without Python installation or command scripts. Keep the entire portable folder together when moving it. Keep generated runtime binaries out of Git.
- English and Russian UI languages must be switchable at runtime, with descriptive translated tooltips for every application action and setting. Persist the language locally and in project UI settings; retain English technical serialization.
- Store geometry and brush coordinates in original image pixels. Preview resolution must never limit export resolution.
- Keep geometry, import validation, and raster/export logic independent of Qt. Validate them with meaningful tests.
- Do not claim semantic terrain recognition, real Dungeon Alchemist compatibility, or a Foundry integration test without evidence.
- User-supplied files in `examples/` are local, untrusted, and untracked by default. Never upload or commit them without explicit authorization.

## Commands (PowerShell)
```powershell
.\.venv\Scripts\python.exe -m dale
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe tools/check_repository.py
powershell -NoProfile -ExecutionPolicy Bypass -File tools/build_windows.ps1
```

If Git reports ownership mismatch, use the command-scoped option `git -c safe.directory=C:/Programming/GitHub/DALE ...`. Do not change global Git settings to resolve it.
