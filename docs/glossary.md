# Project glossary

| Canonical term | Aliases | Meaning in DALE |
| --- | --- | --- |
| DALE | Dungeon Alchemist Levels Export, project, editor | Local image preparation application. Full name appears in the window title; the portable executable remains `DALE.exe`. |
| Foundry VTT | Foundry, Фаундри | Foundry Virtual Tabletop, the target tabletop application. It hosts game scenes, maps, tokens, walls, visibility, lighting, and tabletop game systems. |
| Dungeon Alchemist | Alchemist, Алхимист | The map creation application that provides the source image and Foundry scene JSON. |
| Dungeons & Dragons | D&D, DND, ДНД | The tabletop role-playing game in the owner's use case. DALE image operations do not depend on a specific game system. |
| Ground-level map | base map, ground floor | Complete, unchanged map at the bottom of the intended floor stack. |
| Upper-floor overlay | floor overlay | Cropped native-resolution PNG with transparent terrain, aligned to the base map using recorded placement coordinates. |
| Terrain | ground, relief, рельеф, земля | Outdoor ground/background the owner wants to remove. It is a visual category, not a guaranteed field in the JSON. |
| Source wall | original line | Wall segment read from the source JSON, including door/window segments. Not the visible wall artwork itself. |
| Auto-close | Автозамыкание | Cursor tool tracing reachable geometry and extending existing lines along their vectors to intersections. Uses its own screen-pixel distance; creates no standalone connectors. |
| Closed face | enclosed region | Polygon formed by noded source walls and temporary closures. |
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
| T junction | Т-образное соединение | A wall endpoint meets, or lies near, the interior of another segment. |
| Contour offset | margin, отступ контура | Signed image-pixel expansion (positive) or contraction (negative) of the closed region. |
| Edge guard | export padding, запас 3 пикселя | Mandatory 3-source-pixel expansion beyond the effective contour for each cropped PNG; retains available source edge detail. |
| Point handle | drag circle, кружок | Circular 10-screen-pixel control for moving/deleting a working geometry vertex; its size is independent of zoom. |
| DALE project | .dale, проект | Self-contained ZIP archive with exact source assets, editing and redo history, geometry, placement, and UI settings. |
| Portable package | portable, портейбл | Complete `DALE/` runtime folder with executable and dependencies; launch without installing Python and move by copying the entire folder. |
| Placement manifest | placement.json | DALE export coordinate reference for cropped images; not a Foundry scene import document. |
| Contours | Контуры | Tool set for working lines, points, snapping, and directional repair. |
| Regions | Области | Tool set for minimum-cell selection, geometry transforms, padding and selected export. |
| Raster | Растр | Pixel-alpha eraser, restore brush, and snapshot masks. |
| Lineage | ancestry, происхождение, наследование | Persistent edge/parent/source graph; distinct from unsupported legacy formats. |
| Source wall reference | JSON parent | Exact JSON SHA-256 plus original /walls/index and optional Foundry ID. |
| Contact node | shared point | Geometric endpoint with incident line IDs and their parent/source references. |
| Minimum cell | selected region | Smallest polygonized closed face containing the cursor; independent of touching neighbors. |
| Extra export padding | additional box margin | Transparent space beyond mandatory 3px; every bound is clipped to source JPG. |
| JSON catalog | document list | Declared immutable original/updated JSON members within a current .dale package. |
