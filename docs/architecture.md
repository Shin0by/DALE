# Architecture and decisions

## ADR-001: local Python desktop editor

Decision date: 2026-10-16. Use Python 3.11+ with PySide6 (desktop UI), Pillow (JPEG preview/raster operations), Shapely (robust planar geometry), and psutil (memory preflight). The task is local image editing with large files and geometry, so a desktop process avoids server transfers and browser canvas texture limits. Packaging as an executable is a later delivery step.

The UI owns dialogs and input state. The import, geometry, editing, and export modules do not import Qt. This allows the agent to verify image/geometry behavior without automating a desktop.

## Module contracts

- `scene.py`: validated scene input, map dimension limits, source image metadata, explicit scene-to-image transformation. Never mutates the raw JSON.
- `geometry.py`: point-to-source-segment projection, intersection noding, polygonization, and unresolved line diagnostics. Original segments and editor closure segments stay distinct.
- `session.py`: immutable operation records and undo/redo; authoritative positions use native image pixels. A contour mask is a snapshot of the current closed geometry. Later closures do not retroactively change a previously applied mask; apply the mask again to use them.
- Session contour settings store explicit gap tolerance and signed offset in original image pixels. They change the next mask and its geometric preview, not prior mask snapshots.
- `raster.py`: deterministic alpha rendering shared by preview/export; preview max side 2,048. Export uses original image data and 128-row RGBA stripes with incremental PNG/zlib encoding. No full-size RGBA canvas or full-size undo bitmap is stored.
- `canvas.py`: map rendering, live snapping, temporary paths, brush input, and right-button panning in every mode, with navigation space around the image even at fit zoom.
- `placement.py`: independent validation of Foundry 13/14 targets and integer-foot elevation; version-aware guidance and PNG text metadata.
- `ui.py`: import/export dialogs, controls, alignment changes, export worker, and unsaved-edit prompts.

## Coordinates

Image coordinates are the only editing coordinate system. For a supported unrotated scene background:

```text
image_x = (wall_x - scene_origin_x - background_offset_x) * image_width / scene_width
image_y = (wall_y - scene_origin_y - background_offset_y) * image_height / scene_height
```

Default scene origin is `(0, 0)`. Nonzero padding triggers a warning and requires alignment review; do not guess a Foundry-version-specific padding rounding algorithm. The owner can enter the actual scene origin in source scene pixels. Scene dimensions can differ from JPG dimensions and yield explicit scaling. Reject nonidentity background scale/rotation, malformed wall coordinates, and unsupported JSON layouts rather than silently cutting with misaligned walls. EXIF-oriented images are rejected until their coordinates can be explicitly reconciled.

## Geometry policy

Node intersections with Shapely before polygonization. Snap only to original source segments, within 14 viewport pixels. Reconcile projected closure anchors with nearby source lines at 1e-7 image pixels to handle floating-point error on angled segments; this is numerical reconciliation, not automatic gap repair. Give synthetic connectors a distinct visual style. Diagnose dangles, cuts, and invalid rings after polygonization; these may be exterior lines or internal partitions rather than actual gaps. The UI therefore asks for review when enclosed regions coexist with unresolved segments. Never silently bridge a gap or invent a wall.

The explicit gap-tolerance setting described below authorizes visible editor-only bridge generation. It is disabled by default and is distinct from numerical reconciliation and cursor snapping.

All bounded faces are unioned for each mask operation. This is geometric extraction, not ground recognition. Brush edits are applied in chronological order after or between mask operations; restore recovers the source alpha. No geometry is burned into the export.

## ADR-003: configurable joins and contour offsets

Real samples contain small gaps, unclosed artwork, and T junctions. Exact line intersections are noded before tolerance repair. An explicit nonnegative gap tolerance (0 disables joining) creates editor-only bridge segments: prioritize nearby free endpoint pairs, then project remaining free endpoints to eligible source segments, including segment interiors. Use spatial indexes and deterministic distance/coordinate ordering. Each free end receives at most one automatic bridge. Generated joins are visible and never enter source JSON. This does not guarantee a useful polygon where wall metadata is absent or incomplete.

After polygonization and face union, buffer the region by the signed offset. Positive expands, negative contracts; mitered corners preserve straight building edges. Reject empty results from excessive contraction. Settings affect image-space geometry independently of viewport zoom. Keep the original source walls available for snap projection and cyan overlay; show automatic joins in purple and the offset boundary in green. Previously applied masks remain immutable snapshots and can be undone.

The owner can test the native Windows UI with `run.cmd`. The launcher sets up the project-local environment if absent, then starts `pythonw -m dale`. `--image` and `--scene` arguments support agent-assisted opening of real pairs. A standalone executable remains a later packaging task.

## ADR-002: Foundry version and elevation are placement intent

Owner clarification: support Foundry 13 and 14. The raster asset remains RGBA PNG for both. Foundry 13 tile/module workflows differ from Foundry 14 native Scene Levels; do not generate one guessed scene document for both. The prototype provides a version selector and editable elevation dropdown: presets -20 through 100 ft in 5-ft increments, custom integers from -1,000,000 through 1,000,000 ft. Negative elevation supports basements. Fractions are rejected.

PNG `tEXt` keys `DALE.FoundryMajor`, `DALE.ElevationFeet`, `DALE.Placement`, and `DALE.Note` retain the intended placement. Foundry does **not** read these keys to set elevation. They are editor metadata and the user must configure placement in Foundry. Default export names include elevation. A real Foundry adapter must eventually encode scene-unit conversion, v13 module configuration, or v14 Level range/visibility after installation validation. These are explicitly pending, not simulated by PNG metadata.

## Resource policy

Reject images above 16,384 per side before decoding. Locally raise Pillow's decompression-bomb threshold only for the bounded, validated source open, then restore it. JPEG preview uses decoder reduction before thumbnailing. Export retains one decoded RGB JPEG (Pillow storage may use four bytes per pixel), a small stripe, vector operations, and zlib state. Memory preflight estimates 4 bytes per source pixel plus 256 MiB headroom and declines if available RAM is lower. This is an estimate, not an allocation guarantee; errors are surfaced and partial output is removed.

Export cancellation is checked per stripe and progress covers the export stripes. Source JPEG decoding cannot be interrupted inside Pillow. Worker completion is required before closing the application; cancellation must not destroy a running QThread. Output is atomic and source paths are protected.

## Delivery boundaries

No direct Foundry mutation or floor-module dependency in the prototype. JSON import variants and Foundry floor configuration will be determined from owner examples. Do not automatically rewrite/export Foundry JSON, crop transparent margins, or downscale outputs. Persistent sessions, native installers, per-face selection, antialiasing, semantic segmentation, and richer diagnostics remain follow-up work.
