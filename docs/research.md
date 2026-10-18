# External research

Owner scope replacement2026-10-17 (ADR-020): DALE edits one scene image and its optional source contour JSON, repairs/joins/closes contours, cleans alpha and exports separate native RGBA PNGs for all connected closed objects or selected minimum cells. Every PNG filename includes its exact final width and height in pixels. Levels, wall/floor presets, composition, portals, native Scene export and Foundry runtime configuration are cancelled; the owner configures these manually in Foundry. Earlier plans are historical, not a backlog.

The following historical decisions/evidence do not authorize removed product features.

Latest owner scope2026-10-17(ADR-018): portal authoring/generation is cancelled. No Portals UI, authored portal records, links, behaviors or importer scripts will be implemented. The owner creates/links portals manually in Foundry after import. Preserve native source JSON bytes; floor Regions, floors/walls/lights/background and0.01ft level heights remain in scope. Earlier portal-specific research is historical.


Light-transfer scope update2026-10-17: the owner selected source wall-setting preservation and requires Dungeon Alchemist lights on the initial default level. The [v13 AmbientLight schema](https://foundryvtt.com/api/v13/classes/foundry.documents.BaseAmbientLight.html) confirms XY, elevation, config, hidden and wall/vision fields; [LightData](https://foundryvtt.com/api/v13/classes/foundry.data.LightData.html) describes the separate light configuration. Legacy bright/dim/tint fields need deliberate conversion. This adds planned light transfer, not a live import claim.

## Scope and evidence update: 2026-10-17

Required work is now additive level composition, a complete native Foundry package and authored portals (ADR-011..013), with application implementation explicitly stopped. First target is Foundry13 + Wall Height; the owner will add that module and has not accepted Levels. The six Dungeon Alchemist image/JSON pairs are conversion inputs, while the two fvtt-Scene-test exports are native target examples from core13.351/dnd5e5.3.3. The owner confirms the sample portals worked. The sample core version does not identify a current installation or module build.

Read-only reinspection reproduces both indexed hashes and identical regions arrays; only tiles/_stats differ. This corroborates the existing atlas rather than replacing it. Native Region.color, polygon geometry, directed destinations and per-source choice have direct local evidence. The [v13 Region schema](https://foundryvtt.com/api/v13/classes/foundry.documents.BaseRegion.html) and [v13 TeleportToken schema](https://foundryvtt.com/api/v13/classes/foundry.data.regionBehaviors.TeleportTokenRegionBehaviorType.html) were rechecked for these fields. The [official Regions guide](https://foundryvtt.com/article/scene-regions/) describes user choice and destination Regions. No additional portal module is implied. Wall-height bounds are flags in the scene probe; the additional Tile's elevation20 is an explicit vertical coordinate, distinct from its500-pixel image height.

Remaining generated-output evidence: native same-scene link handling when importing into a differently identified empty Scene, destination elevation/retrigger/confirmation behavior of generated portals, and stacked-floor visibility in the chosen v13 profile. The public teleport schema has no explicit arrival-height field. Do not erase owner-reported successful source behavior by labeling these different questions as proof that the source portals are unsupported. Private files remain local and unchanged.

Checked: 2026-10-16. Sources below are official product documentation unless otherwise marked. These observations inform requirements; they do not establish support for an untested export variant.

## Foundry VTT

Foundry is a virtual tabletop for running role-playing games. Scenes combine map imagery with gameplay objects and visibility. Walls, tokens, lighting, grid measurements, and fog participate in play; image preparation alone does not assemble the complete scene. See [Foundry](https://foundryvtt.com/), [Scenes](https://foundryvtt.com/article/scenes/), and [Canvas Layers](https://foundryvtt.com/article/canvas-layers/).

There is no universal image dimension. Foundry's [scene loading troubleshooting](https://foundryvtt.com/article/ts-scene-loading/) explains that the source texture is limited by client hardware, roughly 8,000 pixels per axis on older PCs and 16,000 on newer PCs. DALE's 8,192 warning and 16,384 support target are engineering thresholds, not a Foundry-wide guarantee. Every player's hardware matters.

[Scene configuration](https://foundryvtt.com/article/scenes/) uses image dimensions and grid size in pixels. The documented default grid is 100 pixels, minimum 50. There is no mandatory JPG width or height. Foreground imagery should have the same dimensions as the background. Padding and background offsets affect coordinate alignment; the [v14 SceneDimensions API](https://foundryvtt.com/api/v14/interfaces/foundry.documents.types.SceneDimensions.html) distinguishes the scene rectangle origin (`sceneX`, `sceneY`) from the outer canvas.

[Media Optimization](https://foundryvtt.com/article/media/) documents PNG transparency and the larger transfer size of large PNG imagery. PNG is retained here because alpha transparency is an explicit product requirement. DPI is not the working unit for alignment; pixel dimensions are.

## Dungeon Alchemist

[Dungeon Alchemist's official import guide](https://www.dungeonalchemist.com/import-to-foundry) describes a JSON scene import for walls and lighting, followed by choosing the exported JPG or video as background. This supports separating image editing from scene data and preserving source JSON. Its [product site](https://www.dungeonalchemist.com/) describes map generation and orthographic, perspective, and 3D views. Top-down samples should be evaluated first because perspective artwork may extend beyond logical wall footprints.

The official guide does not establish a complete stable JSON schema or provide terrain segmentation. Real sample inspection remains necessary. Do not infer semantic terrain labels from the presence of wall and lighting data.

## Foundry 13 and 14 placement

The owner requires both generations. The [v13 Tile model](https://foundryvtt.com/api/v13/classes/foundry.documents.BaseTile.html) and [v14 Level model](https://foundryvtt.com/api/v14/classes/foundry.documents.BaseLevel.html) are separate data models. The [v14 stable release notes](https://foundryvtt.com/releases/14.359) introduce native Scene Levels. A single raster PNG can serve both generations, while floor visibility and scene document configuration differ. The prototype therefore preserves target/elevation as DALE metadata and provides distinct guidance; it does not claim that a PNG can place itself at an elevation or that setting tile elevation alone assembles a multi-floor scene.

## Implementation references

- [Qt QGraphicsView](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QGraphicsView.html): local 2D canvas, transforms, and scene input.
- [Shapely polygonize_full](https://shapely.readthedocs.io/en/stable/reference/shapely.polygonize_full.html): bounded polygons and unresolved geometry diagnostics.
- [Pillow Image API](https://pillow.readthedocs.io/en/stable/reference/Image.html): image opening, JPEG decoder reduction, raster manipulation, and pixel-count protections.
- [PyInstaller operating mode](https://pyinstaller.org/en/stable/operating-mode.html) and [usage](https://pyinstaller.org/en/stable/usage.html): bundle the interpreter and application dependencies for users without Python; validate a directory bundle before considering a single-file variant.

## Validation still required

The independent owner scene probe identifies Foundry **13.351**, dnd5e **5.3.3**, 12 walls, 9 Regions and 4 teleport behaviors. Its detailed [field atlas](foundry-scene-format.md) separates observed records from official-schema interpretation, module flags and untested runtime behavior. The [export design](foundry-export-feasibility.md) compares v13/v14, including native Levels and changed teleport fields. The [machine profile](../project/foundry-format-profile.json) provides counts, paths, aliases and evidence for agent navigation. Semantic export remains future work.

Confirm exact owner builds for the requested Foundry 13/14 targets, JSON coordinate conventions, background offsets, and floor workflows. Verify cropped transparent PNG placement using recorded source/scene positions on the owner's actual Foundry clients. Successful synthetic tests do not establish this external validation.

The six supplied real pairs have now been inspected for image dimensions, zero offsets/padding, wall/light layout, day/night geometry equality, and contour topology. Their observed legacy-style field layout is documented in [the sample profile](sample-formats.md), with an official v9 scene-model comparison and a v13 wall-schema comparison. Real-image import/preview and one full-resolution PNG export have passed; live Foundry placement remains untested.
