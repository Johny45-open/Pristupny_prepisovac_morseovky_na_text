"""Testy stavového automat dekodéru (požadavky č. 5–12 plánu).

Čistý Python, žádné Qt, žádné reálné čekání – čas se předává explicitně
``now_ms``. Morseovy vstupy jsou vždy explicitní literály (bez encoderu).
"""

from __future__ import annotations

import pytest

from morseapp.decoder import (
    DEFAULT_LETTER_GAP_MS,
    DecodeStatus,
    Decoder,
    DASH_SYMBOL,
    DOT_SYMBOL,
)

GAP = DEFAULT_LETTER_GAP_MS  # 1200 ms


def make_decoder(**kwargs) -> Decoder:
    return Decoder(**kwargs)


def send(dec: Decoder, symbols: str, start_ms: float = 0.0, step_ms: float = 50.0) -> float:
    """Pošle sled signálů ('.' a '-') s falešným časem; vrací poslední čas."""
    now = start_ms
    for sym in symbols:
        assert sym in (DOT_SYMBOL, DASH_SYMBOL)
        dec.on_symbol(sym, now)
        now += step_ms
    return now


# ---------------------------------------------------------------------------
# 5. Automatické i ruční dokončení písmen
# ---------------------------------------------------------------------------

def test_letter_completed_automatically_after_gap():
    dec = make_decoder()
    last = send(dec, ".-")    # A; poslední signál v t=50 (krok 50 ms)
    result = dec.tick(last + GAP + 1)  # až za hranicí prodlevy od posledního signálu
    assert result is not None
    assert result.status is DecodeStatus.OK
    assert result.char == "A"
    assert dec.text == "A"


def test_tick_before_gap_does_not_complete():
    dec = make_decoder()
    send(dec, ".-", start_ms=0)
    assert dec.tick(1199) is None      # těsně před prodlevou
    assert dec.text == ""
    assert dec.is_partial


def test_tick_exactly_at_gap_completes():
    dec = make_decoder()
    send(dec, ".-", start_ms=0)        # poslední signál v t=50
    assert dec.tick(50 + GAP) is not None  # rovně hranice → dokončeno
    assert dec.text == "A"


def test_manual_finalize():
    dec = make_decoder()
    send(dec, "-.-.")       # C
    result = dec.finalize_letter(1000)
    assert result.status is DecodeStatus.OK
    assert result.char == "C"
    assert dec.text == "C"


def test_manual_finalize_without_signal_is_missing():
    dec = make_decoder()
    result = dec.finalize_letter(0)
    assert result.status is DecodeStatus.MISSING
    assert dec.text == ""
    assert result.appended == ""


# ---------------------------------------------------------------------------
# 11. Nový signál až po prodlevě dokončí předchozí znak
# ---------------------------------------------------------------------------

def test_new_symbol_after_gap_finalizes_previous_first():
    dec = make_decoder()
    send(dec, ".")                    # E v t=0
    result = dec.on_symbol("-", GAP + 10)  # nový signál mnohem později
    assert result is not None
    assert result.status is DecodeStatus.OK
    assert result.char == "E"
    assert dec.text == "E"
    # Nový znak je rozpracovaný (čárka = T), v textu zatím není.
    assert dec.current_code == "-"
    assert dec.is_partial
    assert dec.text == "E"


def test_new_symbol_before_gap_keeps_partial():
    dec = make_decoder()
    send(dec, ".")
    assert dec.on_symbol("-", GAP - 1) is None  # ještě v rámci písmene
    assert dec.current_code == ".-"


# ---------------------------------------------------------------------------
# 6–7. Ruční mezery, opakované, počáteční, koncové; auto-mezery vypnuty
# ---------------------------------------------------------------------------

def test_manual_space_between_words():
    dec = make_decoder()
    send(dec, ".-")           # A
    dec.finalize_letter(100)
    dec.word_space(200)
    send(dec, "-...", start_ms=300)   # B
    dec.finalize_letter(400)
    assert dec.text == "A B"


def test_word_space_finalizes_pending_char():
    dec = make_decoder()
    send(dec, "..")           # I (rozpracované)
    dec.word_space(100)
    assert dec.text == "I "
    send(dec, ".", start_ms=200)
    dec.finalize_letter(300)
    assert dec.text == "I E"


def test_no_leading_space():
    dec = make_decoder()
    dec.word_space(0)                    # mezera na začátku
    assert dec.text == ""
    send(dec, ".")
    dec.finalize_letter(100)
    assert dec.text == "E"               # žádná úvodní mezera


def test_repeated_spaces_coalesce():
    dec = make_decoder()
    send(dec, ".")
    dec.finalize_letter(100)
    dec.word_space(200)
    dec.word_space(300)                  # opakovaná mezera
    dec.word_space(400)
    assert dec.text == "E "              # jen jedna mezera
    send(dec, ".", start_ms=500)
    dec.finalize_letter(600)
    assert dec.text == "E E"


def test_auto_word_space_disabled_by_default():
    dec = make_decoder()
    assert dec.auto_word_space_enabled is False
    send(dec, ".-")                       # A
    dec.finalize_letter(100)
    # Dlouhá pauza – musí vzniknout jen písmeno, NIKDY mezera.
    assert dec.tick(100 + GAP + 1) is None
    assert dec.tick(10_000) is None
    assert dec.text == "A"


def test_optional_auto_word_space_adds_single_space():
    dec = make_decoder(auto_word_space=True, auto_word_gap_ms=3500)
    send(dec, ".-")
    dec.finalize_letter(100)
    assert dec.tick(100 + 3500) is None           # auto-mezeru nehlásí jako výsledek
    assert dec.text == "A "                       # ale přidala se
    dec.tick(100 + 7000)                          # opakovaná pauza
    assert dec.text == "A "                       # jen jedna mezera
    send(dec, "-...", start_ms=100 + 7100)        # B – auto mezera se resetuje
    dec.finalize_letter(100 + 7200)
    assert dec.text == "A B"


def test_auto_word_gap_is_separate_from_letter_gap():
    # Mezera se nesmí přidat dřív než letter_gap, ale auto_word_gap > letter_gap.
    dec = make_decoder(letter_gap_ms=1200, auto_word_space=True, auto_word_gap_ms=3500)
    send(dec, ".")
    dec.finalize_letter(100)
    dec.tick(100 + 1200)         # jen prodleva písmene – žádná mezera
    assert dec.text == "E"
    dec.tick(100 + 3500)         # až auto_word_gap → mezera
    assert dec.text == "E "


# ---------------------------------------------------------------------------
# 8. Dokončení zprávy s rozpracovaným písmenem
# ---------------------------------------------------------------------------

def test_finish_message_completes_pending_char():
    dec = make_decoder()
    send(dec, "..-")             # U zůstalo rozpracované
    result = dec.finish_message(5000)
    assert result.status is DecodeStatus.OK
    assert result.char == "U"
    assert dec.text == "U"
    assert not dec.is_partial


def test_finish_message_trims_trailing_space():
    dec = make_decoder()
    send(dec, ".-")
    dec.finalize_letter(100)
    dec.word_space(200)
    result = dec.finish_message(300)
    assert result.status is DecodeStatus.MISSING   # po mezeře nebyl znak
    assert dec.text == "A"                          # koncová mezera oříznuta


def test_finish_message_empty_input():
    dec = make_decoder()
    result = dec.finish_message(0)
    assert result.status is DecodeStatus.MISSING
    assert dec.text == ""


# ---------------------------------------------------------------------------
# 9. Mazání a opravy
# ---------------------------------------------------------------------------

def test_backspace_symbol_removes_last_signal():
    dec = make_decoder()
    send(dec, ".-")
    assert dec.backspace_symbol() is True
    assert dec.current_code == "."
    assert dec.backspace_symbol() is True
    assert dec.current_code == ""
    assert dec.backspace_symbol() is False   # není co mazat


def test_backspace_symbol_does_not_touch_completed_text():
    dec = make_decoder()
    send(dec, ".")
    dec.finalize_letter(100)
    send(dec, "-", start_ms=200)
    assert dec.backspace_symbol() is True
    assert dec.text == "E"                   # hotové písmeno zůstalo


def test_backspace_char_removes_last_decoded_char():
    dec = make_decoder()
    send(dec, ".-")
    dec.finalize_letter(100)
    send(dec, "-...", start_ms=200)
    dec.finalize_letter(300)
    assert dec.text == "AB"
    assert dec.backspace_char(400) is True
    assert dec.text == "A"


def test_backspace_char_at_start_returns_false():
    dec = make_decoder()
    assert dec.backspace_char(0) is False
    assert dec.text == ""


def test_backspace_char_finalizes_pending_first():
    dec = make_decoder()
    send(dec, ".-")              # A rozpracované
    assert dec.backspace_char(100) is True
    assert dec.text == ""        # A se dokončilo a hned smazalo


def test_backspace_char_removes_unknown_placeholder_entirely():
    dec = make_decoder()
    send(dec, "......")          # neznámý kód (šest teček)
    result = dec.finalize_letter(100)
    assert result.status is DecodeStatus.UNKNOWN
    assert dec.text == "[......]"
    assert dec.backspace_char(200) is True
    assert dec.text == ""        # placeholder zmizel jako celek


# ---------------------------------------------------------------------------
# 10. Neznámé kódy, prázdné dokončení, PARTIAL
# ---------------------------------------------------------------------------

def test_unknown_code_shows_placeholder_without_crash():
    dec = make_decoder()
    result = dec.finalize_letter(0)
    assert result.status is DecodeStatus.MISSING
    send(dec, "......")
    result = dec.finalize_letter(100)
    assert result.status is DecodeStatus.UNKNOWN
    assert result.char is None
    assert result.code == "......"
    assert dec.text == "[......]"


def test_unknown_code_keeps_message_flow():
    dec = make_decoder()
    send(dec, "......")
    dec.finalize_letter(100)
    send(dec, ".-", start_ms=200)
    dec.finalize_letter(300)
    assert dec.text == "[......]A"   # neznámý kód nezablokoval další znaky


def test_partial_state_is_exposed():
    dec = make_decoder()
    assert not dec.is_partial
    dec.on_symbol(".", 0)
    assert dec.is_partial
    assert dec.current_code == "."
    dec.finalize_letter(100)
    assert not dec.is_partial
    assert dec.current_code == ""


# ---------------------------------------------------------------------------
# 12. Časové hraniční případy bez reálného čekání
# ---------------------------------------------------------------------------

def test_exact_letter_gap_timing_is_deterministic():
    dec = make_decoder()
    dec.on_symbol(".", 1000)                  # poslední signál v t=1000
    assert dec.tick(1000 + GAP - 1) is None   # těsně pod hranicí
    result = dec.tick(1000 + GAP)             # přesně na hranici
    assert result is not None and result.char == "E"


def test_custom_letter_gap():
    dec = make_decoder(letter_gap_ms=500)
    send(dec, ".-", start_ms=0)
    assert dec.tick(549) is None
    assert dec.tick(550) is not None


def test_invalid_config_raises():
    with pytest.raises(ValueError):
        make_decoder(letter_gap_ms=0)
    with pytest.raises(ValueError):
        make_decoder(auto_word_gap_ms=-1)
    with pytest.raises(ValueError):
        dec = make_decoder()
        dec.set_auto_word_space(True, auto_word_gap_ms=0)


def test_invalid_symbol_raises_not_crash():
    dec = make_decoder()
    with pytest.raises(ValueError):
        dec.on_symbol("x", 0)
    with pytest.raises(ValueError):
        dec.on_symbol("", 0)


def test_realistic_sequence_sos():
    dec = make_decoder()
    # ... --- ... (S O S) s prodlevami mezi písmeny, bez mezer mezi slovy
    now = 0.0
    for code in ("...", "---", "..."):
        for sym in code:
            dec.on_symbol(sym, now)
            now += 60
        now += GAP                     # posun za prodlevu písmene
        dec.tick(now)                  # dokončí písmeno
        now += 100
    assert dec.text == "SOS"


def test_sequence_with_manual_word_space():
    dec = make_decoder()
    now = 0.0

    def send_letter(code: str) -> None:
        nonlocal now
        for sym in code:
            dec.on_symbol(sym, now)
            now += 60
        dec.finalize_letter(now)
        now += 100

    send_letter("....")    # H
    send_letter(".")       # E
    send_letter(".-..")    # L
    send_letter(".-..")    # L
    dec.word_space(now)    # ruční mezera před posledním slovem
    now += 100
    send_letter("---")     # O
    dec.finish_message(now + 100)

    assert not dec.text.startswith(" ")
    assert "  " not in dec.text
    assert dec.text == "HELL O"


def test_reset_clears_everything():
    dec = make_decoder()
    send(dec, ".-")
    dec.finalize_letter(100)
    dec.reset()
    assert dec.text == ""
    assert dec.current_code == ""
    assert not dec.is_partial
