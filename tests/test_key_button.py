"""Testy Morseova klíče (požadavky 1–8 z E3).

Bez fyzického audio zařízení – tónové signály se zaznamenávají poslechem
nefalešných signálů, žádný skutečný zvuk se nehraje. ``pytest-qt``
nepoužíváme; QApplication vzniká vlastní fixture s offscreen platformou.
"""

from __future__ import annotations

import os

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

from morseapp.classifier import Signal, classify
from morseapp.settings_store import Settings
from morseapp.widgets.key_button import KeyButton


@pytest.fixture(scope="module")
def qapp():
    """Jediná QApplication pro testy; offscreen, nepotřebuje okno."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


class FakeClock:
    """Deterministický čas – testy nečekají v reálném čase."""

    def __init__(self) -> None:
        self.now = 1000.0   # sekundy

    def __call__(self) -> float:
        return self.now

    def advance(self, ms: float) -> None:
        self.now += ms / 1000.0


@pytest.fixture
def key(qapp):
    clock = FakeClock()
    button = KeyButton(settings_provider=Settings, clock=clock)
    button.clock = clock   # přístup pro testy
    button.show()
    yield button
    button.hide()
    button.deleteLater()


def press_space(widget, auto_repeat: bool = False) -> None:
    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, " ",
        auto_repeat, 1,
    )
    QApplication.sendEvent(widget, event)


def release_space(widget, auto_repeat: bool = False) -> None:
    event = QKeyEvent(
        QEvent.Type.KeyRelease, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, " ",
        auto_repeat, 1,
    )
    QApplication.sendEvent(widget, event)


def mouse_release_outside(widget) -> None:
    """Simuluje uvolnění myši mimo oblast tlačítka (implicitní grab)."""
    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(500.0, 500.0),       # daleko mimo widget
        QPointF(500.0, 500.0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, event)


# ---------------------------------------------------------------------------
# 1–2. Myší stisk: právě jeden signál, tečka vs. čárka
# ---------------------------------------------------------------------------

def test_mouse_press_release_creates_exactly_one_signal(key):
    symbols = []
    key.symbol_entered.connect(symbols.append)

    QTest.mousePress(key, Qt.MouseButton.LeftButton)
    key.clock.advance(50)                 # 50 ms → tečka
    QTest.mouseRelease(key, Qt.MouseButton.LeftButton)

    assert symbols == ["."]


def test_short_press_is_dot_long_press_is_dash(key):
    symbols = []
    key.symbol_entered.connect(symbols.append)

    QTest.mousePress(key, Qt.MouseButton.LeftButton)
    key.clock.advance(119)                # pod prahem 120 ms
    QTest.mouseRelease(key, Qt.MouseButton.LeftButton)

    QTest.mousePress(key, Qt.MouseButton.LeftButton)
    key.clock.advance(300)                # nad prahem
    QTest.mouseRelease(key, Qt.MouseButton.LeftButton)

    assert symbols == [".", "-"]


def test_tone_signals_fire_on_press_and_release(key):
    starts, ends = [], []
    key.tone_start.connect(lambda: starts.append(True))
    key.tone_end.connect(lambda: ends.append(True))

    QTest.mousePress(key, Qt.MouseButton.LeftButton)
    key.clock.advance(60)
    QTest.mouseRelease(key, Qt.MouseButton.LeftButton)

    assert len(starts) == 1
    assert len(ends) == 1


def test_very_short_press_creates_no_signal_but_ends_tone(key):
    symbols, ends = [], []
    key.symbol_entered.connect(symbols.append)
    key.tone_end.connect(lambda: ends.append(True))

    QTest.mousePress(key, Qt.MouseButton.LeftButton)
    key.clock.advance(10)                 # pod minimem 30 ms
    QTest.mouseRelease(key, Qt.MouseButton.LeftButton)

    assert symbols == []                  # IGNORE
    assert len(ends) == 1                 # tón ale skončil


def test_long_hold_does_not_generate_repeated_signals(key):
    symbols = []
    key.symbol_entered.connect(symbols.append)

    QTest.mousePress(key, Qt.MouseButton.LeftButton)
    for _ in range(50):                   # simulace „držení"
        key.clock.advance(100)
    QTest.mouseRelease(key, Qt.MouseButton.LeftButton)

    assert symbols == ["-"]               # právě jeden signál


# ---------------------------------------------------------------------------
# 3–4. Klávesnice a auto-repeat
# ---------------------------------------------------------------------------

def test_space_starts_and_ends_tone(key):
    starts, ends = [], []
    key.tone_start.connect(lambda: starts.append(True))
    key.tone_end.connect(lambda: ends.append(True))

    press_space(key)
    key.clock.advance(50)
    release_space(key)

    assert len(starts) == 1
    assert len(ends) == 1


def test_space_creates_symbol(key):
    symbols = []
    key.symbol_entered.connect(symbols.append)
    press_space(key)
    key.clock.advance(50)
    release_space(key)
    assert symbols == ["."]


def test_auto_repeat_events_are_filtered(key):
    symbols, starts, ends = [], [], []
    key.symbol_entered.connect(symbols.append)
    key.tone_start.connect(lambda: starts.append(True))
    key.tone_end.connect(lambda: ends.append(True))

    press_space(key)                       # skutečný stisk
    for _ in range(10):                    # opakované události systému
        press_space(key, auto_repeat=True)
        release_space(key, auto_repeat=True)
    key.clock.advance(50)
    release_space(key)                     # skutečné uvolnění

    assert len(starts) == 1
    assert len(ends) == 1
    assert symbols == ["."]


def test_second_press_while_held_is_ignored(key):
    # Stisk, když už je drženo, nic nedělá (dvojí zpracování).
    starts = []
    key.tone_start.connect(lambda: starts.append(True))
    QTest.mousePress(key, Qt.MouseButton.LeftButton)
    press_space(key)                       # „druhý" stisk během držení
    QTest.mouseRelease(key, Qt.MouseButton.LeftButton)
    assert len(starts) == 1
    assert not key.is_pressed


# ---------------------------------------------------------------------------
# 5–7. Uvolnění mimo, ztráta fokusu, rychlé posloupnosti
# ---------------------------------------------------------------------------

def test_release_outside_does_not_leave_tone_playing(key):
    ends, symbols = [], []
    key.tone_end.connect(lambda: ends.append(True))
    key.symbol_entered.connect(symbols.append)

    QTest.mousePress(key, Qt.MouseButton.LeftButton)
    key.clock.advance(50)
    mouse_release_outside(key)             # puštění mimo oblast

    assert not key.is_pressed
    assert len(ends) == 1                  # tón ukončen
    assert symbols == ["."]                # signál zaznamenán


def test_focus_loss_safely_resets_state(key):
    ends, symbols = [], []
    key.tone_end.connect(lambda: ends.append(True))
    key.symbol_entered.connect(symbols.append)

    key.setFocus()
    press_space(key)
    key.clock.advance(50)

    # Přímo odešleme FocusOut – offscreen platforma nemusí řídit fokus
    # okna stejně jako plnohodnotné prostředí.
    from PyQt6.QtGui import QFocusEvent

    focus_out = QFocusEvent(
        QEvent.Type.FocusOut, Qt.FocusReason.OtherFocusReason
    )
    QApplication.sendEvent(key, focus_out)

    assert not key.is_pressed
    assert len(ends) == 1                  # tón ukončen
    assert symbols == []                   # ale signál NEVZNIKL

    # Uvolnění po ztrátě fokusu už nic nepřidá.
    release_space(key)
    assert symbols == []
    assert len(ends) == 1


def test_rapid_press_release_press_sequence(key):
    symbols = []
    key.symbol_entered.connect(symbols.append)

    QTest.mousePress(key, Qt.MouseButton.LeftButton)
    key.clock.advance(50)
    QTest.mouseRelease(key, Qt.MouseButton.LeftButton)
    QTest.mousePress(key, Qt.MouseButton.LeftButton)
    key.clock.advance(300)
    QTest.mouseRelease(key, Qt.MouseButton.LeftButton)
    QTest.mousePress(key, Qt.MouseButton.LeftButton)
    key.clock.advance(50)
    QTest.mouseRelease(key, Qt.MouseButton.LeftButton)

    assert symbols == [".", "-", "."]      # nezablokovalo další zadávání


def test_cancel_press_ends_tone_without_symbol(key):
    ends, symbols = [], []
    key.tone_end.connect(lambda: ends.append(True))
    key.symbol_entered.connect(symbols.append)

    QTest.mousePress(key, Qt.MouseButton.LeftButton)
    key.clock.advance(50)
    key.cancel_press()

    assert not key.is_pressed
    assert len(ends) == 1
    assert symbols == []

    # Opětovné cancel je bezpečné.
    key.cancel_press()
    assert len(ends) == 1


# ---------------------------------------------------------------------------
# Klasifikace widgetu = sdílený classify() (žádná kopie logiky)
# ---------------------------------------------------------------------------

def test_key_button_uses_shared_classifier_defaults():
    # Výchozí práh 120 ms a minimum 30 ms podle schváleného plánu.
    assert classify(119) is Signal.DOT
    assert classify(120) is Signal.DASH
    assert Settings().threshold_ms == 120
    assert Settings().min_press_ms == 30


def test_key_button_has_accessible_description(key):
    assert key.accessibleDescription() != ""
    assert "Morse" in key.accessibleDescription()
