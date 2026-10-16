# Observed Dungeon Alchemist export format

Inspected on 2026-10-16. Scope: six private JPG + JSON pairs supplied under `examples/`, representing day/night variants of three source layers. This is a compatibility profile for these files, not a complete Dungeon Alchemist format specification. Original files and derived image previews remain local and ignored by Git.

## Raster and common canvas

All six JPGs are baseline RGB JPEGs at **13,500 × 16,200 pixels**, with 4:2:0 chroma subsampling and a 300 × 300 DPI header. No EXIF orientation transform or embedded ICC profile was found. File sizes range from 31,878,530 to 50,156,185 bytes. The DPI header is print metadata; actual alignment uses pixel dimensions and the JSON grid.

Each JSON declares the exact same image dimensions, a **300-pixel grid**, a distance of **5 ft** per grid space, zero padding, and zero `shiftX`/`shiftY`. The canvas is therefore **45 × 54 grid cells**, or **225 × 270 ft**. DALE's scene-to-image transform is identity for these inputs. All wall and light coordinates are within their image canvas. Representative wall overlays were visually inspected on ground, upper, and roof-like daytime variants at overview resolution. Pixel-edge extraction precision and placement in a live Foundry scene are separate checks.

The image dimensions fit DALE's 16,384-per-side limit, with only 184 pixels of headroom on the long side. The existing 8,192 compatibility warning applies. Do not silently downscale or crop individual floors. If a future lower-resolution workflow is added, resize imagery and scene coordinates together across all floors.

## Layer inventory and topology

Source suffix spelling `outsude` is preserved. It is a file label; it does not declare a numerical elevation. Visual inspection shows roof artwork in this variant, but its intended elevation must still be chosen by the owner.

| Source layer suffix | Walls | Doors (`door=1`) | Lights: day / night | Closed faces at zero tolerance | Unresolved segments at zero tolerance |
| --- | ---: | ---: | ---: | ---: | ---: |
| `ground` | 207 | 22 | 31 / 62 | 18 | 52 |
| `lvl2` | 50 | 1 | 5 / 7 | 1 | 14 |
| `outsude` | 27 | 0 | 0 / 4 | 2 | 25 |

Closed faces are geometric regions, not building/floor counts. Unresolved segments are measured after intersection noding, not simply counted from the JSON. In each corresponding day/night pair, the complete wall arrays are identical; the JSON differences are exactly `name`, `lights`, and `darkness`. Day darkness is 0.0, night darkness is 0.6, and `globalLight` is true in all six files. This supports future reuse of a geometry mask across matching day/night variants, but persistent mask reuse is not implemented yet.

At zero gap tolerance, the union of closed faces covers approximately 9.7956% of the ground image, 3.0165% of `lvl2`, and only 0.0073% of `outsude`. The two tiny roof-layer faces do **not** outline the roof. Selecting Remove outside on that layer without repair would discard most visible roof artwork. Some image roofs and outdoor objects have no matching boundary in that layer's JSON.

Several ground/roof free endpoints are 3 pixels apart. Other gaps and T-junction separations are larger. A small numerical tolerance is useful but is not a semantic building-outline detector. With the implemented join policy, 3 px produces 16 joins on `ground`, 2 on `lvl2`, and 3 on `outsude`; this still does not recover the missing roof boundary. At 12 px the upper-floor enclosed area grows from 6,597,036 to approximately 7,146,779 pixels. Review the preview before choosing a tolerance; a higher value can also join intentional openings.

## JSON structure

The files contain one scene object each, encoded as JSON, without embedded image bytes, native Scene Levels, per-floor elevation, object segmentation, terrain masks, schema version, or a Foundry build marker.

| Field or group | Observed representation | DALE implication |
| --- | --- | --- |
| `width`, `height` | Integer image dimensions | Native map coordinate extent. |
| `grid` | Integer `300`, not an object | Legacy-style scene profile; do not assume `grid.size`. |
| `gridDistance`, `gridUnits` | `5.0`, `"ft"` | Keep scene units separate from image pixels and export elevation. |
| `shiftX`, `shiftY`, `padding` | Zero | No offset correction needed for these inputs. Nonzero legacy shifts remain unverified. |
| `img`, `foreground` | `null` | Select the sibling JPG by filename; the image is not in the JSON. |
| `walls[]` | Objects with `c`, `move`, `sense`, `sound`, `door` | Geometry is available independently of legacy gameplay semantics. |
| `walls[].c` | Four integer values `[x1, y1, x2, y2]` | Each entry is a line segment, not an ordered polygon vertex list. |
| `walls[].sense` | Values 0, 1, or 2 | Preserve all segments, including `sense=0`; this is not an object/terrain classification. |
| `walls[].door` | Values 0 or 1 | Door segments can participate in extraction boundaries. |
| `lights[]` | `x`, `y`, `bright`, `dim`, `tintAlpha`, `tintColor` | Preserve original records; image extraction does not need to rewrite lighting. |
| Scene appearance | `gridColor`, `gridAlpha`, `globalLight`, `darkness` | Keep separate from alpha-mask operations. |

Calling this a legacy-style profile is an inference from the field layout, supported by the official [v9 SceneData reference](https://foundryvtt.com/api/v9/data.SceneData.html). It does not date the Dungeon Alchemist application that produced the files. The modern [v13 Wall model](https://foundryvtt.com/api/v13/classes/foundry.documents.BaseWall.html) uses separate `sight`/`light` restriction fields rather than the observed `sense` field. A future scene exporter must migrate the actual schemas and enumeration values and account for v14 Level documents; changing an image path or height alone is not a complete JSON conversion. Native Foundry import/migration has not been tested here.

## Contour settings confirmed by owner feedback

- **Join gaps up to (px)**: original-image distance, default 0 (disabled), range 0–4,096 with hundredth-pixel input. Node exact intersections first. Prefer nearby free endpoint pairs, then connect remaining ends to the nearest eligible segment, including its interior for T junctions. Use deterministic local bridges; do not chain an endpoint through multiple automatic joins. Generated joins remain editor-only and follow the same cyan-closed/red-open classification as other lines.
- **Contour offset (px)**: signed integer pixels, range -4,096 through 4,096. Union the closed faces, then buffer outward for positive values or inward for negative values, using mitered corners. Show the effective boundary as dashed cyan. A positive offset retains more pixels for Remove outside and removes more for Remove inside. A fully eliminated inward region is rejected.
- Settings update contour previews immediately. Applied masks remain snapshots; undo an old mask and apply again to replace its result. Changing the numbers alone does not mutate an already applied mask or the source JSON. Zoom does not affect the numerical distances.

## Real-image export check

The daytime `lvl2` image was decoded and exported through the existing stripe-based pipeline at **13,500 × 16,200**. The result was RGBA PNG with verified inside/outside alpha, recorded placement metadata, and unchanged source JPG/JSON SHA-256 hashes. Runtime on the current machine was 24.32 seconds. This checks the raster pipeline using the uncorrected existing contour, not a finished upper-floor asset or live Foundry placement.

The original full-canvas output was **680,799,171 bytes** (about 649 MiB), because that encoder retained RGB under fully transparent pixels. This was a historical pipeline check; the current encoder zeroes RGB only where alpha is zero and restores edits from the unchanged source image.

The current default was checked separately on the same upper-floor source: one cropped **3,451 × 3,523** PNG, **15,510,058 bytes**, **1.36 seconds**, with the mandatory 3-pixel guard and placement manifest. A self-contained `.dale` archive was **49,828,685 bytes**, including exact JPG/JSON and history. These use the existing incomplete contour, not a finished floor or a Foundry import test. Private results remain under ignored `artifacts/sample-analysis/`.

## Reproduce locally

```powershell
.\.venv\Scripts\python.exe tools/inspect_examples.py --previews
.\.venv\Scripts\python.exe tools/inspect_examples.py --previews --verify-export village-ruin-day-lvl2
```

The tool writes metadata, source hashes, endpoint distances, gap-tolerance scans, and optional wall-overlay previews under ignored `artifacts/sample-analysis/`. The export verification is optional because it writes a large PNG. Never commit these local diagnostics or the private source maps.
