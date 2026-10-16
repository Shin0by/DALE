# Project glossary

| Canonical term | Aliases | Meaning in DALE |
| --- | --- | --- |
| DALE | project, editor | Working project name; a local image preparation application. |
| Foundry VTT | Foundry, Фаундри | Foundry Virtual Tabletop, the target tabletop application. It hosts game scenes, maps, tokens, walls, visibility, lighting, and tabletop game systems. |
| Dungeon Alchemist | Alchemist, Алхимист | The map creation application that provides the source image and Foundry scene JSON. |
| Dungeons & Dragons | D&D, DND, ДНД | The tabletop role-playing game in the owner's use case. DALE image operations do not depend on a specific game system. |
| Ground-level map | base map, ground floor | Complete, unchanged map at the bottom of the intended floor stack. |
| Upper-floor overlay | floor overlay | Cropped native-resolution PNG with transparent terrain, aligned to the base map using recorded placement coordinates. |
| Terrain | ground, relief, рельеф, земля | Outdoor ground/background the owner wants to remove. It is a visual category, not a guaranteed field in the JSON. |
| Source wall | original line | Wall segment read from the source JSON, including door/window segments. Not the visible wall artwork itself. |
| Closure | temporary line, virtual closure | Editor-only polyline joining source walls to create closed mask regions. Never a new Foundry wall. |
| Closed face | enclosed region | Polygon formed by noded source walls and temporary closures. |
| Remove outside | keep interiors | Make pixels outside the union of closed faces transparent. |
| Remove inside | keep exterior | Make pixels inside the union of closed faces transparent. |
| Eraser | transparency brush | Circular brush that writes zero alpha without altering original RGB data. |
| Restore brush | restore | Restores source opacity in painted areas, including areas removed by a contour mask. |
| Snap | привязка | Project a cursor position onto the nearest original segment within a screen-space tolerance. |
| Image coordinates | native pixels | Original JPG pixel coordinates; authoritative coordinates for all edits and exports. |
| Scene coordinates | Foundry coordinates | Coordinates from the source scene; may require scale and origin/offset conversion. |
| Floor elevation | height, высота этажа | Intended vertical position in integer feet; presets are spaced 5 ft apart. Separate from pixel dimensions and grid size. |
| Scene Level | native level | Foundry 14's native per-scene level document; not the same as a v13 module's data. |
| Placement intent | PNG placement metadata | DALE's target version and elevation recorded in PNG text chunks; Foundry does not automatically apply these values. |
| Gap tolerance | join distance, допуск соединения | Maximum original-image distance for an automatic editor-only wall connection; 0 disables it. |
| T junction | Т-образное соединение | A wall endpoint meets, or lies near, the interior of another segment. |
| Contour offset | margin, отступ контура | Signed image-pixel expansion (positive) or contraction (negative) of the closed region. |
| Edge guard | export padding, запас 3 пикселя | Mandatory 3-source-pixel expansion beyond the effective contour for each cropped PNG; retains available source edge detail. |
| Point handle | drag circle, кружок | Circular 10-screen-pixel control for moving/deleting a working geometry vertex; its size is independent of zoom. |
| DALE project | .dale, проект | Self-contained ZIP archive with exact source assets, editing and redo history, geometry, placement, and UI settings. |
| Portable package | portable, портейбл | Complete `DALE/` runtime folder with executable and dependencies; launch without installing Python and move by copying the entire folder. |
| Placement manifest | placement.json | DALE export coordinate reference for cropped images; not a Foundry scene import document. |
