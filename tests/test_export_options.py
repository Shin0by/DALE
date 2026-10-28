"""Independent PNG output and immutable DA-only JSON/image export scope."""

import json
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QDialogButtonBox
from shapely import box
from test_alchemist import sample as sample
from test_alchemist_interaction import editor as editor

from dale.alchemist import export_session, scoped_geometry
from dale.alchemist_thinning import thin_objects
from dale.editing import add_line
from dale.overlay_export import export_overlays
from dale.preferences import load_alchemist_export, load_include_png
from dale.session import Session


def scene_payload(folder):
    files = list(folder.glob("*.json"))
    return json.loads(next(p for p in files if not p.name.endswith("-placement.json")).read_bytes())


@pytest.mark.parametrize("include_png", [False, True])
def test_da_only_exports_preserve_source_and_exclude_regular_geometry(
    sample, tmp_path, include_png
):
    session = sample[0]
    before, source = session.geometry(), session.source.json_bytes
    # A regular closed rectangle must not contribute any PNG area.
    for a, b in zip(
        box(0, 0, 399, 399).exterior.coords,
        list(box(0, 0, 399, 399).exterior.coords)[1:],
        strict=False,
    ):
        session.add(add_line(session.geometry(), a, b))
    applied = session.geometry()
    expected = export_session(session, only_alchemist=True)
    folder = export_overlays(session, tmp_path, json_contours="alchemist", include_png=include_png)
    payload = scene_payload(folder)
    assert len(payload["walls"]) == len(expected.geometry().walls)
    assert all(w.get("_id") != "ordinarywall0001" for w in payload["walls"])
    if include_png:
        manifest = json.loads(next(folder.glob("*-placement.json")).read_bytes())
        assert manifest["items"]
        assert all(item["width"] < 300 and item["height"] < 300 for item in manifest["items"])
    else:
        assert len(list(folder.iterdir())) == 1
    assert session.geometry() is applied and session.source.json_bytes == source
    assert before.lineage[0] in applied.lineage


def test_json_only_never_renders_image_or_requires_closed_regions(
    pair_factory, tmp_path, monkeypatch
):
    source = pair_factory(walls=[{"c": [1, 2, 10, 20]}])
    session = Session(replace(source, image_path=None))

    def forbidden(*args, **kwargs):
        pytest.fail("JSON-only export must not prepare PNG pixels or grid bounds")

    for name in ("prepare_overlay", "export_png", "export_grid"):
        monkeypatch.setattr("dale.overlay_export." + name, forbidden)
    folder = export_overlays(session, tmp_path, include_png=False, size_to_grid=True)
    assert len(list(folder.iterdir())) == 1
    assert scene_payload(folder)["walls"][0]["c"] == [1, 2, 10, 20]
    with pytest.raises(ValueError, match="Enable PNG or JSON"):
        export_overlays(session, tmp_path, include_png=False, include_json=False)


def test_da_only_never_restores_hidden_or_thinned_assets(sample, tmp_path):
    session = sample[0]
    identifiers = [o.id for o in session.alchemist.objects]
    session.add(thin_objects(session, identifiers, 10))
    settings = list(session.alchemist.settings)
    settings[1] = False, 0
    session.alchemist = replace(session.alchemist, settings=tuple(settings))
    expected = scoped_geometry(session, scope="alchemist")
    folder = export_overlays(session, tmp_path, include_png=False, json_contours="alchemist")
    assert len(scene_payload(folder)["walls"]) == len(expected.walls)
    plain = replace(session, alchemist=None)
    folder = export_overlays(plain, tmp_path, include_png=False, json_contours="alchemist")
    assert scene_payload(folder)["walls"] == []


def test_da_png_regions_are_clipped_to_the_chosen_area(sample, tmp_path):
    session = sample[0]
    folder = export_overlays(
        session,
        tmp_path,
        selected_polygons=(box(0, 0, 400, 200),),
        json_contours="alchemist",
        include_json=True,
    )
    manifest = json.loads(next(folder.glob("*-placement.json")).read_bytes())
    assert manifest["items"]
    assert all(item["y"] + item["height"] <= 202 for item in manifest["items"])


def test_export_options_are_staged_persistent_and_frozen_in_worker(editor, tmp_path):
    from dale.ui import ExportWorker

    editor.show_tool_settings("Export selected regions")
    dialog = editor.tool_settings_popup
    assert dialog.png_export.isChecked()
    dialog.png_export.setChecked(False)
    dialog.reject()
    assert editor.include_png and load_include_png(editor.preferences_path)
    dialog = editor.show_tool_settings("Export selected regions")
    dialog.png_export.setChecked(False)
    dialog.json_export.setChecked(False)
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.json_export.setChecked(True)
    dialog.json_contours.setCurrentIndex(dialog.json_contours.findData("alchemist"))
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.accept()
    assert not editor.include_png and not load_include_png(editor.preferences_path)
    assert load_alchemist_export(editor.preferences_path) == "alchemist"
    worker = ExportWorker(
        editor.view.session,
        tmp_path / "export",
        editor,
        include_png=editor.include_png,
        include_json=editor.include_json,
    )
    editor.json_contours = "regular"
    editor.include_png = True
    assert not worker.include_png and worker.include_json and worker.json_contours == "alchemist"
