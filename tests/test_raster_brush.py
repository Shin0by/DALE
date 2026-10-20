"""Exact brush cores, edge feather, stroke pressure and seam-safe alpha."""

import pytest
from PIL import ImageChops

from dale.project_io import load_project, save_project
from dale.raster import render_alpha, render_export_alpha
from dale.session import Session, Stroke


@pytest.mark.parametrize("shape", ["circle", "square"])
@pytest.mark.parametrize("feather", [0, 0.25, 0.75, 1])
def test_feather_changes_only_outer_band_and_keeps_solid_core(shape, feather):
    stroke = Stroke(((60, 60),), 40, False, shape, feather, 1)
    alpha = render_alpha((120, 120), (120, 120), (stroke,))
    assert alpha.getpixel((60, 60)) <= (1 if feather == 1 else 0)
    assert alpha.getpixel((102, 60)) == 255
    inner = 40 * (1 - feather)
    if inner > 2:
        assert alpha.getpixel((60 + int(inner) - 2, 60)) == 0
    if feather:
        value = alpha.getpixel((60 + round(40 * (1 - feather / 2)), 60))
        assert 0 < value < 255


@pytest.mark.parametrize("shape", ["circle", "square"])
@pytest.mark.parametrize("restore", [False, True])
@pytest.mark.parametrize("pressure", [0, 0.25, 0.75, 1])
def test_pressure_applies_once_per_stroke_and_sparse_sweep_is_continuous(shape, restore, pressure):
    baseline = (Stroke(((0, 60), (120, 60)), 200),) if restore else ()
    sparse = Stroke(((20, 60), (100, 60)), 25, restore, shape, 0.5, pressure)
    dense = Stroke(tuple((x, 60) for x in range(20, 101)), 25, restore, shape, 0.5, pressure)
    a = render_alpha((120, 120), (120, 120), (*baseline, sparse))
    b = render_alpha((120, 120), (120, 120), (*baseline, dense))
    assert ImageChops.difference(a, b).getbbox() is None
    assert (
        a.getpixel((60, 60)) == round(255 * pressure)
        if restore
        else a.getpixel((60, 60)) == 255 - round(255 * pressure)
    )


@pytest.mark.parametrize("shape", ["circle", "square"])
def test_soft_stroke_stripes_match_whole_frame_and_archive_retains_profile(
    pair_factory, tmp_path, shape
):
    source = pair_factory(size=(160, 180))
    stroke = Stroke(((30, 15), (120, 160)), 35, False, shape, 0.6, 0.7)
    whole = render_export_alpha(source.size, source.size, (stroke,))
    from PIL import Image

    tiled = Image.new("L", source.size)
    for top in (0, 60, 120):
        tiled.paste(render_export_alpha((160, 60), source.size, (stroke,), top=top), (0, top))
    assert whole.tobytes() == tiled.tobytes()
    session = Session(source)
    session.add(stroke)
    session.undo()
    path = tmp_path / "Soft.dale"
    save_project(session, path)
    with load_project(path) as loaded:
        assert loaded.session.future == [stroke]
        loaded.session.redo()
        assert loaded.session.operations == [stroke]
