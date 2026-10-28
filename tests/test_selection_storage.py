"""Complete contour references are compact and partial selection stays exact."""

import json
from dataclasses import replace

import pytest
from test_alchemist import sample as sample

from dale.selection_storage import pack_selection, unpack_selection


def test_complete_and_partial_selection_stay_exact(sample):
    session = sample[0]
    one, two = session.alchemist.objects[:2]
    selected = [*one.roots, *two.roots[:3]]
    packed = pack_selection({"figure_lines": selected}, session)
    assert packed["figure_lines"] == sorted(two.roots[:3])
    assert len(packed["figure_components"]) == 1
    assert len(json.dumps(packed)) < len(json.dumps({"figure_lines": selected}))
    restored = unpack_selection(json.loads(json.dumps(packed)), session)
    assert set(restored["figure_lines"]) == set(selected)


def test_compact_selection_rejects_different_membership(sample):
    session = sample[0]
    selected = list(session.alchemist.objects[0].roots)
    packed = json.loads(json.dumps(pack_selection({"figure_lines": selected}, session)))
    packed["figure_components"][0][1] += 1
    with pytest.raises(ValueError, match="does not match"):
        unpack_selection(packed, session)
    packed = json.loads(json.dumps(pack_selection({"figure_lines": selected}, session)))
    geometry = session.geometry()
    session.operations.append(
        replace(
            geometry, lineage=(replace(geometry.lineage[0], id="different"), *geometry.lineage[1:])
        )
    )
    # The first source line is unrelated to the selected DA contour.
    assert set(unpack_selection(packed, session)["figure_lines"]) == set(selected)
