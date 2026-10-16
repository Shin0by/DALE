# Agent entry point

## Working agreement
- Communicate with the owner in Russian. Write code, identifiers, comments, technical documentation, and commit messages in English. Maintain English and Russian UI strings and tooltips. The README introduction is English first, then Russian.
- The owner directs development through chat. Maintain the repository for efficient agent navigation; do not require the owner to curate documentation or operate developer tools.
- Read `project/index.json`, then `project/state.json`. Read only the task-relevant documents and modules listed there. Use `rg` for targeted discovery; exclude generated artifacts and private examples.
- Keep requirements traceable by stable `FR-*` / `NFR-*` IDs. Update state and relevant documentation with each substantive behavior change. State facts, assumptions, validation evidence, and remaining work separately.
- Do not spawn other agents unless the owner explicitly requests delegation.
- Window title is exactly `Dungeon Alchemist Levels Export (v.<major>.<minor:02d>.<revision:03d>)`, independent of language or open file. Every invocation of `tools/build_windows.ps1` automatically increments revision by 1 through `tools/bump_revision.py`; never manually advance revision. Change major/minor only at the owner's explicit instruction, and never carry a revision overflow into them. Keep package, pyproject, and state versions synchronized.

## Product invariants
- DALE is a local desktop image editor for Dungeon Alchemist exports used in Foundry VTT.
- Source input is a JPG/JPEG plus Foundry scene JSON. Default export is separate cropped RGBA PNGs for independent closed regions, each with a mandatory 3-pixel edge guard. Record source and scene placement coordinates; do not replace this workflow with one full-map PNG. Original-size export remains an internal pipeline check only.
- Never overwrite imported JPG/JSON or write temporary closure lines into Foundry JSON. Closures and brushes belong to DALE editing sessions only.
- Automatic gap joins and signed contour offsets also remain editor-only. Distances use original image pixels, not screen pixels; exact and near T junctions must be supported.
- Point handles are fixed 10-screen-pixel circles. Minimum insertion spacing is one handle diameter; shared graph nodes and T junctions move together. Point edits are undoable working geometry only.
- Do not add a dedicated T-junction deletion setting or main-wall preservation policy. Use ordinary line/vertex tools with snapping. Deleting an ordinary wall point reconnects its two neighbors; deleting a branching wall point removes its incident edges. Ignore the retired `junction_policy` field in older projects and omit it from new UI state.
- Render closed geometry cyan and unresolved/open contours pure red (RGB 255, 0, 0). Use 3-screen-pixel cosmetic strokes: a black 3-pixel backing and a 1-pixel colored center, leaving 1-pixel black edges at any zoom. This supersedes previous line thickness/color requirements.
- Auto-close traces every working line under its circular cursor through existing connections and eligible directional extensions. White 1-pixel side edges replace black edges on all affected lines while their center colors remain unchanged; dashed continuations preview endpoint extension. A click lengthens existing segments along their vectors to their future intersection in one undoable GeometryEdit; never add standalone connector segments. Only free ends move forward; existing line directions and lengths remain covered. Collinear facing ends meet at their midpoint; extend a free end to a target segment for a T connection and split the target there. Keep this independent of ordinary snapping and global source-pixel gap tolerance.
- Use two text-only top rows: unframed general commands first; tool-set selection plus Hand, Fit, and Walls second. Show the active geometry/pixel set in one left column. Ordinary tools are 48 x 48 icon-only buttons. Line and vertex erasers are separate 48 x 72 buttons, each with an independent diameter caption below its icon and small gray left/right arrows inside the same button. The caption remains directly editable. Hide the separate geometry-size tile; keep the pixel-size tile in the pixel set and the Snapping (px) tile below tools. Use Russian terminology "Прилипание", localized help, and a neutral dark-gray theme. Ctrl+wheel adjusts the active or hovered tool's own size. Auto-close has its own 48 x 72 button with an independent editable 1-256 screen-pixel distance (default 14) and gray arrows; Ctrl+wheel changes that distance. The retired Closure tool and Alt-click gesture are absent.
- Persist `line_eraser_diameter` and `vertex_eraser_diameter` separately in project UI settings. Older archives initialize both from legacy `geometry_diameter` (24 by default); never synchronize the two tools' sizes after loading.
- Every application control must have English/Russian hover help, including embedded numeric editors, selectors, scrollbars, overflow buttons, and menu controls. Include actual assigned shortcuts and applicable Ctrl+wheel or Escape gestures. Derive command shortcuts from QAction assignments; do not invent bindings. Keep icon-only action names in tooltips and preserve language-independent internal tool keys.
- New line uses press/drag/release. Configurable snapping uses screen pixels and prioritizes vertices over segment interiors, including when moving existing points. Geometry erasers have a circular screen-space footprint, sweep fast drags, and commit one undoable gesture.
- Keep map dimensions, guarded export dimensions, current closed/open counts, region selection, and the language dropdown in one footer row. Minimum window size is 1024 x 768. Count open contours as connected unresolved groups, not guessed missing polygons or raw segment counts. Use the same crop-bounds function for display and export.
- Save portable `.dale` ZIP projects with exact source assets, operations, redo stack, settings, and legacy closure paths. When loading old unfinished paths with at least two points, retain them as editable geometry and preserve redo; map the retired Closure mode to New line. Never commit a user's project archive or source artwork.
- After every project update, rebuild and refresh the complete portable package at `DALE/` using `tools/build_windows.ps1`. Deliver `DALE/DALE.exe` with its runtime libraries and startup notes. Preserve `DALE/UserData` and user projects. Do not report an update complete while the portable package is stale.
- Ordinary Windows users launch `DALE/DALE.exe` directly without Python installation or command scripts. Keep the entire portable folder together when moving it. Keep generated runtime binaries out of Git.
- Use the owner-supplied `src/dale/assets/favicon.ico` unchanged for application/windows and the Windows EXE icon. Preserve `shin0by.png` as the original artwork reference. Include both in package data and portable provenance; do not regenerate or redraw the supplied ICO.
- English and Russian UI languages must be switchable at runtime, with descriptive translated tooltips for every application action and setting. Persist language and selected Foundry 13/14 version locally and in project settings; retain English technical serialization. Updating one preference must preserve the other.
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
