"""Testy dekódovací tabulky (požadavky č. 1 a 2 plánu).

Očekávané hodnoty jsou **explicitní literály** – neodvozují se z žádného
encoderu (žádný v projektu neexistuje).
"""

from __future__ import annotations

from morseapp.morse_table import MORSE_TO_CHAR, decode, known_codes

# Explicitní očekávané kódy (ITU-R M.1677-1), zadány ručně.
EXPECTED_LETTERS = {
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
}

EXPECTED_DIGITS = {
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
}

EXPECTED_PUNCTUATION = {
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


def test_all_letters_decode():
    for code, expected in EXPECTED_LETTERS.items():
        assert decode(code) == expected, f"kód {code!r} nemá být {expected!r}"


def test_all_digits_decode():
    for code, expected in EXPECTED_DIGITS.items():
        assert decode(code) == expected, f"kód {code!r} nemá být {expected!r}"


def test_all_punctuation_decodes():
    for code, expected in EXPECTED_PUNCTUATION.items():
        assert decode(code) == expected, f"kód {code!r} nemá být {expected!r}"


def test_spot_checks_from_plan():
    assert decode(".-") == "A"
    assert decode("-...") == "B"
    assert decode("-.-.") == "C"
    assert decode(".") == "E"
    assert decode("-") == "T"
    assert decode("-----") == "0"
    assert decode(".----") == "1"


def test_table_covers_all_expected():
    expected = set(EXPECTED_LETTERS) | set(EXPECTED_DIGITS) | set(EXPECTED_PUNCTUATION)
    assert set(MORSE_TO_CHAR) == expected
    assert len(MORSE_TO_CHAR) == 26 + 10 + 17


def test_no_czech_diacritics_in_output():
    # V1 mezinárodní Morseovka: výsledky jsou jen základní latinská písmena.
    for char in MORSE_TO_CHAR.values():
        assert char == char.upper()
        assert char.isascii()


def test_unknown_code_returns_none_not_crash():
    assert decode("......") is None       # šest teček – neexistuje
    assert decode(".--.-..") is None      # náhodný neplatný kód
    assert decode("") is None


def test_known_codes_frozenset():
    codes = known_codes()
    assert ".-" in codes
    assert "....." in codes
    assert "......" not in codes
