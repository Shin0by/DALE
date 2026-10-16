# Foundry scene Tile probe

Checked 2026-10-16. Research and future export design; no native scene/Tile generator is implemented here. A Tile is a placed scene image/video document. The correct Russian term is «тайл», not «тайтл». Contours remain DALE editing geometry; a scene JSON contains much more than that geometry.

## Evidence

The owner supplied `examples/fvtt-Scene-test-2WsAkxPbpDPmK2o4 (1).json` and three screenshots of the Tile configuration. The UTF-8 file is 21,593 bytes, SHA-256 `f225fcaf1f9aae25226c23ff48e558d3eeec9dac5fd7b7d09a0cd91122ab0738`. Its declared core/system are Foundry 13.351 / dnd5e 5.3.3. Source images and JSON remain local and unchanged. Tile `T0` below means `/tiles/0`; private document IDs and the character asset path are omitted.

Compared with the previous 20,764-byte probe, only `/tiles` and `/_stats` changed. The new scene has one Tile; the 12 native `walls` records, 9 Regions, one Token and two Drawings are unchanged. The base scene still has width 4000, height 3000, padding 0.25 and a 100 px / 5 ft grid. This is one added object, not a replacement geometry test.

The field inventory matches the [v13 BaseTile schema](https://foundryvtt.com/api/v13/classes/foundry.documents.BaseTile.html). Public v13 API pages identify 13.350, one patch before the supplied export; the file and screenshots are the evidence for 13.351 values. The [v13 TileData reference](https://foundryvtt.com/api/v13/interfaces/foundry.documents.types.TileData.html) describes pixel dimensions, top-left position, elevation, opacity and ordering.

## Screenshot-to-JSON correspondence

Paths in this table are relative to `/tiles/0`. Values come directly from the supplied file; screenshot labels identify the controls.

| Configuration control | JSON path | Observed value | Interpretation |
| --- | --- | --- | --- |
| Position: X / Y | `/x`, `/y` | 3200, 1300 | Nominal scene-pixel position. |
| Size: width / height | `/width`, `/height` | 900, 500 | Image display rectangle in pixels; height here is not vertical elevation. |
| Rotation (degrees) | `/rotation` | 10 | Tile rotation, separate from texture rotation. |
| Elevation (ft) | `/elevation` | 20 | Vertical position in this scene's units (`ft`). |
| Sort | `/sort` | 5 | Draw ordering, not a floor number. |
| Image or video | `/texture/src` | Relative `.png` asset path | Reference to a Foundry-accessible asset; image bytes are not embedded. |
| Texture scale: horizontal / vertical | `/texture/scaleX`, `/texture/scaleY` | 1, 1 | Neutral texture scaling. Preserve signed values if other valid scenes use mirroring. |
| Tile opacity | `/alpha` | 1 | Normal display opacity. PNG per-pixel alpha is separate. |
| Tint | `/texture/tint` | `#ffffff` | Neutral white tint. |
| Occlusion mode: None (always visible) | `/occlusion/mode` | 0 | No occlusion mode selected. |
| Occlusion opacity | `/occlusion/alpha` | 0 | Opacity used when occluded; it does not make normal `/alpha:1` invisible. |
| Restricts light | `/restrictions/light` | true | Enabled light restriction setting. |
| Restricts weather | `/restrictions/weather` | true | Enabled weather restriction setting. |
| Locked (owner enabled) | `/locked` | true | Editing interaction lock. Independent of visibility and gameplay collision. |
| Hidden | `/hidden` | false | Separate visibility flag; the Tile is not hidden. |

The three screenshots do not show the lock toggle, but the owner's report and `/locked:true` agree. Locking is an editor interaction safeguard, not immutability of the JSON. The [official Tiles guide](https://foundryvtt.com/article/tiles/) distinguishes lock, visibility, elevation and sort. That guide currently describes v14, so its newer UI must not override the supplied v13 screenshot/serialization.

The Overhead tab stores `occlusion` and `restrictions`; this sample has no separate `overhead` boolean. Preserve the demonstrated combination of mode 0, occlusion alpha 0 and both restrictions enabled. Do not reject it or silently switch settings to a floor preset. The [v13 occlusion model](https://foundryvtt.com/api/v13/interfaces/foundry.documents.types.TileOcclusionData.html) and [restriction model](https://foundryvtt.com/api/v13/interfaces/foundry.documents.types.TileRestrictionsData.html) confirm these independent fields. Their actual visual interaction still needs a live scene test.

## Additional serialized values

| JSON path | Observed value | Evidence/handling |
| --- | --- | --- |
| `/_id` | Present, 16-character ID | Preserve for an existing object; allocate/remap for a new Tile. Never reuse this probe's ID as a template. |
| `/texture/anchorX`, `/texture/anchorY` | 0.5, 0.5 | Centered texture anchor; not shown in the screenshots. Preserve explicitly. |
| `/texture/offsetX`, `/texture/offsetY` | 0, 0 | Neutral texture offsets. |
| `/texture/fit` | `fill` | Texture fitting rule. |
| `/texture/rotation` | 0 | Texture itself is unrotated relative to the Tile; `/rotation:10` is different. |
| `/texture/alphaThreshold` | 0.75 | Observed field, absent from the supplied configuration screenshots. Preserve; exact hit/occlusion threshold behavior needs runtime verification. It is not DALE's alpha crop threshold. |
| `/video/loop`, `/video/autoplay`, `/video/volume` | true, true, 0 | Serialized video defaults even though the asset is a PNG. No playback is implied. |
| `/flags` | `{}` | No demonstrated module-specific Tile settings. Preserve unknown flags in future imports. |

These texture fields are consistent with the extensible [TextureData model](https://foundryvtt.com/api/v13/classes/foundry.data.TextureData.html), but not every additional field's behavior is explained by its public schema summary. Do not infer the referenced PNG's native dimensions or alpha content from a 900×500 Tile rectangle; the asset was not supplied for this probe.

## Foundry 13 and 14 differences

The [v14 BaseTile schema](https://foundryvtt.com/api/v14/classes/foundry.documents.BaseTile.html) adds `name` and a native `levels` set compared with v13. A future serializer must author/remap Level references, not copy numeric elevation into a Level ID. An actual owner v14 Tile/Level export and live import checks remain missing. Interface summaries also differ in how they describe origins/anchors, so verify the target coordinate transform against exports/runtime.

Occlusion codes are version-sensitive. Published [v13 constants](https://foundryvtt.com/api/v13/variables/CONST.TILE_OCCLUSION_MODES.html) give NONE=0, FADE=1, RADIAL=3, VISION=4. Published [v14 constants](https://foundryvtt.com/api/v14/variables/CONST.TILE_OCCLUSION_MODES.html) give NONE=0, FADE=1, SURFACE=2, RADIAL=4, VISION=8. The current guide allows multiple v14 modes. Store semantic mode names internally and serialize for the explicit target; never copy a v13 numeric mode directly into v14. The present mode 0 is common, but proves no nonzero conversion.

## Future PNG floor placement

The owner's intended floor artwork carrier is a Tile referencing a PNG extracted from selected DALE regions. A Tile supplies positioned artwork; explicit elevation/Level, visibility, contour gameplay semantics and teleport behavior still require separate configuration.

1. Export each selected region as its exact native RGBA crop. Keep every nonzero smoothed alpha pixel; clip only to the source scene image. Record crop origin and dimensions. Preserve the source scene JSON and store the future generated scene as a separate updated catalog document.
2. Resolve the source-image-to-Foundry-scene transform, including background offsets, scale and padded canvas origin. For the already resolved transform used by `placement.json`, assign Tile x/y from scene_x/scene_y and width/height from scene_width/scene_height. Do not use the preview zoom or nominal source file's pixel density as a guess.
3. For a new aligned crop, the proposed neutral artwork template uses Tile rotation 0, texture scale 1, offsets/texture rotation 0, white tint, alpha 1 and hidden false. The owner-confirmed locked true prevents accidental movement. Do not apply a Tile rotation to raster that was already transformed, or it will rotate twice. Existing objects retain their own values rather than being reset to this template.
4. Allocate a stable Tile identity linked to DALE region/floor/crop identity. Use a path under the selected Foundry asset destination; `.dale` member paths and Windows absolute paths are not Foundry asset URLs. Deliver PNG assets with a scene JSON that references them; JSON alone cannot transport the image.
5. Assign the intended vertical elevation in scene units and deterministic sort order. v13 module-floor behavior and v14 native Level membership are distinct target profiles. Do not label a Tile or its sort number as a complete floor model.
6. Make occlusion/light/weather policy explicit. Preserve imported combinations; verify the chosen floor appearance with player vision, transparent holes and tokens above/below. Keep `texture.alphaThreshold` separate from PNG antialiasing; never discard 1/255 PNG pixels because this sample uses 0.75 for another setting.

For this probe the nominal unrotated rectangle is `[3200,1300,4100,1800]`, centered at `[3650,1550]`. It extends beyond the scene's nominal width 4000 while padding is 0.25. Accept the supplied values; do not clamp imported Tile coordinates to nominal scene bounds. Rotation also changes rendered coverage. Exact padded-canvas alignment remains a live-validation requirement.

Acceptance evidence for the future generator: fresh Tile IDs, working asset paths, source/crop alignment at several scales, lock/unlock, negative/zero/positive elevation, sort overlap, native v14 membership, neutral and mirrored textures, rotated imports, hidden/opacity/occlusion independence, all version-specific occlusion modes, transparent holes/edge alpha, light/weather and preservation of unrelated scene documents. This analysis does not yet generate or import a native Foundry scene.
