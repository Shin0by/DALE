# Project storage and object processing research

Measured locally on2026-10-27. These results describe the owner-designated private Untitled Map.dale; they are not universal timing guarantees. Original inputs were not modified. Prototypes are diagnostic artifacts, not a new production project format.

## Existing project and current saving

The original schema7 archive was saved by1.4.114, before applied-state-only saving. It contains11 historical geometry records and repeats state in history.json and datasets.json. Each member expands to1075.29MiB. Opening measured83.469s, with28.531s and30.515s in the two state readers. Preparing image/contours took1.953s.

Normal current saving created a separate Untitled Map - optimized.dale. Its archive shrank from220213753 to84634773 bytes; each state member shrank to148.53MiB. Opening plus an exact equality check took30.594s. Current geometry, DA metadata, persisted selection and embedded source bytes matched. This improvement is already available without a format change. Undo history is not restored from either file.

Source SHA256: e67e54d4b9ea17317b997d91d4d31f2330e8273b2dd21007591ae2022d01a60a. Copy SHA256: 8dac8080410380ff5485db6d07eb31ee91a92693e1c44e14cfc0a49c25511c3c.

## Representation experiments

One applied state contains171401 edges,530457 current/ancestor records and113639 property owners. Only31383 record attribute sets and2838 style lists are distinct. Repeated attributes and styles are a larger opportunity than adding threads to the same JSON decoding path.

Two warmed-cache reads per prototype restored the exact existing JSON values and float64 coordinates. The table measures one state payload, excluding complete archive validation, source loading and GUI publication. JSON/array variants use ZIP deflate level1. SQLite size is uncompressed; it is not a like-for-like compression comparison. Runtime decoding constructs the existing Python geometry objects after reading.

| Representation | Bytes | Read and expand, s | Runtime decode, s | First transform plan, s |
| --- | ---: | ---: | ---: | ---: |
| Ordinary JSON | 15385037 | 1.892 | 1.410 | 0.0480 |
| Shared attribute/style tables in JSON | 14722626 | 0.812 | 1.713 | 0.0456 |
| Shared metadata plus float64/int32 arrays | 13178431 | 0.633 | 1.708 | 0.0437 |
| Normalized SQLite columns | 79372288 | 0.894 | 1.792 | 0.0424 |

Pooling reduced uncompressed JSON from155740107 to79296591 bytes; constructing pools took1.595s. LZ4 compressed pooled JSON to22965542 bytes in0.044s and decompressed it in0.027s, trading a larger archive for lower codec cost. Parsing and Python allocation remain separate costs. The array prototype's combined read/decode gain was about29%, not a threefold complete-project speedup. The narrow transform-plan check found no editing penalty; a full interaction and export benchmark is still required before adoption.

Evidence: artifacts/projection-close/storage-research/results.json and storage-research.py; artifacts/projection-close/mode-progress/compact-owner-result.json. Prototype files remain ignored and outside the portable delivery.

## Recommended next format

1. Store each dataset's applied state once. Root/current dataset references should not duplicate its payload.
2. Store exact float64 coordinates in typed arrays, with integer references into shared ID, ancestry and style tables. Keep source JSON/DAM/image bytes unchanged. Reject object/pickle arrays and validate shapes, numeric bounds and references before publication.
3. Keep active geometry in memory. Use immutable object-to-edge, category-to-object and bounding-box indexes for selection/visibility; do not query SQL or decode strings on each mouse event.
4. Represent a placed DA object by its source shape, affine placement, slice/complexity parameters and revision. Preserve separate islands and explicit property ancestry. Materialize the edge view for existing ordinary tools/export until those consumers can accept object records directly.
5. Cache expensive local model projections and simplifications by content, algorithm version and parameters. Recompute on a relevant change, not once forever. Bounds indexes are rebuilt only for changed geometry; visibility can reuse intrinsic ownership and heights.
6. Load inactive datasets lazily only after designing validation and temporary-file ownership for them. Use bounded independent image work alongside contour preparation. More threads cannot remove duplicate payloads or Python object-allocation costs.

SQLite remains useful for portable per-type presets and model-cache lookup. Columns help targeted access, but this experiment does not justify moving the entire active geometry to SQL. Binary arrays plus shared metadata were smaller and faster to read here.

The owner requests current and previous .dale format support, independent of application versions. Production remains schema7. A future schema8 implementation must retain the schema7 reader and reject schema6 and earlier; when schema9 ships, retain8/9 only. No speculative readers or old migrations are introduced now.

## Primary references and limits

- [NumPy array format](https://numpy.org/doc/stable/reference/generated/numpy.lib.format.html) documents dtype/shape-preserving binary arrays and ZIP-based NPZ. [numpy.load](https://numpy.org/doc/stable/reference/generated/numpy.load.html) describes memory mapping and disabling pickle. Compressed ZIP members do not provide direct memory mapping; that needs a validated extracted or uncompressed layout.
- [SQLite WITHOUT ROWID](https://www.sqlite.org/withoutrowid.html) describes workload-dependent primary-key savings, not a universal speed switch. [SQLite internal versus external BLOBs](https://www.sqlite.org/intern-v-extern-blob.html) reports hardware- and size-dependent results; historical benchmark numbers are not DALE measurements.
- [SQLite R-Tree](https://www.sqlite.org/rtree.html) stores default bounds as32-bit floats. It can supply conservative candidates, but cannot replace exact float64 geometry.
- [Shapely STRtree](https://shapely.readthedocs.io/en/stable/strtree.html) is an immutable query index. Cache it by geometry revision, then verify candidates against exact edges.

## Delivered interaction changes

DA selection now addresses a whole placed object, including disconnected islands. Category visibility reuses intrinsic height information and ownership caches keyed by retained immutable inputs. The private visibility diagnostic before these changes measured0.87-1.25s, not the reported10s; after the cache changes it measured0.45-0.54s. Geometry/history remained unchanged. This identifies removed repeat work, not a reproduction of every reported delay.

Dataset manager Apply has a separate background preparation phase and keeps progress visible through GUI publication. On the private optimized copy the instrumented Apply path took3.235s, including1.027s background preparation and2.115s profiled GUI publication, with55 timer heartbeats and no errors. This is applying an already staged large dataset, not a measurement of a new model import. Synthetic tests verify cold analysis runs off the GUI thread and failure leaves the current dataset intact.

Native Windows follow-up,2026-10-27: after the owner cleared DAM/cache and saved the diagnostic copy, imported examples/Untitled Map.dam with local geometry again using compiled1.4.121 modules in a Windows Qt window. Import took38.807s, manager Apply1.546s, DA entry4.817s. The fresh map has2757 objects and214334 edges. QWidget uses the Qt Raster paint engine; initial full-contour paint events took46-49ms. This is not an OpenGL viewport. Windows compositor/display latency is not included in the paint-event timer.

All four categories were switched off and back on with real clicks. Some switches took2.64-3.16s. Profiling then reproduced a cache cliff: the2048-entry topology cache could not retain2757 small objects, causing5514 cache misses and zero hits for an unchanged full display/selection traversal. The replacement cache is bounded by1000000 retained input edges and16384 entries, uses exact edge/tolerance keys, and rejects post-clear asynchronous publication. The same eight-switch diagnostic then measured0.07-1.11s, with no additional topology misses. Geometry was unchanged. Evidence: fresh-result.json, fresh-profile.txt, fresh-after-result.json and fresh-after-budget.json under artifacts/projection-close/mode-progress.

Saved the fresh result through the GUI as examples/Untitled Map - verified.dale,87143034 bytes. Actual save work took10.716s; the save_project_file wrapper also includes time spent in the file chooser and must not be used as storage timing. GUI reopening took27.486s. Coordinates, closures, current lineage and wall styles exactly matched an independent repeat import from the same cleared project and cached local profiles. DA metadata hashes before save and after opening matched, and undo/redo reopened empty. A hash including the redundant in-memory ancestry tuple differs because applied-state loading deduplicates ancestor IDs and omits copies of current records; this is not a coordinate mismatch. The independent comparison was performed after a diagnostic wall-visibility toggle, so its raw DAData equality is not the before/after metadata check. The original owner archive and DAM remained unchanged. The owner intentionally changed the earlier optimized copy, so its historical benchmark hash no longer describes the current file.

Final compiled1.4.122 native-window verification reopened the verified file in30.775s, including a1.700s DA entry. All eight actual category clicks took0.059-1.265s, with no errors; screenshots confirmed all-hidden and all-restored states. The compiled affected suite passed179 cases, the actual portable EXE passed three smoke cases, and12 delivery checks passed. Evidence: native-final-result.json, objects-compiled-final.log, objects-portable-validation.json and objects-delivery-tests.log.

## Native libraries and next algorithm priorities

Installed development/runtime stack checked2026-10-27: Shapely2.2.0, GEOS3.14.1 and NumPy2.4.6; pyvips already provides the native image pipeline. Shapely2.2 scalar-call improvements are already present, so updating from2.1 is not an available new gain here. [Shapely release notes](https://shapely.readthedocs.io/en/stable/release/2.x.html) and [Shapely architecture](https://shapely.readthedocs.io/en/stable/index.html) describe compiled GEOS operations, C array loops and GIL release. [libvips](https://www.libvips.org/) describes demand-driven threaded image processing.

A read-only prototype used all214334 edges from the verified private map and compared the same common affine transform, with exact coordinate equality. Median of three runs: Python tuples0.14413s, an already prepared NumPy float64 array0.00538s, NumPy plus tuple-to-array and array-to-tuple conversions0.31515s. Thus the arithmetic kernel is about27 times faster, but naive insertion into the present tuple pipeline is slower overall. This is not an end-to-end rotation speedup: it excludes individual pivots, ownership, history and rendering. Evidence: artifacts/project-title/array-benchmark.json and array-benchmark.py. No application geometry or numerical implementation was changed by this experiment.

Priorities, inferred from the local profiles and experiment:

1. Retain object/category membership and bounds indexes across visibility changes; update only affected objects. The post-cache profiled toggle still traversed214334 records, spending0.668s in ownership calls and1.098s in display assembly under profiler overhead. An object visibility bitset and per-object retained paths avoid this work; a different polygon engine does not remove it.
2. Keep coordinates in immutable float64 arrays through multiple operations, alongside integer object/edge indexes. Apply batches through NumPy/Shapely array APIs, with bounded blocks for cancellation, rather than repeatedly converting tuples. Exact source ownership and applied geometry must remain preserved.
3. For alpha projection and outer-outline reduction, profile the Python triangle loop and candidate-update heap separately. Keep the required outer enclosure and no-new-contact invariants; an ordinary simplification call is not a drop-in replacement. Compile only numeric hot loops if batching is insufficient. [Cython typed memoryviews](https://docs.cython.org/en/latest/src/userguide/memoryviews.html) support buffer access without Python element overhead and numeric loops without the GIL. A prebuilt Windows extension could be bundled offline; this is a proposal, not a new shipped dependency.
4. Parallelize independent native work on immutable inputs with bounded workers and stale-result rejection. [NumPy thread safety](https://numpy.org/doc/stable/reference/thread_safety.html) confirms that many numeric operations release the GIL, whereas object arrays do not. Python dictionary/ancestry loops need representation changes or compiled code; more Python threads alone are not sufficient.
5. For opening projects, remove duplicated applied state and use shared metadata/typed arrays as proposed above. Faster arithmetic cannot fix JSON parsing and repeated Python allocation. GPU migration is not the first experiment for the present object/ownership bottleneck.

No unmeasured whole-application speedup is promised. Benchmark native kernels together with conversion, validation, publication and repaint costs before adopting a new library.

## Implemented object-array follow-up

ADR-131 / FR-194 implements the runtime array/index proposal without changing schema7. DA filters and object selection reuse bounded immutable ownership groups and integer visibility codes; retained float64 coordinates feed per-object bounds and vectorized transforms. Native structured-array conversion materializes the existing nested edge tuples without an extra Python loop constructing every point. Changed snapshots inherit unchanged ownership grouping and retain numeric coordinates. The latest applied geometry checkpoint also avoids rebuilding superseded source geometry. No new dependency or network service is added.

The same214334-edge private map was exercised with compiled1.4.123 code and the updated source. Measurements include Qt window refresh/paint for eight category toggles (offscreen QWidget, not compositor latency). Exact results and individual times are in artifacts/object-index/summary.json, sequence-before-result.json and native-array-result.json. Five successive all-object transforms retain exactly matching coordinates, IDs, styles and pivots by SHA256 comparison with the old implementation. The editor then rotated/scaled all selected objects, saved an isolated numeric-roundtrip.dale and reopened it; current geometry and DA metadata matched, with empty undo/redo. Original project/DAM files were not overwritten. These are local measured improvements, not universal timing guarantees or a new project-loading format.

Eight visibility switches: 4.737s before, 1.766s after. Median all-object numeric transformation, including tuple publication but excluding subsequent repaint/history: 0.335s before, 0.242s after.
