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
| overlay_export.py | Current cell/component cutouts, exact bicubic alpha bounds/cache, clamping and staged manifest. |
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

Move regions freezes a geometry plan. Related-line mode uses indexed transitive reachability within snap tolerance. Without related lines detach branches and retain shared walls for stationary neighbors. Move regions drag translates and Ctrl-wheel scales 5%. A separate Rotate regions mode consumes plain wheel for 0.1 degree clockwise/counterclockwise rotation per notch without view zoom. Both modes share related-line settings/right-click configuration and persist their active mode. Remove the Alt-wheel rotation handler. Common bounding-box center remains fixed through scaling/rotation, moves with translation. Undo/redo stores geometry only; raster/masks stay fixed. Yes/No/Cancel dialog, optional remembered choice; right-click reopens; loading never prompts.

Required isolation, pending NEXT-009: freeze membership before the transform. Do not snap, repair, extend lines toward stationary neighbors or grow the group during the gesture. The owner reported unwanted extensions while moving/rotating; the research update records the defect without claiming an implementation fix.

## ADR-005: ancestry and project format
Source identity is exact JSON SHA-256 plus original /walls/index, preserving skipped zero-length array positions; optional Foundry ID need not be unique. Working edges have persistent ID, parents, root source references, origin. Splits/clones get child IDs, merges union parents, new contacts inherit incident parents, detached lines become editor roots. Moves/extensions preserve identity. Deleted ancestors remain in snapshot catalogs. Contact nodes expose line/parent/source records.

Schema 2 requires lineage and JSON catalog. Older/unknown versions rejected; no migrations or historical-coordinate ancestry inference. See project-format.md. JSON import lists every declared package document without decoding/extracting its JPG. Current archives preserve additional documents; automatic generation of updated Foundry JSON is future work.

## ADR-006: separate bounded exports
All-regions exports current connected components; explicit selection exports cells. The left Artwork offset (-4096..4096 source pixels, stored as contour_offset) expands/contracts retained JPG pixels relative to lines. It is the only margin control: no automatic 3px guard or global transparent-padding setting.

For export, substitute the current offset union for outside-mask boundaries at their existing history positions. Replay brushes and inside masks in order, then constrain each item to its own current offset contour. Project/preview mask snapshots remain immutable; geometry still never moves source artwork. This makes changing the live artwork offset effective in export even after a previous outside mask.

Render alpha only at 2x resolution and reduce with Pillow BICUBIC. Two-source-pixel filter halos on all stripe/crop sides avoid seams and discover complete filter support; they are an internal sampling extent, not an exported fixed border. Scan source-aligned alpha stripes before RGB decoding; getbbox includes every nonzero byte, even 1/255. Crop to this actual alpha box, clipped to JPG. The same renderer encodes PNG and supplies Information dimensions. A 32-entry cache keyed by size/immutable raster operations/contour avoids repeated sidebar scans. No full native alpha bitmap is retained. Native source RGB is unchanged, including under partial alpha; zero-alpha RGB stays compacted.

Fully transparent items are skipped, an entirely transparent set is rejected, and outside selections report no bounds. Stage a complete new directory and rename on success. Placement manifest schema 2 records artwork_offset_px, alpha_antialiasing, bounds_mode and each item's source-coordinate content_bounds. Removed guard/padding metadata has no fallback. Current project UI serialization omits the retired export-padding preference; no migration or alias is added.

placement.json is a DALE coordinate manifest, not native Foundry import. Foundry 13/14/elevation primitives retain placement intent; actual elevation/visibility is set in Foundry.

## ADR-007: compact localized UI
File/Edit/About menus own general commands. Three adjacent top panels: Sections (text Contours/Regions/Raster), Scene (text Levels), Main (36x36 icon-only Hand/Clear selection/Fit/Show contours/Settings). Menu/toolbar Clear selection share one QAction and shortcut. One left column contains the active toolbar directly in an unframed stack, without the former nested wrapper/frame: 48x48 icons and 48x72 independent numeric tools. Snapping only in Contours. Minimum 1024x768; no footer or default map tooltip.

Right pages are mutually exclusive: Project nests Regions and File information; Scene contains an empty Levels group reserved for future controls; Settings orders target, language, global-scope checkbox and explanation. Every page owns an identical 240px Information group at the bottom. Update all copies from one contextual-help source, including actual enabled QAction shortcuts. Levels cancels previews, hides left editing tools and activates Pan without changing geometry/raster. Settings toggles its page and returns to the active scene/project page. Editing section selection returns to Project. Native floor controls/export are not implemented by this placeholder.

File > Recent projects always exists, including an empty-state entry. Store at most10 unique absolute .dale paths from successful saves/opens, newest first, in merged portable preferences. Missing paths stay listed but disabled with explanatory path help. Opening an entry runs ordinary save/discard/cancel first. Clear list preserves files. Do not store archive extraction paths. Refresh dynamic menu translations on language switches. Rotate regions help documents wheel and tool-button right-click; all controls retain localized gestures/shortcuts. No-op auto-close remains Close-only; geometry changes require Cancel/Yes.

Closed cyan/open pure red RGB(255,0,0). Black 3px backing + colored 1px center; white hover edges. Fixed 10-screen-pixel handles. Show contours off suppresses all base geometry/offsets and inactive handles regardless of mode. Selected cells remain visible only in region tools. Hover previews carry a separate unresolved subpath, so white-edged drawing never restores all base centerlines. Explicit new-line/snap/drag/repair previews remain visible as active geometry.

## ADR-008: identity and portable delivery
Title Dungeon Alchemist Levels Export (v.<major>.<minor:02d>.<revision:03d>). Every build invocation advances revision once, including failed attempts; major/minor only owner direction. Supplied ICO unchanged in Qt/PE.

Refresh full root DALE/ and source hashes; preserve UserData/projects/running editors. Move locked old EXE into unique ignored storage if needed; never kill user process. Changed locked libraries may require restart.

## ADR-009: numeric tool setting scope

Eight values have stable preference keys: line_eraser_diameter, vertex_eraser_diameter, raster_erase_diameter, raster_restore_diameter, auto_close_distance_px, global_close_distance_px, snap_distance_px and artwork_offset_px. Validate integer ranges independently; malformed config entries use current defaults. The right Store settings globally checkbox is an application preference (global_tool_settings, default false), not a project flag.

Off: current numeric values belong to the project. On: snapshot the project's current values, copy all active values into portable tool_values, then merge subsequent individual changes atomically with the existing config. Restore before opening a project; enabled global values override its numeric settings. Preserve an independent project snapshot while global values are active. Unchecking applies that snapshot, including the session's artwork offset, without changing raster/masks/history. Saving in global mode serializes a shallow session copy with the project offset and project UI numbers; never write the global override over the project's own values. A new JPG pair starts with the currently active values. Language, Foundry target, paths and related-line choice retain their existing independent policies.

Qt control changes and view-driven Ctrl+wheel resizing converge on one persistence method; signal-blocked UI synchronization still records changed values. Initialization/project restoration suppress intermediate writes. Internal tool keys remain stable while explicit English/Russian labels name the affected regions, contours or raster. Clear selection cancels transient gestures, clears selected cells/pivot and hover geometry, then repaints; no committed operation is added.

## ADR-010: editable circular contours

Circles are regular closed polygons in existing GeometryEdit snapshots, not a new archive primitive. Press fixes the center; drag changes radius; release commits one undo step. Preview and commit use the same vertices. No ordinary snapping is applied while drawing. Exact contact vertices split existing edges and inherit parents through LineageBuilder; unaffected IDs remain stable. Existing point/line tools, region selection, transforms, masks and PNG export can operate on the result without adapters.

Use source grid cell size (numeric Dungeon Alchemist export or Foundry grid.size), converted to image pixels. Missing/invalid grids use an explicit 100-source-pixel editing fallback; it is not inferred scene metadata. For diameter d in cells: 4 vertices for d<=0.5, 6 for d<=1, 8 for d<=2; otherwise min(4096, 8+2*ceil((d-2)/2.5)). Zoom does not change density. This owner-selected sparse approximation intentionally makes small circles square/hexagonal. Do not add subpixel-error tessellation or regenerate the polygon after ordinary point edits. Ctrl+wheel adjusts the active radius in screen pixels, Escape/Clear selection cancels.

Foundry Regions support native circle and polygon shapes, while walls use straight segments. Future serialization should preserve the edited polygon as Region polygon/individual walls; emitting a native circle requires a future explicit semantic primitive and round-trip rules. Existing original JSON remains unchanged. See foundry-export-feasibility.md for sources and limitations.

## Resource and evidence boundaries

Exact PNG bounds for sidebar information are coordinated by bounds_preview.py. Crops totaling at most 262,144 candidate pixels are immediate; larger calculations use one Qt worker with immutable Session/polygon snapshots and cancellation between alpha stripes. Keep only the newest pending request and apply results only for the current geometry/selection/raster/offset key. A bounded 16-result cache avoids repeated scans. Pending information says calculating exact bounds; do not show stale dimensions or substitute approximate boxes. Export still computes identical exact nonzero alpha bounds.

Canvas raster rendering is keyed only by scene image size and raster mask/stroke snapshots. A contour-only edit changes geometry without rebuilding the same RGBA preview/QPixmap. Raster edits and undo/redo invalidate this key. Stop/cancel the bounds worker before window shutdown; the worker never decodes source RGB or accesses temporary project files.

Read-only profiling of three owner daytime scenes (13500x16200) found synchronous sidebar alpha scans dominated the reported pause: ground-scene refreshes 698–725 ms, geometry edits about 4 ms. With background bounds and raster reuse, profiled UI refreshes were 20–38 ms for that scene, 4–5 ms for the other two. This measures the tested update path, not a universal latency guarantee. Synthetic Qt tests verify live event-loop progress during a held worker and rejection of obsolete offset requests.
JPG max 16384 per side; warn above 8192. Reduced preview, decoded source plus 128-row export stripes, memory preflight/cancellable worker. Source decoding is not interruptible; no bitmap undo history.

Real sample evidence: docs/sample-formats.md; six owner JPG/JSON pairs and the independent Foundry 13.351 scene probe are present locally. Semantic evidence and future export design: docs/foundry-scene-format.md and docs/foundry-export-feasibility.md. Current export-margin regression checks use synthetic fixtures. No semantic segmentation, live Foundry connection/native scene generation/verified live floor assembly.
Archive ownership checks resolve both source and workspace paths before comparing containment; Windows short-name/junction aliases must not cause active assets to be deleted. Retain active extracted JPG/JSON until their session is replaced or closed.
