# Per-level wall editing

Owner scope replacement2026-10-17 (ADR-020): DALE edits one scene image and its optional source contour JSON, repairs/joins/closes contours, cleans alpha and exports separate native RGBA PNGs for all connected closed objects or selected minimum cells. Every PNG filename includes its exact final width and height in pixels. Levels, wall/floor presets, composition, portals, native Scene export and Foundry runtime configuration are cancelled; the owner configures these manually in Foundry. Earlier plans are historical, not a backlog.

The following historical decisions/evidence do not authorize removed product features.

Planned update2026-10-17: ADR-011..014 replace automatic all-level wall membership and this prototype layout. Preserve source wall properties when copying; ordinary defaults apply to new manual lines/reset. Double-click a wall opens the standard prefilled linked-preset editor or creates a corrected preset from its effective properties. Existing shared-preset save updates its references; Save as new affects only the clicked wall. Cancel and double-click must not commit a paint/reset stroke. See FR-070 and the architecture for atomic history and explicit instance ownership.

Scene > Templates edits shared level definitions and wall presets. Scene > Walls opens a separate assignment page. The visible left toolbar contains Select walls, two independent numeric property brushes, and Select all walls. The right page contains level and preset lists without definition management buttons. Settings remains a separate page; every page shares contextual Information. Minimum window size is 1224 x 768.

## Level scope and selection

Every current contour edge exists as an independent ordinary wall on every defined level. No preliminary membership assignment is needed. Check level rows to choose the scope for preset application; click a row to choose the current level whose colors are displayed. Different presets on different levels remain separate instances, including adjacent levels with identical properties. Heights come from the level's nullable whole-foot limits.

Click a segment to toggle selection. Drag a rectangle to select intersecting segments, including segments whose endpoints lie outside it; Shift+drag adds to the selection. Select all walls / Ctrl+A selects all visible segments. Clear selection / Ctrl+Shift+A clears wall selection as well as extraction selections. Right-drag pans, ordinary wheel zooms. Hidden-only segments cannot be selected. Turning off Show contours retains selected and hovered walls.

Checking a preset applies it to the selected segments on the checked levels. Default wall clears the preset reference. Only the current level supplies displayed/selectable walls; a hidden current level supplies none. Each preset has its own configurable RGB color; assigned segments follow that color immediately. Icons independently distinguish wall, window and door variants. Black 3px backing and 1px color centers retain the existing line style; active/affected segments have white backing.

## Scene background and level stacking

A separate graphics overlay covers the entire JPG rectangle with the current level RGB color at alpha64/255, matching region-fill translucency. It is not clipped to closed contours and never modifies the JPG or exported raster. Place it above the background and lower-level asset groups, but below the current level group. Current-floor surfaces therefore retain their original colors; lower content is tinted. Wall strokes are drawn above the overlay and retain their preset RGB values unchanged.

Sort levels by lower elevation, then upper elevation, with null limits as negative/positive infinity and stable creation order for ties. Hide asset groups above the current level; honor each level's eye state. Foreground wall rendering/hit testing uses only the current visible level. Groups already support this order; native floor-PNG creation remains future work. The overlay is a simple rectangle, without contour scans or raster recomputation.

## Property brushes

Reset wall properties uses a formatting-cleanup brush icon. It resets intersected segments to ordinary defaults on the current visible level only. Other levels retain their presets.

Paint wall properties requires a preset and checked visible levels on the right, then paints those settings onto intersected segments. It does not require prior selection. No property change is made until a preset is chosen. Hidden levels are excluded from brush writes.

Both brushes have their own persistent 1-512 screen-pixel radius inside their 48x72 left tool buttons. Typing, arrows and Ctrl+wheel use the same values. Hover previews affected segments with white backing and a circular footprint. Fast strokes test the swept capsule, not just pointer samples. A completed stroke is one undo step; Escape cancels it. Geometry, source image and raster masks do not change. Numeric values follow project/global settings precedence.

## Identity and contour edits

Wall instances hold their own unique ID, base-edge ID, level ID, optional preset ID and optional parent-instance ID. Base-edge lineage holds source SHA-256, original array pointer and optional Foundry ID when a source exists. A completely new independent line is its own root, without a parent or source JSON reference. Manual contact ancestry is topological information; contact alone never copies a neighboring door/window preset.

Moving/extending a contour edge preserves its assignments. Splitting a line creates child instances inheriting its settings independently on every level; child IDs are new and deterministic from the previous instance and child edge. A new independent segment appears as an ordinary wall on every level. Deleting an edge removes its current instances. A merge that would destroy a boundary between different presets is refused. Geometry and assignment operations share undo/redo, including after project save/load.

The level eye in Templates controls that level's wall instances and its asset group. Other visible levels remain independent even when their geometry coincides. Removing a preset makes its references resolve to ordinary defaults; removing a level deactivates its instances. Historical references remain available for editing history.

## Storage and limits

DALE schema 4 stores wall_assignments snapshots in history operations/redo. Validate IDs, unique edge/level pairs and known base edges. Each assignment operation permits up to 500000 instances and remains subject to the 64 MiB history limit. Default per-level instances are generated lazily with stable IDs; explicit snapshots preserve edited properties. Reuse cached results while operation identities and level IDs stay unchanged.

File > Import templates reads shared definitions only from a selected current .dale project, appending fresh definition IDs without loading its image, contours or assignments. No standalone template export command exists. Normal project Save can store a template-only .dale before an image is loaded. Native Foundry scene serialization, v13 module heights and v14 level mapping remain separate future work; this editor does not rewrite imported JSON.
