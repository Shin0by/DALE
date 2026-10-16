from dale.preferences import load_language, save_language


def test_language_preferences_survive_restart_and_invalid_files(tmp_path):
    path = tmp_path / "UserData" / "settings.json"
    assert load_language(path) == "ru"
    save_language(path, "en")
    assert load_language(path) == "en"
    path.write_text("invalid", encoding="utf-8")
    assert load_language(path) == "ru"
