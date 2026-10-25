"""Explicitní tabulka mezinárodních Morseových kódů pro DEKÓDOVÁNÍ.

Tento modul obsahuje **pouze** směr kód → znak (žádný encoder, žádná
obousměrná struktura – dle schváleného plánu aplikace dekóduje, nekóduje).

Podporované znaky:

- písmena A–Z,
- číslice 0–9,
- interpunkce: ``. , ? ' ! / ( ) & : ; = + - " $ @``.

Kódy jsou mezinárodní Morseova abeceda (ITU-R M.1677-1). Nejsou odvozeny
z žádného encoderu – jsou zadány explicitně a ověřeny testy.

Česká diakritika: v1 mezinárodní Morseovka zná jen základní latinská
písmena. Výsledek ``C`` se **nikdy automaticky nemění na** ``Č``. České
rozdšíření se nepřidává bez samostatného ověření a schválení.

Reprezentace neznámého kódu: ``decode()`` vrací ``None``. Kód, který
není v tabulce, nenahrazujeme znakem mlčky – volající (dekodér) ho
zobrazí jako ``[kód]`` (viz ``decoder``).
"""

from __future__ import annotations

# Kód → znak. Explicitní, ručně ověřená tabulka (ITU-R M.1677-1).
MORSE_TO_CHAR: dict[str, str] = {
    # Písmena
    ".-": "A",
    "-...": "B",
    "-.-.": "C",
    "-..": "D",
    ".": "E",
    "..-.": "F",
    "--.": "G",
    "....": "H",
    "..": "I",
    ".---": "J",
    "-.-": "K",
    ".-..": "L",
    "--": "M",
    "-.": "N",
    "---": "O",
    ".--.": "P",
    "--.-": "Q",
    ".-.": "R",
    "...": "S",
    "-": "T",
    "..-": "U",
    "...-": "V",
    ".--": "W",
    "-..-": "X",
    "-.--": "Y",
    "--..": "Z",
    # Číslice
    "-----": "0",
    ".----": "1",
    "..---": "2",
    "...--": "3",
    "....-": "4",
    ".....": "5",
    "-....": "6",
    "--...": "7",
    "---..": "8",
    "----.": "9",
    # Interpunkce
    ".-.-.-": ".",
    "--..--": ",",
    "..--..": "?",
    ".----.": "'",
    "-.-.--": "!",
    "-..-.": "/",
    "-.--.": "(",
    "-.--.-": ")",
    ".-...": "&",
    "---...": ":",
    "-.-.-.": ";",
    "-...-": "=",
    ".-.-.": "+",
    "-....-": "-",
    ".-..-.": '"',
    "...-..-": "$",
    ".--.-.": "@",
}


def decode(code: str) -> str | None:
    """Vrátí znak pro Morseův kód, nebo ``None`` pro neznámý kód.

    Neznámý kód nikdy nezpůsobí výjimku ani pád – je to běžná situace
    při ručním zadávání.
    """
    return MORSE_TO_CHAR.get(code)


def known_codes() -> frozenset[str]:
    """Množina všech podporovaných Morseových kódů (pro testy a kontrolu)."""
    return frozenset(MORSE_TO_CHAR)
