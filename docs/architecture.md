# Architecture and decisions

Current owner decisions supersede earlier UI/format choices. .dale schema 2 only; no backward compatibility.

## ADR-001: local editor
Python 3.11+, PySide6, Pillow, Shapely, psutil; PyInstaller directory bundle. Core import/geometry/provenance/transforms/history/export are independent of Qt.

| Module | Contract |
| --- | --- |
| scene.py | Bounded validated JPG/JSON, coordinates, exact source wall references. |
| geometry.py | Intersection noding, minimum polygon cells, union masks, unresolved diagnostics. |
| session.py | Immutable operation/redo snapshots; GeometryEdit with lineage/ancestry. |
| provenance.py | Persistent edge/parent/source records and contact nodes, explicit inheritance. |
| editing.py | Insert/move/split/delete/create edges; swept geometry erasing. |
| autoclose.py | Indexed reachable groups, directional extensions, shared intersections/tiny gaps. |
| region_transform.py | Frozen affine plans, related-line reachability, stationary shared-wall copies, common pivot. |
| canvas.py | Rendering/pointer/modifier input; no file dialogs. |
| raster.py | Reduced preview and chronological alpha, cancellable stripe PNG. |
| overlay_export.py | Cell/component crops, guards/padding/clamping, staged placement manifest. |
| project_io.py | Bounded checksummed schema-2 ZIP and multiple JSON catalog. |
| preferences.py | Atomic merged language/version/related choice/input-output folders. |
| toolbar.py / localization.py | Drawn icons, embedded numeric buttons, theme/bilingual help. |
| ui.py | Dialogs, sets/selection, JSON catalog, persistence/export worker. |

## ADR-002: coordinates and raster
Positions use original JPG pixels:
image_x = (wall_x - origin_x - background_offset_x) * image_width / scene_width, likewise Y.
Reject nonidentity background scale/rotation and EXIF rotation. Padding needs alignment evidence. No visible height/origin controls. Internal placement/coordinate primitives are not a compatibility adapter or Foundry importer.

Masks are immutable snapshots. Geometry edits never move artwork or regenerate masks. Preview does not limit export resolution.

## ADR-003: graph editing
Snapping prefers vertices, then interiors; exclude dragged-node incident edges. Alt-drag projects onto the original approached segment vector; toggle mid-drag. Reconciliation epsilon is 1e-7 source pixels.

Cursor Auto-close and Close all contours extend existing free ends forward along vectors. Required travel distances must fit configured screen tolerance; facing collinear tips meet halfway when the full gap fits. T/shared contacts are noded. No standalone bridge or sideways movement. White edges/dashed extensions preview a frozen plan; Cancel/Yes precedes mutation; one undo snapshot. No-op clicks explain.

Eraser hover/deletion share hit tests; swept circles prevent missed edges. Ordinary vertex deletion reconnects two neighbors; branches remove incident edges. No source writes.

## ADR-004: selected cells and transforms
Expose minimum polygonized cells separately from mask union. Toggle smallest covering cell; neighboring cells remain independent. Fill continuous closed QPainterPath rings translucent cyan.

Move regions freezes a geometry plan. Related-line mode uses indexed transitive reachability within snap tolerance. Without related lines detach branches and retain shared walls for stationary neighbors. Drag translates, Ctrl-wheel scales 5%, Alt-wheel rotates 0.1 degree per notch. Common bounding-box center remains fixed through scaling/rotation, moves with translation. Undo/redo stores geometry only; raster/masks stay fixed. Yes/No/Cancel dialog, optional remembered choice; right-click reopens; loading never prompts.

## ADR-005: ancestry and project format
Source identity is exact JSON SHA-256 plus original /walls/index, preserving skipped zero-length array positions; optional Foundry ID need not be unique. Working edges have persistent ID, parents, root source references, origin. Splits/clones get child IDs, merges union parents, new contacts inherit incident parents, detached lines become editor roots. Moves/extensions preserve identity. Deleted ancestors remain in snapshot catalogs. Contact nodes expose line/parent/source records.

Schema 2 requires lineage and JSON catalog. Older/unknown versions rejected; no migrations or historical-coordinate ancestry inference. See project-format.md. JSON import lists every declared package document without decoding/extracting its JPG. Current archives preserve additional documents; automatic generation of updated Foundry JSON is future work.

## ADR-006: separate bounded exports
All-regions exports components; explicit selection exports cells. Signed offset, mandatory 3px artwork guard, extra transparent box padding 0-4096, then clamp all bounds to JPG. Share bounds with UI; fully outside selections report no bounds without crashing. Preserve native visible RGB and alpha history; never burn overlays. Stage complete new directory and rename on success.

placement.json is a DALE coordinate manifest, not native Foundry import. Foundry 13/14/elevation primitives retain placement intent; actual elevation/visibility is set in Foundry.

## ADR-007: compact localized UI
Two text-only top rows; Contours/Regions/Raster, one left column. 48x48 icons; 48x72 numeric tools with independent captions/arrows. Snapping only in Contours. Right Information/Settings replace footer; minimum 1024x768. No default map tooltip; all controls describe actual shortcuts/modifiers.

Closed cyan/open pure red RGB(255,0,0). Black 3px backing + colored 1px center; white hover edges. Fixed 10-screen-pixel handles.

## ADR-008: identity and portable delivery
Title Dungeon Alchemist Levels Export (v.<major>.<minor:02d>.<revision:03d>). Every build invocation advances revision once, including failed attempts; major/minor only owner direction. Supplied ICO unchanged in Qt/PE.

Refresh full root DALE/ and source hashes; preserve UserData/projects/running editors. Move locked old EXE into unique ignored storage if needed; never kill user process. Changed locked libraries may require restart.

## Resource and evidence boundaries
JPG max 16384 per side; warn above 8192. Reduced preview, decoded source plus 128-row export stripes, memory preflight/cancellable worker. Source decoding is not interruptible; no bitmap undo history.

Historical real sample evidence: docs/sample-formats.md. Owner maps are currently absent from examples. Current changes use synthetic fixtures. No semantic segmentation, live Foundry connection/native scene generation/verified live floor assembly.
Archive ownership checks resolve both source and workspace paths before comparing containment; Windows short-name/junction aliases must not cause active assets to be deleted. Retain active extracted JPG/JSON until their session is replaced or closed.
