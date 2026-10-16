# Project glossary

## Naming policy

Use Scene / «сцена», Scene image / «изображение сцены», Scene JSON / «JSON сцены», and Contours / «контуры» in application labels, help and general workflow descriptions. JPG/JPEG is a supported file format, not the name of the asset. A scene JSON is a complete Foundry Scene document, not a contour-only file. A DALE project is the editor's `.dale` archive. Reserve native `walls`, `Wall`, field names and module titles for literal schema/API descriptions; never rename wire fields to match UI wording.

| Canonical term | Meaning |
| --- | --- |
| Scene | Foundry Scene document, including artwork references, gameplay documents, Regions and settings. |
| Scene image | Raster artwork associated with the Scene; currently imported as JPG/JPEG. |
| Scene JSON | Exported Foundry Scene document; can supply initial DALE contour segments through its native `walls` collection. |
| Contour | DALE editable line geometry, imported or manually created; not a claim that every segment is a gameplay barrier. |
| Tile | Foundry placed image/video document. Future extracted floor PNGs are Tile assets; a Tile alone does not define all floor behavior. Russian: «тайл». |

| Canonical term | Aliases | Meaning in DALE |
| --- | --- | --- |
| DALE | Dungeon Alchemist Levels Export, editor | Local image preparation application. Full name appears in the window title; the portable executable remains `DALE.exe`. |
| Foundry VTT | Foundry, Фаундри | Foundry Virtual Tabletop, the target tabletop application. It hosts game scenes, maps, tokens, walls, visibility, lighting, and tabletop game systems. |
| Dungeon Alchemist | Alchemist, Алхимист | The map creation application that provides the source image and Foundry scene JSON. |
| Dungeons & Dragons | D&D, DND, ДНД | The tabletop role-playing game in the owner's use case. DALE image operations do not depend on a specific game system. |
| Ground-level map | base map, ground floor | Complete, unchanged map at the bottom of the intended floor stack. |
| Upper-floor overlay | floor overlay | Cropped native-resolution PNG with transparent terrain, aligned to the base map using recorded placement coordinates. |
| Terrain | ground, relief, рельеф, земля | Outdoor ground/background the owner wants to remove. It is a visual category, not a guaranteed field in the JSON. |
| Source contour segment | imported line | Initial editable segment read from the scene JSON's native `walls` collection, including door/window records. Separate from scene image pixels and future gameplay semantics. |
| Auto-close | Автозамыкание | Cursor tool tracing reachable geometry and extending existing lines along their vectors to intersections. Uses its own screen-pixel distance; creates no standalone connectors. |
| Closed face | enclosed region | Polygon formed by noded contour segments. |
| Remove outside | keep interiors | Make pixels outside the union of closed faces transparent. |
| Remove inside | keep exterior | Make pixels inside the union of closed faces transparent. |
| Eraser | transparency brush | Circular brush that writes zero alpha without altering original RGB data. |
| Restore brush | restore | Restores source opacity in painted areas, including areas removed by a contour mask. |
| Snapping | Snap, прилипание | Project a cursor position onto existing working geometry within a screen-space distance, preferring vertices over segment interiors. The left tile is labeled "Snapping (px)" / "Прилипание (px)" through hover help. |
| Image coordinates | native pixels | Original JPG pixel coordinates; authoritative coordinates for all edits and exports. |
| Scene coordinates | Foundry coordinates | Coordinates from the source scene; may require scale and origin/offset conversion. |
| Floor elevation | height, высота этажа | Intended vertical position in integer feet; configured in Foundry; no visible height control in DALE. Separate from pixel dimensions and grid size. |
| Scene Level | native level | Foundry 14's native per-scene level document; not the same as a v13 module's data. |
| Placement intent | PNG placement metadata | DALE's target version and elevation recorded in PNG text chunks; Foundry does not automatically apply these values. |
| Gap tolerance | join distance, допуск соединения | Independent screen-pixel distance for directional local or whole-map contour repair. |
| T junction | Т-образное соединение | A contour endpoint meets, or lies near, the interior of another segment. |
| Contour offset | margin, отступ контура | Signed image-pixel expansion (positive) or contraction (negative) of the closed region. |
| Point handle | drag circle, кружок | Circular 10-screen-pixel control for moving/deleting a working geometry vertex; its size is independent of zoom. |
| DALE project | .dale, проект | Self-contained ZIP archive with exact source assets, editing and redo history, geometry, placement, and UI settings. |
| Portable package | portable, портейбл | Complete `DALE/` runtime folder with executable and dependencies; launch without installing Python and move by copying the entire folder. |
| Placement manifest | placement.json | DALE export coordinate reference for cropped images; not a Foundry scene import document. |
| Contours | Контуры | Tool set for working lines, points, snapping, and directional repair. |
| Regions | Области | Tool set for minimum-cell selection, geometry transforms, padding and selected export. |
| Raster | Растр | Pixel-alpha eraser, restore brush, and snapshot masks. |
| Lineage | ancestry, происхождение, наследование | Persistent edge/parent/source graph; distinct from unsupported legacy formats. |
| Source contour reference | JSON parent | Exact scene JSON SHA-256 plus original native /walls/index and optional Foundry ID. |
| Contact node | shared point | Geometric endpoint with incident line IDs and their parent/source references. |
| Minimum cell | selected region | Smallest polygonized closed face containing the cursor; independent of touching neighbors. |
| Artwork offset | image margin, Отступ изображения | Left Regions numeric tool, -4096..4096 source pixels; expands retained JPG artwork outside lines or cuts inward. Stored as contour_offset. No global transparent-padding parameter. |
| Alpha bounds | visible pixel box | Smallest pixel rectangle containing every nonzero final alpha byte after bicubic smoothing, including 1/255. Clipped to the JPG extent. |
| JSON catalog | document list | Declared immutable original/updated JSON members within a current .dale package. |
| Rotate regions | Вращение областей | Separate Regions tool; ordinary wheel rotates geometry 0.1 degree per notch about common center. |
| Foundry Region | Scene Region | Explicit composite shapes, one elevation interval and behaviors; distinct from DALE extraction cells and native Scene Levels. |
| Teleport portal | teleportToken, портал | Directed Region-to-Region behavior identified by destination UUID; distinct from an ordinary/secret wall door. |
| Wall Height | wall-height | Foundry module namespace for wall top/bottom and related vision settings; not a core v13 floor model. |
| Height normalization | wall bound normalization | Preserve original values, optionally order finite wall bounds as bottom=min and top=max in working/generated data. Null remains unbounded. |
