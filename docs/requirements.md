# Product requirements

Status: owner intent captured on 2026-10-16. Implementation status is recorded in `project/state.json`; acceptance criteria below are targets, not claims of completed validation.

## Outcome

Prepare aligned floor assets for a Foundry VTT map: one complete ground-level image and multiple upper-floor PNGs with transparent terrain. The owner supplies exported JPG + JSON pairs from Dungeon Alchemist and controls development through chat. DALE is an independent local desktop editor, not a game system or a Foundry module.

## Functional requirements

| ID | Requirement | Acceptance criterion |
| --- | --- | --- |
| FR-001 | Import a JPG/JPEG and its Foundry scene JSON. | Decode the image, validate supported JSON fields, show dimensions and actionable errors, and retain original files unchanged. |
| FR-002 | Display the map with wall lines from JSON. | Support zoom, pan, fit-to-view, and a wall visibility toggle; walls remain aligned in image coordinates. |
| FR-003 | Remove ground using wall-defined regions. | Offer Remove outside and Remove inside, preview transparency, and retain exact canvas size. No closed face must produce a repair prompt, not an empty accidental export. |
| FR-004 | Diagnose open contours. | Highlight unresolved segments; explain that a temporary closure can form a usable region. Require explicit review before applying a mask when unresolved geometry remains. |
| FR-005 | Draw temporary closure polylines. | In Closure mode, a plain first click snaps to the nearest source segment; Ctrl-click or Alt-click adds free vertices; a plain final click snaps to a source segment. Snap works on segment interiors as well as endpoints. Escape cancels an unfinished path. |
| FR-006 | Keep closures out of Foundry data. | Source JSON is never written. PNG export includes no wall overlay or closure artwork and produces no modified Foundry JSON. Future saved editor sessions use a separate format. |
| FR-007 | Erase unwanted objects manually. | A continuous circular brush makes pixels transparent; diameter is expressed in original image pixels and is adjustable. |
| FR-008 | Recover from edits. | Undo/redo restores contour-mask decisions, closure additions, and complete brush strokes; restore brush recovers source opacity. |
| FR-009 | Export PNG with transparency. | Output is RGBA at the exact original width/height and origin. Preserved pixels retain the decoded JPG RGB values. No auto-crop or preview-resolution export. |
| FR-010 | Preserve a base-map workflow. | Original JPG is available unchanged for the ground level. Repeat the editor workflow for each upper floor. Automatic assembly inside Foundry is outside the initial scope. |
| FR-011 | Support alignment correction. | Use explicit scene dimensions, background offsets, and editable scene-origin controls. Show ambiguity warnings for padding; unsupported transforms must fail visibly. |
| FR-012 | Provide sample-driven compatibility. | Keep owner files under ignored `examples/`. Label synthetic data accurately. Verify a real export before claiming Dungeon Alchemist compatibility. |
| FR-013 | Target Foundry 13 and 14. | Provide an explicit target-version selector, a common PNG image path, and version-aware placement guidance. Keep future scene/tile export adapters separate where schemas differ. Initial PNG export does not create Foundry levels. |
| FR-014 | Configure floor elevation in feet. | Editable dropdown offers presets every 5 ft, including ground and negative heights; accept manual whole-number heights at 1-ft resolution. Reject fractions. Preserve selected target/elevation in PNG metadata and filename; explain that Foundry placement must be configured separately. |
| FR-015 | Pan with the right mouse button. | Holding and dragging the right button moves the map with the cursor in every tool, including fit zoom and brush/closure modes. Panning creates no brush stroke or closure vertex. |
| FR-016 | Configure automatic gap joining. | Adjustable maximum gap in original image pixels; 0 disables it. Join nearby free endpoints and endpoint-to-segment T junctions. Exact T intersections work without tolerance. Show generated joins separately and retain source walls unchanged. |
| FR-017 | Configure a signed contour offset. | A positive pixel offset expands the closed contour; a negative offset shrinks it. Preview the effective boundary, apply it to inside/outside masks, preserve PNG canvas dimensions, and refuse an inward offset that eliminates all closed areas. |
| FR-018 | Run and test the desktop UI directly. | Double-click `run.cmd` on Windows to open DALE; set up the local Python environment if absent. Allow an image/JSON pair to be opened from command-line arguments for agent-assisted manual testing. |

## Nonfunctional requirements

| ID | Requirement | Acceptance criterion |
| --- | --- | --- |
| NFR-001 | Large maps | Target JPGs up to 16,384 × 16,384. Warn above 8,192 per side. Export in a worker with progress/cancellation; use a reduced preview and stripe-based PNG generation. Full JPEG decoding still requires memory proportional to source area. |
| NFR-002 | Source safety | Never overwrite selected sources. PNG output is written to a temporary sibling and atomically replaces its destination only on success. Cancellation/failure removes the partial file. |
| NFR-003 | Local operation | Images and JSON stay on the user's machine. No account, server, telemetry, or image upload is needed for editing. |
| NFR-004 | Language | English code, documentation, and technical text; Russian chat. README short introduction must appear in English, then Russian. |
| NFR-005 | Agent navigation | Stable requirement IDs, small responsibility-focused modules, machine-readable index and state, targeted reads, reproducible checks, no committed generated/private files. |
| NFR-006 | Testing | Cover geometry noding, segment snapping, closure isolation, alpha operations, scale/offset conversion, source protection, export cancellation, and full-size export. |

## Interpretation and open questions

- A JPG has flattened artwork. A Foundry JSON commonly describes walls and lighting, not semantic ground/object layers. Initial ground removal means removing pixels by wall contours, then cleaning manually. Automated semantic recognition remains a future option requiring separate design and evaluation.
- Source walls include doors/windows as boundary segments regardless of whether a door is open in Foundry. Gameplay collision/sight semantics do not define the extraction boundary.
- Initial mask operations use the union of **all** closed faces. Enclosed courtyards are included; the eraser can make them transparent. Per-face selection and wall-art margins are follow-up refinements.
- Visible walls/roofs/shadows can extend past JSON centerlines. Exact pixel extraction and preservation of projecting details need real samples and optional future margins.
- Supported target generations are Foundry 13 and 14, confirmed by the owner. Exact builds, floor module configuration, Dungeon Alchemist version, export perspective, and typical available RAM still need sample-driven validation.
- Synthetic tests establish internal correctness. Real export alignment and usability in Foundry require separate validation.
- Six owner-provided legacy-style export pairs have now been inspected and opened. See `docs/sample-formats.md` for exact scope, geometry gaps, common-canvas checks, and the verified real-image PNG export. Live Foundry placement remains unverified.
