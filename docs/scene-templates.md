# Scene template library

Scene > Levels opens two blocks: Levels and Wall presets. The left editing toolbar remains visible, the active tool stays selected, and editing does not leave the Scene page. Explicit Contours/Regions/Raster section selection returns to Project. Each right page retains its common bottom Information block.

## Levels

Add level opens Name, Bottom (ft), Top (ft), Color. Heights accept whole signed feet only: 0, 1, 2, 10, 100 are ordinary finite values; empty bottom means negative infinity and empty top means positive infinity. Store both empty limits as JSON null, never as zero or nonstandard Infinity. Two finite reversed limits are normalized into ascending order. RGB selection offers 16 suggested swatches and the full Qt RGB picker, with no alpha component.

Each rectangular card shows its name, interval, RGB swatch and eye. Double-click edits; Delete level deletes the selected definition. The eye persists visibility and controls a QGraphicsItemGroup for that stable level ID. Children follow the group visibility; the source image and unassigned contour/raster data stay visible. Groups are safely recreated after map replacement. Actual scene-object assignment to levels is future work, so new groups initially contain no placed assets.

## Wall presets

These are semantic Foundry wall definitions, separate from the editor's contour geometry. The owner explicitly allows Wall terminology here. Presets have no endpoints, source ancestry, placed object IDs, assigned level or height fields. A future placed wall obtains height from its assigned level.

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
| Sound | doorSound | Empty or user-entered Foundry configuration key |
| Animation | animation | Type, texture, flip, double, direction, duration, strength |

Door-specific fields appear when a door type is selected. Animation details appear for a nonempty animation type. Hidden fields keep their values when modes change. Restrictions remain independently editable; an unusual allowed combination is not rejected. Threshold values remain nullable, even in a proximity mode. See [Foundry's configuration guide](https://foundryvtt.com/article/walls/) for restriction behavior.

Animation choices include Ascend, Descend, Slide, Swing and Swivel, with an editable configuration key. Sound keys are editable rather than an invented fixed catalog: Foundry exposes runtime [animationTypes and doorSounds registries](https://foundryvtt.com/api/v13/variables/CONFIG.Wall.html), which modules may extend. No audio asset playback or Foundry runtime registry query is implemented.

Icons are independent visual labels: wall, two-pane opening window, locked opening window, full barred window, closed door, locked closed door, secret closed door and locked secret door. Barred windows have a full grille and no opening leaves. Door icons always show a closed leaf, including when the configured initial state is Open. Choosing an icon does not overwrite custom restriction settings; future scene generation must use the properties rather than infer semantics from artwork.

## Storage and transfer

DALE project schema 3 requires a checksummed templates.json member. Schema 2 and older/unknown versions are rejected; there is no migration or legacy loader. The library stores up to 256 levels and 1024 presets with unique 32-character hex IDs. Payload limit: 2 MiB. Names are limited to 128 characters; heights to whole feet in -1000000..1000000. All booleans, enum values, finite numbers, field sets and RGB values are validated.

The same payload can be exported separately as JSON:

```json
{
  "format": "dale-scene-templates",
  "schema_version": 1,
  "levels": [],
  "wall_presets": []
}
```

Import templates accepts this JSON or a current .dale project. Reading a project imports only manifest.json and templates.json, validates the template hash, and never extracts/decodes source images, geometry, history or JSON scene documents. Import appends definitions with fresh IDs and preserves existing definitions; it does not replace scene data. Export contains no placed objects, source files or private instance settings. Writes are atomic and may not overwrite the active project or imported sources. Input/output directories follow the existing independent folder preferences.

Project save/load includes definitions and visibility independently of global numeric-tool settings. Template-only work without a scene image can be saved/exported as JSON; closing asks save/discard/cancel when changed. Template edits are tracked for unsaved-change detection; contour/raster undo history remains separate. No native Foundry scene generation or assignment tool is claimed by this library feature.
