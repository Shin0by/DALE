# Foundry semantic export: feasibility and proposed design

Status: research and design, 2026-10-16. The owner requested analysis before implementation. No semantic export, floor editor or automatic Foundry import is delivered here. Evidence: [observed scene atlas](foundry-scene-format.md), [machine profile](../project/foundry-format-profile.json), [original Dungeon Alchemist profile](sample-formats.md). Future work is tracked as NEXT-002, NEXT-008 and NEXT-010; the independent transform defect is NEXT-009.

## Feasibility conclusion

Generating a new scene from original map JSON plus DALE's edited geometry is feasible. The supplied 13.351 scene provides concrete v13 wall, composite Region and teleport records. Existing ancestry identifies which original wall each working segment came from. These are necessary inputs, but provenance and polygons alone do not preserve all gameplay semantics.

A separate semantic model and two target serializers are required. PNG export stays an image operation; floor visibility, walls, doors, Regions, teleport links and native levels require Foundry documents and a tested import path. A JSON can reference PNG/media paths without containing their bytes, so portable delivery must also provide assets and a placement/import procedure.

## Target differences

| Feature | Foundry 13 target | Foundry 14 target | Evidence / unresolved work |
| --- | --- | --- | --- |
| Transparent artwork | Cropped PNG placed as tile/scene artwork with recorded transform | Same image; associated level and rendering settings differ | Existing PNG pipeline only. |
| Walls | Core wall restrictions/doors plus optional module flags | Core walls additionally have a `levels` field | [v13 BaseWall](https://foundryvtt.com/api/v13/classes/foundry.documents.BaseWall.html), [v14 BaseWall](https://foundryvtt.com/api/v14/classes/foundry.documents.BaseWall.html). |
| Core floor organization | No v14-style Level collection in this probe; separate scenes are one possible core workflow | Native embedded Scene Levels with elevation ranges, artwork and visibility | [v14 Level schema](https://foundryvtt.com/api/v14/classes/foundry.documents.BaseLevel.html), [LevelData](https://foundryvtt.com/api/v14/interfaces/foundry.documents.types.LevelData.html). |
| One-scene stacked floors in v13 | Evaluate an explicit, pinned module profile; Wall Height alone is insufficient | Native levels are the primary candidate | [Wall Height author guide](https://wiki.theripper93.com/free/wall-height), [v14 release](https://foundryvtt.com/releases/14.359). |
| Regions | Shapes, shared elevation interval, visibility and behaviors | Additional level membership, attachment/restriction/display/ownership fields | [v13 BaseRegion](https://foundryvtt.com/api/v13/classes/foundry.documents.BaseRegion.html), [v14 BaseRegion](https://foundryvtt.com/api/v14/classes/foundry.documents.BaseRegion.html). |
| Teleport behavior | Singular `destination`, boolean `choice` | Plural `destinations`, plus `choice`, `dialog`, `placement`, `revealed`, `snap`, `transition` | [v13 teleport schema](https://foundryvtt.com/api/v13/classes/foundry.data.regionBehaviors.TeleportTokenRegionBehaviorType.html), [v14 teleport schema](https://foundryvtt.com/api/v14/classes/foundry.data.regionBehaviors.TeleportTokenRegionBehaviorType.html). Nested defaults need an actual v14 export. |
| Floor traversal/surface | Explicit chosen core/module strategy | Change Level and Define Surface behaviors are available | [ChangeLevel schema](https://foundryvtt.com/api/v14/classes/foundry.data.regionBehaviors.ChangeLevelRegionBehaviorType.html), [DefineSurface schema](https://foundryvtt.com/api/v14/classes/foundry.data.regionBehaviors.DefineSurfaceRegionBehaviorType.html), [official level demo](https://foundryvtt.com/packages/restored-keep-levels). |

The native Level schema includes `_id`, name, sort, background/foreground, textures, fog, visibility, elevation and flags. It is a different entity from a Region's activation interval. The public Change Level schema exposes `movementActions`; the Define Surface schema exposes culling, exposure, light, move, occlusion, placement, sight and sound. Those names establish available concepts, not enough nested values/defaults to invent valid example JSON.

The target version selector must select an explicit serializer/capability profile, not just change a label or one height. Targeting Foundry 13/14 is a product requirement and is separate from unsupported legacy `.dale` schemas. The original Dungeon Alchemist input layout remains an explicitly observed source profile; its `sense` enum cannot be copied numerically into modern `sight` or `light`. Determine and verify an intentional mapping before generation.

## Proposed data boundaries

| Layer | Proposed responsibility | Current state |
| --- | --- | --- |
| Immutable source catalog | Exact original bytes, hash and original array pointers; additional updated snapshots separately | Present in schema-2 `.dale`. |
| Source semantic records | Ordered wall endpoints, all restrictions, thresholds, door/animation/audio, flags and source document identity | Raw scene is retained, but no typed editable semantic model. |
| Working geometry and lineage | Persistent edge/parent/source graph, edits and contact references | Implemented; sufficient to locate source metadata, not to resolve semantic conflicts. |
| Semantic map model | Floors, wall properties, ordered Region shapes, behavior graph, asset transforms, per-version extensions | Proposed. |
| Target serializers | Explicit v13 core/module profile or v14 native profile, ID/UUID maps and validation reports | Proposed. |
| Delivery/import verification | Assets, source-to-target mapping, Foundry import, link repair if necessary, live behavior checks | Pending. |

The semantic layer should distinguish a DALE minimum extraction cell, a Foundry Region, a floor and a native v14 Level. A single Region can contain disconnected shapes, while one building floor can contain many cells/Regions. A door passage and a teleport portal are also distinct concepts. Geometry can be reused to propose boundaries, but no implicit one-to-one conversion should erase those distinctions.

Preserve unknown fields and extension flags with their source semantic record. DALE must not execute imported scripts/macros or behaviors. Generating map content must deliberately handle world-owned tokens, Actor links, journals, ownership, folders and playlists; copying unrelated source-world references is not a portable-map strategy. Exact original data remains in the project regardless of the chosen generated-map scope.

## Wall ancestry and semantic edits

1. Resolve every working edge's source references against exact catalog hashes and original `/walls/index`. Preserve its ordered endpoint correspondence separately from the undirected geometric key. Current geometry may canonicalize endpoint order; this can reverse `dir` semantics and animated hinges unless the serializer accounts for orientation.
2. A moved, rotated or extended wall retains source identity and properties. A coordinate transform does not implicitly turn a one-way door around. Map first/second endpoint orientation intentionally; swap left/right when serialization reverses endpoints, and test door hinge/animation behavior.
3. Split ordinary walls may inherit restrictions and flags. Splitting a door does not automatically mean several independent doors: require an explicit policy for the interactive span and preserve ancestry for every resulting piece.
4. Merging or contacting walls can produce multiple parents with conflicting door, direction, restriction, sound, animation or height settings. Parent-set union is not semantic-field resolution. Retain segmentation or present a defined resolution decision; do not pick an arbitrary parent's fields.
5. New manual lines may have contact parents or be independent editor roots. Contact ancestry indicates origin, not automatic agreement of gameplay settings. Use explicit chosen defaults/properties for genuinely new semantic walls.

Per owner clarification, all combinations permitted by Foundry remain valid input. Do not use a short preset list as a validator. Preserve unusual but valid combinations, null thresholds, empty animation choices and module flags. Finite inverted wall-height bounds may be normalized to ascending bottom/top in the working/generated record, with an auditable original-to-normalized difference; never rewrite the original document. Do not normalize nulls to zero, or generalize this rule to every interval without evidence. Product UI can explain a normalization without treating Foundry's saved data as invalid.

Foundry embedded IDs and DALE lineage IDs have different jobs. In this sample embedded IDs are 16 alphanumeric characters. A `line:<uuid>` editor ID cannot be used directly as a Foundry embedded `_id`. Preserve IDs for safe one-to-one updates, allocate target-valid IDs for new/split/cloned documents, and keep a complete source/working/target map. Never rely on array index alone after editing.

## Region and teleport construction

Preserve editable positive/negative primitives in their original order, including redundant positive shapes, empty Regions and hole-only constructions. A normalized polygon cache may support hit testing/export, but it must not replace the source construction unless the operation deliberately flattens it. Decide precision and tessellation when ellipses become polygons; the local Shapely approximation is not Foundry's runtime clipping engine.

Region elevation is independent of wall module bounds and floor membership. Preserve nullable/unbounded endpoints, equal-height ranges and negative heights. Grid distance uses scene units; XY pixel scaling must not multiply vertical feet or sensory thresholds simply because these are also numeric values.

Build teleport links in two passes: allocate all scene/Region/behavior IDs, then resolve directed destinations through the map. Preserve one-way connections and confirmation choices. Detect unresolved/cross-scene links and explain their status rather than silently redirecting. The observed graph is R4↔R5, R6→R7→R4.

The source scene has no root `_id` but its links contain the original scene UUID. Foundry may assign a different ID when importing/cloning. Verify the supported scene-import behavior before promising that a standalone JSON's links survive. Depending on that behavior, delivery may require a controlled helper/import step that creates the scene then repairs UUIDs. Destination elevation, token size, landing placement and re-entry/chaining behavior need live tests; the file alone does not establish them.

## Coordinates, assets and floors

### Circular contours (2026-10-16)

Foundry has a native Region circle model in [v13 CircleShapeData](https://foundryvtt.com/api/v13/classes/foundry.data.CircleShapeData.html) and [v14 CircleShapeData](https://foundryvtt.com/api/v14/classes/foundry.data.CircleShapeData.html). The v13 schema lists type/hole/x/y/radius. Region shape types also include polygons. This differs from [v14 BaseWall](https://foundryvtt.com/api/v14/classes/foundry.documents.BaseWall.html), whose c coordinates describe straight wall endpoints.

DALE's new circular-contour gesture creates editable regular polygon edges. Density follows the owner's grid-cell diameter rule: <=0.5 cell 4 vertices, <=1 cell 6, <=2 cells 8, then two more per started 2.5 cells, capped at 4096. This replaces the initially considered subpixel-error approximation. These edges fit the existing archive/lineage model and can later serialize as wall segments or a Region polygon. A native circle is technically available in Foundry, but should not be reconstructed from manually edited polygon points or promised as the current output. Semantic scene generation and live Foundry import validation remain future work; current delivery exports PNG and saves .dale geometry.

Maintain explicit transforms between padded Foundry canvas, unpadded scene rectangle, source JPG and each cropped PNG. Resolve padding/grid rounding and background placement before editing. Store crop origin and dimensions; never shrink or shift an individual floor implicitly. Raster masks and source images stay fixed when only geometry moves. The left Artwork offset controls retained JPG content; exact nonzero bicubic alpha bounds determine crops, clipped to JPG. The owner removed the mandatory 3px guard and global transparent-padding parameter.

For v13, evaluate two named profiles: core separate scenes with region teleports, and a pinned single-scene module stack. The latter requires actual module exports and visibility tests; the Wall Height flags in this sample are insufficient. For v14, use native Level records plus wall/Region membership and the appropriate surface/transition definitions. A floor descriptor will need a stable ID, name/order, elevation range, imagery transform and gameplay membership. Future integer-foot UI defaults can use 5-foot presets, but no height controls are added during this research.

## Pending transform isolation defect: NEXT-009

Owner report: moving/rotating selected Regions can cause unwanted connections or endlessly extended lines toward the moving object. Record this as a separate implementation task, not a confirmed diagnosis of a particular function.

Required behavior: determine the selected and optionally related line set **before** the gesture, freeze that set, and transform it only. Related-line tolerance may discover membership at preparation time; active snapping, directional repair, noding toward stationary neighbors or automatic extensions must not run during translation, scaling or rotation. Stationary geometry must not chase the transformed group. Preserve necessary shared-boundary copies and ancestry; leave raster and mask snapshots fixed. This is recorded, not fixed by the documentation update.

Future regression evidence should compare stationary segment coordinates and counts throughout repeated move/rotate/scale gestures, with ordinary snapping on/off and both related-line choices. Cover shared boundaries, near parallel endpoints, branches, several selected cells, repeated wheel events, Escape and undo/redo. Ensure the group does not grow as it passes other geometry and no new connector is created.

## Implementation sequence and acceptance evidence

| Stage | Deliverable | Required evidence before proceeding |
| --- | --- | --- |
| 1 | Pinned source/target profiles | Owner v14 equivalent export; exact v13 module builds; runtime padded scene dimensions. Expand probes for currently absent settings. |
| 2 | Read-only semantic model and preservation | Decode known fields while retaining original/unknown data; ordered endpoints/shapes and all links round-trip without gameplay reinterpretation. |
| 3 | Explicit semantic edit rules | Door splitting/merging, direction, defaults, height normalization and floor ownership are unambiguous; lineage maps remain complete. |
| 4 | v13 and v14 serializer prototypes | Validate target models in actual Foundry builds; choose supported import/link-remapping procedure; no source mutation. |
| 5 | Floor/portal/door authoring UI | Localized tools, undo/redo and current-format project persistence; separate explicit requirements before implementation. |
| 6 | Live integration matrix | GM and player checks for each supported core/module profile, asset alignment, visibility, doors and transitions. |

The future matrix must cover arbitrary combined restrictions and directions; all door/secret states; animation/audio/hinge orientation; wall splits/merges; null/equal/inverted heights and normalization; ordered holes/refill/disconnected Regions; rotated rectangles/ellipses/circles/polygons; disabled and cross-scene behaviors; v14 multi-destination fields; missing references; copied/new scene IDs; padding/offset/scale; native levels and occlusion; player confirmation and arrival height. Preserve original bytes and source lineage throughout. Current 13.351 observations establish a useful reference, not completion of those integration checks.

## Tile artwork evidence

The additional owner scene includes one locked Tile. Its screenshot mapping, transform/texture/occlusion fields, v13/v14 code differences and future extracted-PNG placement rules are documented in [the Tile probe](foundry-tile-format.md). Only the Tile collection and scene statistics changed from the first probe. Generation remains future work.
