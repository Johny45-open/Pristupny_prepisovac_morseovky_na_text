"""Trvalé uložení a validace nastavení aplikace (QSettings + validace).

Tento modul je součástí etapy E0. Obsahuje:

- ``Settings`` – neměnitelný datový objekt se všemi předvolbami.
- ``normalize(raw)`` – čistá (bez Qt) validace: neplatné hodnoty → výchozí,
  mimo rozsah → oříznutí do povoleného rozsahu.
- ``SettingsStore`` – obal nad ``QSettings`` pro trvalé ukládání.

Výchozí hodnoty dle schváleného plánu:
- ``threshold_ms = 120`` (hranice tečky/čárky),
- ``continuous_announce = False`` (průběžné hlasové oznamování vypnuto).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping

from PyQt6.QtCore import QSettings

# Klíč -> (minimum, maximum) pro číselné hodnoty; obojí se ořezává (clamp).
RANGES: dict[str, tuple[int, int]] = {
    "tone_frequency_hz": (100, 2000),
    "tone_volume": (0, 100),
    "threshold_ms": (50, 1000),
    "min_press_ms": (5, 200),
    "letter_gap_ms": (300, 3000),
    "auto_word_gap_ms": (1000, 10000),
    "speech_volume": (0, 100),
}

# Klíče, které jsou pravdivostní.
BOOL_KEYS = frozenset({"auto_word_space", "continuous_announce"})

_TRUE_STRINGS = frozenset({"true", "1", "yes", "on"})
_FALSE_STRINGS = frozenset({"false", "0", "no", "off"})


@dataclass(frozen=True)
class Settings:
    """Platná hodnoty nastavení (vždy po projití ``normalize``)."""

    tone_frequency_hz: int = 600      # frekvence tónu v Hz
    tone_volume: int = 70             # hlasitost tónu 0–100 %
    threshold_ms: int = 120           # hranice tečka/čárka
    min_press_ms: int = 30            # minimální délka stisku
    letter_gap_ms: int = 1200         # prodleva pro automatické ukončení písmene
    auto_word_space: bool = False     # automatické mezery mezi slovy – vypnuto
    auto_word_gap_ms: int = 3500      # prodleva pro volitelnou automatickou mezeru
    continuous_announce: bool = False  # průběžné hlasové oznamování – vypnuto
    speech_volume: int = 100          # hlasitost hlasu 0–100 %


DEFAULTS: dict[str, Any] = asdict(Settings())


def _coerce_bool(key: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
    return DEFAULTS[key]


def _coerce_int(key: str, value: Any) -> int:
    number: int | None = None
    if isinstance(value, bool):
        number = None
    elif isinstance(value, int):
        number = value
    elif isinstance(value, float):
        number = int(value)
    elif isinstance(value, str):
        try:
            number = int(value.strip())
        except ValueError:
            number = None
    if number is None:
        return DEFAULTS[key]
    low, high = RANGES[key]
    return max(low, min(high, number))


def normalize(raw: Mapping[str, Any]) -> Settings:
    """Dopravede libovolné (i poškozené) vstupy na platný ``Settings``.

    - chybějící klíč nebo nekonvertovatelná hodnota → výchozí hodnota,
    - číslo mimo povolený rozsah → oříznuto na nejbližší mez.
    """
    result: dict[str, Any] = {}
    for field in fields(Settings):
        key = field.name
        value = raw.get(key)
        if key in BOOL_KEYS:
            result[key] = _coerce_bool(key, value)
        else:
            result[key] = _coerce_int(key, value)
    return Settings(**result)


class SettingsStore:
    """Ukládání a načítání nastavení přes QSettings."""

    ORG = "PristupnyMorsePrepisovac"
    APP = "MorsePrepisovac"

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings if settings is not None else QSettings(self.ORG, self.APP)

    @classmethod
    def ini_store(cls, path: str) -> "SettingsStore":
        """uložení do INI souboru – používá se testy, nepíše do registru."""
        return cls(QSettings(path, QSettings.Format.IniFormat))

    def load(self) -> Settings:
        """Načte a validuje uložené hodnoty."""
        raw = {key: self._settings.value(key) for key in DEFAULTS}
        return normalize(raw)

    def save(self, settings: Settings) -> None:
        """Uloží již platný objekt ``Settings`` (trvale)."""
        for key, value in asdict(settings).items():
            self._settings.setValue(key, value)
        self._settings.sync()

    def reset_to_defaults(self) -> Settings:
        """Smaže uložené hodnoty a vrátí výchozí nastavení."""
        self._settings.clear()
        self._settings.sync()
        return Settings()
