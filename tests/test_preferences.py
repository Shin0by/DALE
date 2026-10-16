import json

from dale.preferences import load_foundry_major, load_language, save_foundry_major, save_language


def test_language_preferences_survive_restart_and_invalid_files(tmp_path):
    path = tmp_path / "UserData" / "settings.json"
    assert load_language(path) == "ru"
    save_language(path, "en")
    assert load_language(path) == "en"
    path.write_text("invalid", encoding="utf-8")
    assert load_language(path) == "ru"


def test_foundry_and_language_preferences_merge_and_survive_restart(tmp_path):
    path = tmp_path / "settings.json"
    assert load_foundry_major(path) == 14
    save_foundry_major(path, 13)
    save_language(path, "en")
    assert load_foundry_major(path) == 13
    assert load_language(path) == "en"
    save_foundry_major(path, 14)
    assert load_language(path) == "en"
    assert load_foundry_major(path) == 14
    path.write_text(json.dumps({"foundry_major": "13", "language": "en"}), encoding="utf-8")
    assert load_foundry_major(path) == 14
    path.write_text("[]", encoding="utf-8")
    assert load_foundry_major(path) == 14
