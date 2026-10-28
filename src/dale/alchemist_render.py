"""Local DA drawing analysis; global extraction topology is calculated only when needed."""

from collections import OrderedDict, namedtuple
from threading import RLock

from shapely import STRtree
from shapely.geometry import GeometryCollection, MultiPolygon

from dale.geometry import RegionAnalysis, analyze_regions, simple_contour_polygon


def object_figures(data, geometry, gap_tolerance):
    """Treat every placed object, including disconnected islands, as one selection unit."""
    from dale.geometry import ContourComponent
    from dale.object_index import object_index

    index = object_index(data, geometry)
    cached = getattr(index, "figures", None)
    if cached is not None and cached[0] == gap_tolerance:
        return cached[1]
    result = []
    for _, indices in index.units:
        lines = tuple(index.edges[i] for i in indices)
        result.append(
            ContourComponent(
                tuple(geometry.lineage[i].id for i in indices),
                lines,
                _part(lines, gap_tolerance).area,
            )
        )
    result = tuple(result)
    index.figures = gap_tolerance, result
    return result


class _PartCache:
    """Bound retained geometry by edge volume, avoiding small-object count thrashing."""

    Info = namedtuple("PartCacheInfo", "hits misses maxsize currsize edges max_edges")

    def __init__(self, calculate, *, max_edges=1_000_000, max_entries=16384):
        self.calculate = calculate
        self.max_edges, self.max_entries = max_edges, max_entries
        self.lock = RLock()
        self.values = OrderedDict()
        self.edges = self.hits = self.misses = self.generation = 0

    def __call__(self, edges, gap_tolerance):
        key = edges, gap_tolerance
        with self.lock:
            if key in self.values:
                self.hits += 1
                self.values.move_to_end(key)
                return self.values[key]
            self.misses += 1
            generation = self.generation
        result = self.calculate(edges, gap_tolerance)
        cost = max(1, len(edges))
        with self.lock:
            if generation != self.generation or cost > self.max_edges:
                return result
            # Concurrent readers may finish the same immutable shape independently.
            if key in self.values:
                self.values.move_to_end(key)
                return self.values[key]
            while self.values and (
                len(self.values) >= self.max_entries or self.edges + cost > self.max_edges
            ):
                previous, _ = self.values.popitem(last=False)
                self.edges -= max(1, len(previous[0]))
            self.values[key] = result
            self.edges += cost
        return result

    def cache_clear(self):
        with self.lock:
            self.values.clear()
            self.edges = self.hits = self.misses = 0
            self.generation += 1

    def cache_info(self):
        with self.lock:
            return self.Info(
                self.hits,
                self.misses,
                self.max_entries,
                len(self.values),
                self.edges,
                self.max_edges,
            )


def _calculate_part(edges, gap_tolerance):
    polygon = simple_contour_polygon(edges)
    if polygon is not None:
        return RegionAnalysis(polygon, 1, (), cells=(polygon,))
    # Imported alpha masks often contain many already closed, disjoint rings.
    # Only general intersections/open lines require the full endpoint-noding path.
    rings, start = [], 0
    for index, edge in enumerate(edges):
        if index > start and edges[index - 1][1] != edge[0]:
            break
        if edge[1] == edges[start][0]:
            polygon = simple_contour_polygon(edges[start : index + 1])
            if polygon is None:
                break
            rings.append(polygon)
            start = index + 1
    if start == len(edges) and len(rings) > 1:
        area = MultiPolygon(rings)
        if area.is_valid:
            pairs = STRtree(rings).query(rings, predicate="dwithin", distance=1e-7)
            if not any(a != b for a, b in zip(*pairs, strict=True)):
                cells = tuple(sorted(rings, key=lambda p: (p.bounds[1], p.bounds[0], p.area)))
                return RegionAnalysis(area, len(rings), (), cells=cells)
    return analyze_regions(edges, gap_tolerance=gap_tolerance)


_part = _PartCache(_calculate_part)


def display_key(data, geometry, gap_tolerance):
    return geometry, geometry.lineage, geometry.ancestry, data, gap_tolerance


def display_analysis(data, geometry, gap_tolerance, report=None):
    """Reuse stationary obstacles; connected architectural walls keep their joint analysis."""
    from dale.object_index import object_index

    index = object_index(data, geometry)
    cached = getattr(index, "drawing", None)
    if cached is not None and cached[0] == gap_tolerance:
        return cached[1]
    grouped = index.drawing_groups
    parts = []
    last_percent = None
    for position, edges in enumerate(grouped):
        percent = 40 + int(40 * position / max(1, len(grouped)))
        if report and percent != last_percent:
            report(percent, "Calculating DA contours")
            last_percent = percent
        parts.append(_part(tuple(edges), gap_tolerance))
    result = RegionAnalysis(
        GeometryCollection([p.area for p in parts if not p.area.is_empty]),
        sum(p.faces for p in parts),
        tuple(edge for p in parts for edge in p.unresolved),
        tuple(edge for p in parts for edge in p.joins),
        tuple(cell for p in parts for cell in p.cells),
    )
    index.drawing = gap_tolerance, result
    return result
