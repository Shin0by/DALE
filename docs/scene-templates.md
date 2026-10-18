# Scene template library

Owner scope replacement2026-10-17 (ADR-020): DALE edits one scene image and its optional source contour JSON, repairs/joins/closes contours, cleans alpha and exports separate native RGBA PNGs for all connected closed objects or selected minimum cells. Every PNG filename includes its exact final width and height in pixels. Levels, wall/floor presets, composition, portals, native Scene export and Foundry runtime configuration are cancelled; the owner configures these manually in Foundry. Earlier plans are historical, not a backlog.

The following historical decisions/evidence do not authorize removed product features.

Planned update2026-10-17: ADR-011..014 supersede the prototype layout/bounds below. In Walls, segment double-click opens this standard editor prefilled from its linked shared preset or effective source/default properties. Existing-preset save updates its references; Save as new creates/assigns a fresh preset only to the clicked segment. Cancel changes nothing. Source-derived walls retain supported source properties until an explicit preset/reset operation. This is FR-070 planning, not implemented behavior.

Scene > Templates opens two blocks: Levels and Wall presets. The left editing toolbar remains visible, the active tool stays selected, and editing does not leave the Scene page. Explicit Contours/Regions/Raster section selection returns to Project. Each right page retains its common bottom Information block.

## Levels

Latest planned precision update(ADR-016 / FR-075): levels support signed0.01ft bounds, mandatory finite bottom, nullable unbounded top, default0.00/+infinity. UI uses two decimals/0.01 step; domain/payload use exact integer hundredths, with explicit bottom_centi_ft/top_centi_ft. Every derived object uses the entered level height exactly; no hidden floor offset or integer snap. Older whole-foot/schema2 behavior below describes the verified prototype.

Additional planned scope2026-10-17: separate shared FloorPreset definitions are required under ADR-015 / FR-072, with type-safe selected-floor assignment, standard metadata RGB selection and supported native rendering/occlusion/light/weather settings. They are edited in Project/current-level floor contents; Levels remains level-only and Walls retains wall presets. They have no image/placement/height/order. Planned template3/schema5 must include their current/history/redo definitions and references before release. The prototype description below is not an implementation claim for floor presets.

Add level opens Name, Bottom (ft), Top (ft), Color. Heights accept whole signed feet only: 0, 1, 2, 10, 100 are ordinary finite values; empty bottom means negative infinity and empty top means positive infinity. Store both empty limits as JSON null, never as zero or nonstandard Infinity. Two finite reversed limits are normalized into ascending order. RGB selection offers 16 suggested swatches and the full Qt RGB picker, with no alpha component.

Each rectangular card shows its name, interval, RGB swatch and eye. Double-click edits; Delete level deletes the selected definition. The eye persists visibility and controls a QGraphicsItemGroup for that stable level ID. Children follow the group visibility; the source image and unassigned contour/raster data stay visible. Groups are safely recreated after map replacement. The Walls page uses visibility to filter per-level wall instances. Asset groups are ready for future placed images; the source image remains unchanged.

## Wall presets

These are semantic Foundry wall definitions, separate from the editor's contour geometry. The owner explicitly allows Wall terminology here. Presets have names, icons and their own editable RGB colors (16 swatches/full RGB picker). They have no endpoints, source ancestry, placed object IDs, assigned level or height fields. A placed working wall obtains its height range from its level.

The [v13 BaseWall schema](https://foundryvtt.com/api/v13/classes/foundry.documents.BaseWall.html) and [v14 BaseWall schema](https://foundryvtt.com/api/v14/classes/foundry.documents.BaseWall.html) keep direction, movement, three sensory restrictions, doors, thresholds, sound and animation separate. The v14 schema additionally carries level membership; a template is not a native document or a level assignment.

| Editor field | Stored property | Choices |
| --- | --- | --- |
| Direction | dir | Both 0, Left 1, Right 2 |
| Movement | move | None 0, Normal 20 |
| Light / Sight / Sound | light / sight / sound | None 0, Limited 10, Normal 20, Proximity 30, Reverse proximity 40 |
| Distance | threshold.light / sight / sound | Nullable nonnegative distance in feet; field appears for 30/40 independently |
| Attenuation | threshold.attenuation | Boolean; distance attenuation is relevant to light/sight |
| Door type | door | None 0, Door 1, Secret 2 |
| State | ds | Closed 0, Open 1, Locked 2 |
| Door sound | doorSound | Always empty (None); no editable sound control |
| Animation | animation | Type, texture, flip, double, direction, duration, strength |

Door-specific fields appear when a door type is selected. Animation details appear for a nonempty animation type. Hidden fields keep their values when modes change. Restrictions remain independently editable; an unusual allowed combination is not rejected. Threshold values remain nullable, even in a proximity mode. See [Foundry's configuration guide](https://foundryvtt.com/article/walls/) for restriction behavior.

Animation choices include Ascend, Descend, Slide, Swing and Swivel, with an editable configuration key. Foundry exposes runtime [animationTypes and doorSounds registries](https://foundryvtt.com/api/v13/variables/CONFIG.Wall.html). The owner requires door sound to remain None; sensory sound restriction remains independent. No sound field or audio playback is offered.

Icons are independent visual labels: wall, two-pane opening window, locked opening window, full barred window, closed door, locked closed door, secret closed door and locked secret door. Barred windows have a full grille and no opening leaves. Door icons always show a closed leaf, including when the configured initial state is Open. Choosing an icon does not overwrite custom restriction settings; future scene generation must use the properties rather than infer semantics from artwork.

## Storage and transfer

DALE project schema 4 requires a checksummed templates.json member using dale-scene-templates schema 2. Reject older/unknown project and payload versions without migration. The library stores up to 256 levels and 1024 presets with unique 32-character hex IDs. Payload limit: 2 MiB. Names are limited to 128 characters; heights to whole feet in -1000000..1000000. Validate booleans, enums, finite numbers, fields and RGB values.

File > Import templates accepts only another current .dale project. It reads manifest.json and templates.json without extracting/decoding scene images, geometry, history, assignments or scene JSON. Imported definitions receive fresh IDs and append without replacing existing work. The input folder preference is retained. No standalone template export command exists.

Normal project save/load includes the definitions and visibility independently of numeric global settings. A template-only .dale can be saved before loading an image; closing still offers save/discard/cancel. Full scenes preserve shared definitions and per-level wall property operations. The Templates page edits definitions; the Walls page applies them to segments. See [per-level wall editing](wall-assignments.md). Native Foundry JSON generation remains future work.

## Wall display colors: Foundry versus DALE

Checked on 2026-10-17: both supplied Foundry 13.351 probe JSON documents have 12 walls each and no wall color field. The [v13 BaseWall schema](https://foundryvtt.com/api/v13/classes/foundry.documents.BaseWall.html#defineSchema) and [v14 WallData](https://foundryvtt.com/api/v14/interfaces/foundry.documents.types.WallData.html) have no ordinary wall color property. The v14 [CATEGORY_COLORS palette](https://foundryvtt.com/api/v14/classes/foundry.documents.BaseWall.html#CATEGORY_COLORS) supplies wall-category colors. The [v14 BaseWall schema](https://foundryvtt.com/api/v14/classes/foundry.documents.BaseWall.html#defineSchema) likewise has no per-wall color property. The renderer computes display color from wall properties through [Wall._getWallColor](https://foundryvtt.com/api/v13/classes/foundry.canvas.placeables.Wall.html#_getWallColor).

DALE preset color is editor metadata, stored as an RGB hex value in templates.json. Every segment assigned that preset uses its configured color, including immediately after template color edits. Icon choice does not override color or native wall settings. Do not invent a native Foundry wall color field or promise the DALE palette will appear in an unmodified Foundry editor. Custom module flags, Region colors and tile tints are separate concepts.
