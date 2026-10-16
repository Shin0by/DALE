# External research

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

## Validation still required

Confirm exact owner builds for the requested Foundry 13/14 targets, JSON coordinate conventions, background offsets, actual export dimensions, and floor workflows. Verify identical-size transparent PNGs on the owner's actual Foundry clients. The initial implementation must not equate successful synthetic tests with this external validation.

The six supplied real pairs have now been inspected for image dimensions, zero offsets/padding, wall/light layout, day/night geometry equality, and contour topology. Their observed legacy-style field layout is documented in [the sample profile](sample-formats.md), with an official v9 scene-model comparison and a v13 wall-schema comparison. Real-image import/preview and one full-resolution PNG export have passed; live Foundry placement remains untested.
