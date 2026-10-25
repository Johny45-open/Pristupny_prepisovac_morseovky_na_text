"""Testy ukládání a obnovy nastavení (požadavek č. 10 plánu, etapa E0)."""

from __future__ import annotations

from PyQt6.QtCore import QSettings

from morseapp.settings_store import (
    DEFAULTS,
    RANGES,
    Settings,
    SettingsStore,
    normalize,
)


# ---------------------------------------------------------------------------
# Výchozí hodnoty
# ---------------------------------------------------------------------------

def test_default_threshold_is_120():
    assert Settings().threshold_ms == 120
    assert DEFAULTS["threshold_ms"] == 120


def test_default_continuous_announce_is_off():
    assert Settings().continuous_announce is False
    assert DEFAULTS["continuous_announce"] is False


def test_default_auto_word_space_is_off():
    assert Settings().auto_word_space is False


def test_all_defaults_within_allowed_ranges():
    settings = Settings()
    for key, (low, high) in RANGES.items():
        value = getattr(settings, key)
        assert low <= value <= high, f"{key}={value} mimo rozsah {low}–{high}"


# ---------------------------------------------------------------------------
# Validace (normalize) – poškozené a neplatné hodnoty
# ---------------------------------------------------------------------------

def test_missing_values_fall_back_to_defaults():
    assert normalize({}) == Settings()


def test_none_value_falls_back_to_default():
    assert normalize({"threshold_ms": None, "continuous_announce": None}) == Settings()


def test_non_numeric_string_falls_back_to_default():
    assert normalize({"tone_frequency_hz": "abc"}) == Settings()


def test_float_string_is_accepted():
    result = normalize({"threshold_ms": "150"})
    assert result.threshold_ms == 150


def test_values_are_clamped_into_range():
    result = normalize({"threshold_ms": 99999, "tone_volume": -50})
    assert result.threshold_ms == RANGES["threshold_ms"][1]
    assert result.tone_volume == RANGES["tone_volume"][0]


def test_bool_strings_are_accepted():
    assert normalize({"continuous_announce": "true"}).continuous_announce is True
    assert normalize({"continuous_announce": "yes"}).continuous_announce is True
    assert normalize({"continuous_announce": "off"}).continuous_announce is False


def test_invalid_bool_falls_back_to_default():
    assert normalize({"auto_word_space": "blabla"}).auto_word_space is False


def test_bool_as_int_is_not_accepted():
    # 1/0 z INI přicházejí jako řetězce; číselná 1 není bool → výchozí (False).
    assert normalize({"continuous_announce": 1}).continuous_announce is False


def test_negative_threshold_falls_to_min():
    result = normalize({"threshold_ms": -1})
    assert result.threshold_ms == RANGES["threshold_ms"][0]


# ---------------------------------------------------------------------------
# Kolo uložení a obnovy (round-trip) přes QSettings (INI, ne registr)
# ---------------------------------------------------------------------------

def test_round_trip_preserves_custom_values(tmp_path):
    store = SettingsStore.ini_store(str(tmp_path / "settings.ini"))
    custom = normalize(
        {
            "tone_frequency_hz": 700,
            "tone_volume": 55,
            "threshold_ms": 150,
            "letter_gap_ms": 900,
            "continuous_announce": True,
            "auto_word_space": True,
            "speech_volume": 80,
        }
    )
    store.save(custom)

    reloaded = SettingsStore.ini_store(str(tmp_path / "settings.ini")).load()
    assert reloaded == custom
    assert reloaded.threshold_ms == 150
    assert reloaded.continuous_announce is True


def test_load_from_missing_file_returns_defaults(tmp_path):
    store = SettingsStore.ini_store(str(tmp_path / "missing.ini"))
    assert store.load() == Settings()


def test_corrupted_ini_values_return_defaults(tmp_path):
    path = tmp_path / "corrupt.ini"
    path.write_text(
        "[General]\n"
        "threshold_ms=not-a-number\n"
        "tone_frequency_hz=\n"
        "continuous_announce=maybe\n"
        "tone_volume=5000\n",
        encoding="utf-8",
    )
    loaded = SettingsStore.ini_store(str(path)).load()
    # Poškozené hodnoty → výchozí.
    assert loaded.threshold_ms == 120
    assert loaded.tone_frequency_hz == 600
    assert loaded.continuous_announce is False
    # Číslo mimo rozsah → oříznuté, ne výchozí.
    assert loaded.tone_volume == 100


def test_reset_to_defaults(tmp_path):
    store = SettingsStore.ini_store(str(tmp_path / "reset.ini"))
    store.save(normalize({"threshold_ms": 500}))
    assert store.load().threshold_ms == 500
    assert store.reset_to_defaults() == Settings()
    assert store.load() == Settings()


def test_save_uses_real_qsettings_api(tmp_path, monkeypatch):
    # Kryt: save() volá setValue pro každý klíč a sync().
    calls: list[tuple[str, object]] = []

    class FakeSettings:
        def setValue(self, key, value):
            calls.append((key, value))

        def sync(self):
            calls.append(("__sync__", None))

        def value(self, key):
            return None

    store = SettingsStore(FakeSettings())
    store.save(Settings())
    saved_keys = {key for key, _ in calls if key != "__sync__"}
    assert saved_keys == set(DEFAULTS)
    assert ("__sync__", None) in calls
    # Nepoužívá se registry-friendly QSettings bez třídy (jen kontrola typu).
    assert isinstance(SettingsStore.ini_store(str(tmp_path / "x.ini"))._settings, QSettings)
