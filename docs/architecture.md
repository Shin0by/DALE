# Architecture and decisions

## ADR-001: local Python desktop editor

Decision date: 2026-10-16. Use Python 3.11+ with PySide6 (desktop UI), Pillow (JPEG preview/raster operations), Shapely (robust planar geometry), and psutil (memory preflight). The task is local image editing with large files and geometry, so a desktop process avoids server transfers and browser canvas texture limits. Deliver a PyInstaller directory bundle with its interpreter and native dependencies; ordinary users launch `DALE/DALE.exe` directly.

The UI owns dialogs and input state. The import, geometry, editing, and export modules do not import Qt. This allows the agent to verify image/geometry behavior without automating a desktop.

## Module contracts

- `scene.py`: validated scene input, map dimension limits, source image metadata, explicit scene-to-image transformation. Never mutates the raw JSON.
- `geometry.py`: point-to-source-segment projection, intersection noding, polygonization, and unresolved line diagnostics. Original segments and editor closure segments stay distinct.
- `session.py`: immutable operation records and undo/redo; authoritative positions use native image pixels. A contour mask is a snapshot of the current closed geometry. Later closures do not retroactively change a previously applied mask; apply the mask again to use them.
- Session contour settings store explicit gap tolerance and signed offset in original image pixels. They change the next mask and its geometric preview, not prior mask snapshots.
- `raster.py`: deterministic alpha rendering shared by preview/export; preview max side 2,048. Export uses original image data and 128-row RGBA stripes with incremental PNG/zlib encoding. No full-size RGBA canvas or full-size undo bitmap is stored.
- `canvas.py`: map rendering, live snapping, temporary paths, brush input, and right-button panning in every mode, with navigation space around the image even at fit zoom.
- `placement.py`: independent validation of Foundry 13/14 targets and integer-foot elevation; version-aware guidance and PNG text metadata.
- `editing.py`: graph-aware point insertion, shared-node movement, T-junction splitting, and configurable junction deletion. Each committed drag stores one geometry snapshot in history; live movement does not rerender the full mask raster.
- `project_io.py`: bounded, checksummed `.dale` ZIP serialization, exact source assets, operations plus redo, geometry and UI settings. Loading uses fixed temporary destinations, never arbitrary archive extraction paths.
- `overlay_export.py`: connected-region PNG crops, mandatory 3-pixel edge guards, source/scene placement manifest, staged all-or-nothing export folders.
- `localization.py`: English source strings, Russian translations, static controls and dynamic message templates; internal tool keys remain language-independent.
- `preferences.py`: portable language settings beside the executable in `UserData/settings.json`, with atomic updates. Development settings live under ignored artifacts.
- `ui.py`: import/export dialogs, controls, alignment changes, export worker, and unsaved-edit prompts.

## Coordinates

Image coordinates are the only editing coordinate system. For a supported unrotated scene background:

```text
image_x = (wall_x - scene_origin_x - background_offset_x) * image_width / scene_width
image_y = (wall_y - scene_origin_y - background_offset_y) * image_height / scene_height
```

Default scene origin is `(0, 0)`. Nonzero padding triggers a warning and requires alignment review; do not guess a Foundry-version-specific padding rounding algorithm. The owner can enter the actual scene origin in source scene pixels. Scene dimensions can differ from JPG dimensions and yield explicit scaling. Reject nonidentity background scale/rotation, malformed wall coordinates, and unsupported JSON layouts rather than silently cutting with misaligned walls. EXIF-oriented images are rejected until their coordinates can be explicitly reconciled.

## Geometry policy

Node intersections with Shapely before polygonization. Use the Snapping toolbar radius (default 14, range 0-256 screen pixels), preferring vertices over segment projections. New lines and moved nodes snap to working walls and local paths. Exclude the moving node and its incident edges from snap targets. Closure anchors use working wall geometry; Alt-click inserts free corners. Reconcile projected closure anchors with nearby source lines at 1e-7 image pixels to handle floating-point error on angled segments; this is numerical reconciliation, not automatic gap repair. Classify source lines, local closures, and automatic joins consistently: closed geometry cyan, unresolved lines red, all at 2 cosmetic screen pixels. An unfinished path is red; an offset boundary is dashed cyan. Diagnose dangles, cuts, and invalid rings after polygonization; these may be exterior lines or internal partitions rather than actual gaps. The UI therefore asks for review when enclosed regions coexist with unresolved segments. Never silently bridge a gap or invent a wall.

The explicit gap-tolerance setting described below authorizes visible editor-only bridge generation. It is disabled by default and is distinct from numerical reconciliation and cursor snapping.

All bounded faces are unioned for each mask operation. This is geometric extraction, not ground recognition. Brush edits are applied in chronological order after or between mask operations; restore recovers the source alpha. No geometry is burned into the export.

## ADR-003: configurable joins and contour offsets

Real samples contain small gaps, unclosed artwork, and T junctions. Exact line intersections are noded before tolerance repair. An explicit nonnegative gap tolerance (0 disables joining) creates editor-only bridge segments: prioritize nearby free endpoint pairs, then project remaining free endpoints to eligible source segments, including segment interiors. Use spatial indexes and deterministic distance/coordinate ordering. Each free end receives at most one automatic bridge. Generated joins are visible and never enter source JSON. This does not guarantee a useful polygon where wall metadata is absent or incomplete.

After polygonization and face union, buffer the region by the signed offset. Positive expands, negative contracts; mitered corners preserve straight building edges. Reject empty results from excessive contraction. Settings affect image-space geometry independently of viewport zoom. Keep source walls unchanged, classify working lines and joins by closed/open topology, and show the offset boundary as dashed cyan. Diagnostics retain the join/segment counts without separate diagnostic colors. Previously applied masks remain immutable snapshots and can be undone.

The owner tests `DALE/DALE.exe`. A positional `.dale` path or `--image` and `--scene` arguments support preloaded testing. Python console/development scripts remain implementation tools.

## ADR-004: point editing and portable projects

Use fixed 10-screen-pixel circular handles, pointing-hand hover, and a minimum insertion distance of one handle diameter. Editing positions stay in source pixels at every zoom. Move shared graph vertices together and split implicit T intersections when needed. Deleting a junction preserves the straightest continuation by default; an explicit alternative removes all incident edges. Source JSON remains unchanged, and mask snapshots are not retroactively regenerated by geometry edits.

The `.dale` schema-1 ZIP has exactly four members: `manifest.json`, `history.json`, `sources/map.jpg`, and `sources/scene.json`. Preserve source bytes, SHA-256 hashes, applied operations and redo stacks, origin/gap/offset, placement, viewport, current tool, language, junction policy, and unfinished closure. Never pickle executable objects. Bound member sizes (64 KiB manifest, 64 MiB history, 1 GiB JPG, 32 MiB JSON), reject unexpected/duplicate/encrypted members and invalid data, and load source assets to a disposable fixed-name workspace. Saving is atomic and independent of original paths.

## ADR-005: separate PNG crops and edge guards

The owner's later instruction supersedes the original full-canvas default. Export one PNG per disconnected component of the selected mask union, not per room. Expand retained outside-mask boundaries by 3 source pixels after the signed user offset, retain real source pixels in this guard, and bound each output by the contour's inclusive pixel limits plus 3 on each side. Areas beyond the original image remain transparent. Preserve brush history; clip each part independently. Fully transparent RGB is zeroed for compact compression; visible RGB is unchanged. Preview remains on the source canvas and does not display the extra export guard.

`placement.json` records each crop's image origin/size, transformed scene position/size, elevation, version, and guard. Include the origin in PNG text metadata as well. This manifest does not claim native Foundry import compatibility. Stage the complete set in a new sibling directory, then rename it only on success; avoid replacing an existing export set.

## ADR-006: maintained portable delivery and localization

After every project update, run `tools/build_windows.ps1` and refresh root `DALE/` with the complete directory bundle, startup note, and source SHA-256 build provenance. Preserve `UserData` and user files during refresh. Never commit generated runtimes or user projects. The package runs without external Python and can be copied as a whole.

Skip copying identical runtime files. When only the executable is locked by an open editor, move that old executable into an ignored, uniquely named artifacts folder before copying the new one; do not terminate the process or discard its edits. An open editor continues its current version until restarted. Changed locked runtime libraries still require the editor to close before deployment can finish.

Keep technical documentation and serialized field names English; switch UI actions, tooltips, guidance, and dialogs between English and Russian at runtime. Russian is the initial default. Persist the choice beside the portable executable and in project preferences. Unknown low-level import/ZIP/library diagnostics can remain English technical detail; application-owned user flows are translated.

## ADR-002: Foundry version and elevation are placement intent

Owner clarification: support Foundry 13 and 14. The raster asset remains RGBA PNG for both. Foundry 13 tile/module workflows differ from Foundry 14 native Scene Levels; do not generate one guessed scene document for both. The prototype provides a version selector and editable elevation dropdown: presets -20 through 100 ft in 5-ft increments, custom integers from -1,000,000 through 1,000,000 ft. Negative elevation supports basements. Fractions are rejected.

PNG `tEXt` keys `DALE.FoundryMajor`, `DALE.ElevationFeet`, `DALE.Placement`, and `DALE.Note` retain the intended placement. Foundry does **not** read these keys to set elevation. They are editor metadata and the user must configure placement in Foundry. Default export names include elevation. A real Foundry adapter must eventually encode scene-unit conversion, v13 module configuration, or v14 Level range/visibility after installation validation. These are explicitly pending, not simulated by PNG metadata.

## Resource policy

Reject images above 16,384 per side before decoding. Locally raise Pillow's decompression-bomb threshold only for the bounded, validated source open, then restore it. JPEG preview uses decoder reduction before thumbnailing. Export retains one decoded RGB JPEG (Pillow storage may use four bytes per pixel), a small stripe, vector operations, and zlib state. Memory preflight estimates 4 bytes per source pixel plus 256 MiB headroom and declines if available RAM is lower. This is an estimate, not an allocation guarantee; errors are surfaced and partial output is removed.

Export cancellation is checked per stripe and progress covers the export stripes. Source JPEG decoding cannot be interrupted inside Pillow. Worker completion is required before closing the application; cancellation must not destroy a running QThread. Output is atomic and source paths are protected.

## Delivery boundaries

No direct Foundry mutation or floor-module dependency in the prototype. Preserve native resolution and source JSON while exporting separate crops. The observed legacy zero-shift/zero-padding profile is validated; other profiles require evidence. Manual free outlines can be assembled with New line. Per-face selection within a connected object, automatic boundary reuse across floors, semantic segmentation, refined edge antialiasing, and live Foundry assembly remain follow-up work.


## ADR-007: toolbar tools, snapping, and status footer

The latest owner color rule supersedes both the original diagnostic palette and the intermediate outer-red/interior-cyan request: draw resolved closed geometry cyan and unresolved segments red. All line pens are cosmetic, 2 screen pixels at any zoom. Keep fixed 10-screen-pixel circular handles.

Use exactly two text-only top rows: general actions, then tool-set selection with contextual size and snapping. A QStackedWidget left of the map displays the current geometry or pixel tools as one narrow vertical column of square icon-only buttons. Switching sets restores the last used tool within the running window; save the active set in project UI settings. Use code-drawn QPainter icons from `toolbar.py` only for left tools, filled/bordered inactive buttons, a clear checked state, and a compact Photoshop-inspired neutral dark-gray palette. Close map offers project saving without closing the application.

New line captures a first endpoint on press and commits the second on release, with a live preview. Prefer existing vertices over closer line projections within the configured screen-space radius. Split target edges at connection points. Moving a node excludes its own incident edges from snap candidates; minimum handle spacing prevents crowded new points.

Geometry erasers remove entire touched edges or vertices, not raster pixels. Sweep a capsule between mouse samples so fast drags do not miss geometry. Split local polylines into surviving runs. Preview immutable GeometryEdit snapshots and commit one per drag; Escape cancels. Vertex erasing reuses the selected junction-deletion policy. Automatic gap joins remain generated from tolerance rather than independently persisted walls.

Pixel brush diameter uses source pixels; geometry eraser diameter uses screen pixels (1-512, default 24). Ctrl+wheel changes the active sized tool anywhere in the window. Over size/distance controls it adjusts that control. Reserve Alt-click for free closure corners; standard Ctrl shortcuts remain available.

The permanent footer contains source map dimensions, current closed components and connected unresolved-group counts, export dimensions with the mandatory 3-pixel guard, an all/one-region selector, and language. An open count is a connected graph-component count, not inferred missing polygons. Closed counts use the current face union, while crop bounds and selection use the effective export mask snapshot. For multiple selected outputs show the largest actual PNG by pixel area; for one show exact dimensions and origin. Share `crop_bounds` between export and footer. Highlight the selected region without burning it into PNGs, and export only that region when selected.

Every application control has localized hover help. Copy source help into embedded numeric editors and popup scrollbars, provide overflow/menu help, and translate tool names and descriptions separately for icon-only buttons. Dynamic selectors refresh their own localized help.

Save optional tool-set choice, snap enablement/radius, geometry eraser diameter, current tools, and region selection in schema-1 project UI settings; defaults preserve loading older archives. Geometry and raster history serialization stay independent of Qt.
