"""Script detection and font choice."""

from __future__ import annotations

from abikaraoke.fonts import choose_font, detect_scripts


def test_detects_devanagari():
    assert "devanagari" in detect_scripts("मैं तो कब से खड़ी इस पार")


def test_detects_malayalam():
    assert "malayalam" in detect_scripts("ഹരിവരാസനം")


def test_latin_only_has_no_script():
    assert detect_scripts("Hello, it's me") == []


def test_mixed_scripts_ordered_by_frequency():
    scripts = detect_scripts("മലയാളം മലയാളം hello தமிழ்")
    assert scripts[0] == "malayalam"
    assert "tamil" in scripts


def test_choose_font_returns_something_for_latin():
    font, warnings = choose_font("Hello")
    assert font
    assert warnings == []


def test_choose_font_for_devanagari_names_a_font():
    font, _ = choose_font("मैं तो कब से")
    assert font


def test_choose_font_warns_when_script_unsupported(monkeypatch):
    import abikaraoke.fonts as fonts

    monkeypatch.setattr(fonts, "bundled_font", lambda script: None)
    monkeypatch.setattr(fonts, "_installed_families", lambda: set())
    monkeypatch.setattr(fonts, "_has_language", lambda tag: False)
    font, warnings = fonts.choose_font("മലയാളം")
    assert warnings
    assert "malayalam" in warnings[0]


def test_bundled_font_is_preferred():
    import abikaraoke.fonts as fonts

    font, warnings = fonts.choose_font("മലയാളം")
    assert font == "Noto Sans Malayalam"
    assert warnings == []


def test_bundled_fonts_are_shipped():
    import abikaraoke.fonts as fonts

    directory = fonts.bundled_fonts_dir()
    assert directory is not None
    for script in ("malayalam", "devanagari", "tamil"):
        assert fonts.bundled_font(script) is not None, script
