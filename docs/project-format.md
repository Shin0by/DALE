# DALE project schema 2

Only schema 2 is supported; older/unknown formats are rejected without migrations.

## Members and limits
Required ZIP members: manifest.json, history.json, sources/map.jpg, sources/scene.json.
Additional JSON members must be declared at sources/json/<id>.json. Reject unexpected/duplicate/encrypted members and traversal paths.

Limits: manifest 64 KiB; history 64 MiB; JPG 1 GiB; each JSON 32 MiB; catalog 1-100 entries, 128 MiB combined JSON. IDs match [A-Za-z0-9_-]{1,64}. Required source ID: source. SHA-256 covers every payload; saves are atomic.

Manifest fields: format=dale-project, schema_version=2, app_version, image_name, scene_name, sha256 map, json_documents array. Each document has id, name, kind (original/updated), member. The source member is sources/scene.json; additional IDs map to sources/json/<id>.json.

Updated JSON generation is future work. Additional declared documents already round-trip and appear in the JSON import chooser. Selecting JSON does not load package JPG/history.

## Provenance
Geometry snapshots include walls, closures, lineage (walls followed by path edges), ancestry catalog, inspectable vertices.
Each edge record has id, parents, sources, origin (source/editor/derived).
Each source reference has json_sha256, wall_index, optional foundry_id.
Source IDs: sha256:<digest>#/walls/<original-array-index>. Index includes skipped zero-length walls. Foundry ID may be absent/nonunique. Preserve exact source bytes.

Splits create child IDs; merges union parent/source references. New contact lines inherit incident parents, including interior splits. Detached lines are independent editor roots, with no fabricated JSON source. Movement/extension preserve identity; shared-wall clones get child IDs. Retain deleted ancestors so parents remain resolvable. Nodes expose point, lines, parents, sources; runtime recomputes from edge records. Validate against embedded JSON and reject unknown parents. Both applied history and redo preserve ancestry.

## State
History stores origin, gap_tolerance, contour_offset, operations, redo, UI. All coordinates are source pixels; masks/geometry are immutable snapshots.

Current UI stores tool set/mode, language, Foundry target, viewport/wall visibility, independent eraser/brush sizes, snap enablement/distance, local/global auto-close tolerance, selected cell indices and active related-line choice. Artwork offset is history.contour_offset and appears in the left Regions tile. No global transparent-padding setting is serialized; exact nonzero bicubic alpha bounds are computed at export.

New circle is a current contour mode. Its completed polygon is an ordinary GeometryEdit with per-edge lineage and undo/redo; no new operation type, native circle metadata or schema migration is required. The transient center/radius gesture is not saved. Original source JSON remains byte-for-byte unchanged.

The application's global_tool_settings preference controls numeric-tool precedence; it is not embedded into .dale. Global overrides do not replace a loaded project's eight stored values. Save serializes the project's independent UI numbers and artwork offset even while global values are active; unchecking the setting restores those project values. Internal mode keys are stable and separate from translated action names. No archive format migration is introduced.

Remember choice and two input/output directories are portable preferences, not project paths. Retired modes, unfinished-draft migration, shared-size fallbacks, export-region aliases, and component-selection migrations are unsupported.
Rotate regions is a persisted current tool mode; rotation uses ordinary wheel, not Alt-wheel in Move regions. Wall visibility is restored independently of active selection.
