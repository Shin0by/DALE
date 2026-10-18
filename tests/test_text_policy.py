"""Hard punctuation policy covers rendered strings and skips private/generated assets."""

from pathlib import Path

import pytest

from tools.text_policy import check_authored_texts, dash_analogues, text_violations


@pytest.mark.parametrize(
    "codepoint",
    [0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212, 0x00AD, 0xFE63, 0xFF0D, 0x2796],
)
def test_unicode_dash_and_minus_variants_rejected(codepoint):
    text = "Name " + chr(codepoint) + " description"
    assert text_violations(Path("guide.md"), text) == [(1, codepoint)]


def test_ascii_punctuation_and_other_ui_symbols_remain_valid():
    assert not dash_analogues("Scene - image, 0-10, -0.25, -infinity; Ctrl+C / Ctrl+V; 90°")


def test_escaped_translation_and_json_text_are_checked():
    escaped = chr(92) + "u2014"
    assert text_violations(Path("translations.py"), 'LABEL = "a ' + escaped + ' b"') == [
        (1, 0x2014)
    ]
    assert text_violations(Path("state.json"), '{"note":"a ' + escaped + ' b"}') == [(1, 0x2014)]
    entity = chr(38) + "mdash;"
    assert text_violations(Path("guide.md"), "a " + entity + " b") == [(1, 0x2014)]


def test_public_docs_and_translations_checked_without_private_or_generated_inputs(tmp_path):
    for name in (
        "docs/guide.md",
        "src/dale/localization.py",
        "examples/private.json",
        "artifacts/old.md",
        "DALE/START-HERE.txt",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('"text ' + chr(0x2014) + ' value"', encoding="utf-8")
    count, failures = check_authored_texts(tmp_path)
    assert count == 2
    assert any("guide.md" in failure for failure in failures)
    assert any("localization.py" in failure for failure in failures)
    assert not any("private" in failure or "old.md" in failure for failure in failures)
