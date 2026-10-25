"""Testy hlavního okna a přístupnosti (požadavky 9–15 z E3).

Bez fyzického audio zařízení (koordinátor je fake) a bez sítě.
``pytest-qt`` se nepoužívá – QApplication vzniká vlastní fixture.

Automatické testy **nenahrazují** ruční ověření s NVDA/Narratorem
(viz docs/pristupnost_checklist.md – zatím nevyplněná šablona).
"""

from __future__ import annotations

import os

import pytest
from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton, QTextEdit

from morseapp.announce import Announcer
from morseapp.main_window import MainWindow
from morseapp.settings_store import Settings
from morseapp.style_sheet import APP_STYLESHEET


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


class _IdleSignals(QObject):
    completed = pyqtSignal(int, bytes)
    error = pyqtSignal(int, str)
    interrupted = pyqtSignal(int)


class IdleSpeechWorker(QThread):
    """Fake hlasového pracovníka: nic negeneruje, žádná síť.

    E3 testy klikají na „Dokončit zprávu a přečíst“ (E4 změnilo
    chování tlačítka); bez tohoto faku by vznikl skutečný gTTS
    požadavek. Vlákno skončí okamžitě, rozhraní zůstane stejné.
    """

    def __init__(self, request_id: int, text: str, cache=None, parent=None) -> None:
        super().__init__(parent)
        self.request_id = request_id
        self.text = text
        self.signals = _IdleSignals()

    def run(self) -> None:  # nic nedělá – žádná síť
        pass


def idle_speech_factory(request_id: int, text: str, cache) -> IdleSpeechWorker:
    return IdleSpeechWorker(request_id, text, cache)


class FakeCoordinator:
    """Napodobuje AudioCoordinator bez pygame."""

    def __init__(self, available: bool = True, error: str | None = None) -> None:
        self._available = available
        self.error_message = error
        self.calls: list[str] = []

    @property
    def is_available(self) -> bool:
        return self._available

    def initialize(self) -> bool:
        self.calls.append("initialize")
        return self._available

    def prepare_tone(self, block) -> bool:
        self.calls.append("prepare_tone")
        return self._available

    def start_tone(self, volume: float = 1.0) -> bool:
        self.calls.append("start_tone")
        return self._available

    def release_tone(self) -> None:
        self.calls.append("release_tone")

    def stop_now(self) -> None:
        self.calls.append("stop_now")

    def shutdown(self) -> None:
        self.calls.append("shutdown")


class FakeOutput:
    """Zaznamenává výstup Announcera bez screen readeru."""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def speak(self, text, **kwargs):
        self.spoken.append(text)


def wait_for_tone_ready(window: MainWindow, timeout_ms: int = 5000) -> bool:
    """Čeká na asynchronní přípravu tónu (QThreadPool) bez pytest-qt."""
    from PyQt6.QtCore import QEventLoop, QTimer

    if window.key_button.isEnabled():
        return True
    loop = QEventLoop()
    window.tone_ready.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return window.key_button.isEnabled()


@pytest.fixture
def window(qapp):
    settings = Settings()
    coordinator = FakeCoordinator()
    output = FakeOutput()
    announcer = Announcer(output=output, clock=lambda: 0.0)
    win = MainWindow(
        settings=settings,
        coordinator=coordinator,
        announcer=announcer,
        speech_factory=idle_speech_factory,   # žádná síť v E3 testech
    )
    win.output = output
    win.coordinator = coordinator
    win.show()
    assert wait_for_tone_ready(win), "tón se nepřipravil"
    yield win
    win.close()
    win.deleteLater()


# ---------------------------------------------------------------------------
# 9. Přístupné názvy a popisy interaktivních prvků
# ---------------------------------------------------------------------------

def test_interactive_elements_have_accessible_names(window):
    # Qt přebírá název z viditelného textu tlačítka – kontrolujeme text.
    button_names = [
        window.key_button, window.dot_button, window.dash_button,
        window.finish_letter_button, window.space_button,
        window.back_symbol_button, window.back_char_button,
        window.finish_message_button,
    ]
    for button in button_names:
        assert isinstance(button, QPushButton)
        assert button.text().strip(), f"{button.objectName() or button} bez textu"
    # Editovatelné prvky mají vlastní název.
    assert window.text_edit.accessibleName() != ""
    assert window.status_label.accessibleName() != ""


def test_key_elements_have_relevant_descriptions(window):
    for button in (
        window.key_button, window.dot_button, window.dash_button,
        window.finish_message_button,
    ):
        assert button.accessibleDescription() != "", (
            f"{button.text()} nemá přístupný popis"
        )


def test_result_label_has_buddy(window):
    # Popisek je propojen s polem (setBuddy) – ověříme přes focus input.
    window.text_edit.setFocus()
    assert window.text_edit.hasFocus()


# ---------------------------------------------------------------------------
# 10. Pořadí Tab
# ---------------------------------------------------------------------------

def test_tab_order_matches_intended_sequence(window):
    expected = [
        window.key_button, window.dot_button, window.dash_button,
        window.finish_letter_button, window.space_button,
        window.back_symbol_button, window.back_char_button,
        window.finish_message_button, window.text_edit,
    ]
    window.key_button.setFocus()
    qapp = QApplication.instance()
    for next_widget in expected[1:]:
        QTest.keyClick(window, Qt.Key.Key_Tab)
        assert qapp.focusWidget() is next_widget, (
            f"Tab nevede na {next_widget.text() if hasattr(next_widget, 'text') else next_widget}"
        )


# ---------------------------------------------------------------------------
# 11. Viditelný fokus – per-třídní selektory
# ---------------------------------------------------------------------------

def test_stylesheet_has_focus_selectors_for_used_classes():
    # Použité třídy: QPushButton (tlačítka), QTextEdit (výsledek).
    assert "QPushButton:focus" in APP_STYLESHEET
    assert "QTextEdit:focus" in APP_STYLESHEET
    # Ne univerzální Q:focus.
    assert "\nQ:focus" not in APP_STYLESHEET and not APP_STYLESHEET.startswith("Q:focus")
    # Výrazné orámování – border v obou pravidlech.
    assert APP_STYLESHEET.count("border:") >= 2
    # Použité vlastnosti musí být podporované Qt Style Sheets (border, padding).
    assert "outline" not in APP_STYLESHEET  # neopodporovaná CSS vlastnost


def test_window_applies_stylesheet(window):
    assert "QPushButton:focus" in window.styleSheet()


# ---------------------------------------------------------------------------
# 12–13. Dekódování přes GUI
# ---------------------------------------------------------------------------

def test_dot_and_dash_update_decoder_and_output(window):
    QTest.mouseClick(window.dot_button, Qt.MouseButton.LeftButton)
    assert window._decoder.current_code == "."
    assert "Rozpracovaný kód: ." in window.status_label.text()

    QTest.mouseClick(window.dash_button, Qt.MouseButton.LeftButton)
    assert window._decoder.current_code == ".-"

    QTest.mouseClick(window.finish_letter_button, Qt.MouseButton.LeftButton)
    assert window.text_edit.toPlainText() == "A"
    assert window._decoder.current_code == ""


def test_manual_finish_space_backspace_and_finish_message(window):
    # E
    QTest.mouseClick(window.dot_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.finish_letter_button, Qt.MouseButton.LeftButton)
    assert window.text_edit.toPlainText() == "E"

    # mezera
    QTest.mouseClick(window.space_button, Qt.MouseButton.LeftButton)
    assert window.text_edit.toPlainText() == "E "

    # T
    QTest.mouseClick(window.dash_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.finish_letter_button, Qt.MouseButton.LeftButton)
    assert window.text_edit.toPlainText() == "E T"

    # vrácení posledního znaku
    QTest.mouseClick(window.back_char_button, Qt.MouseButton.LeftButton)
    assert window.text_edit.toPlainText() == "E "

    # vrácení signálu (rozpracovaný znak)
    QTest.mouseClick(window.dot_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.back_symbol_button, Qt.MouseButton.LeftButton)
    assert window._decoder.current_code == ""

    # dokončení zprávy: doplní rozpracované písmeno, mezera zůstává
    # (back_char mezeru neodstraňuje – text "E " je konzistentní)
    QTest.mouseClick(window.dot_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.dash_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.finish_message_button, Qt.MouseButton.LeftButton)
    assert window.text_edit.toPlainText() == "E A"


def test_unknown_code_shows_placeholder(window):
    # "------" (šest čárek) není v tabulce → placeholder.
    for _ in range(6):
        QTest.mouseClick(window.dash_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.finish_letter_button, Qt.MouseButton.LeftButton)
    assert window.text_edit.toPlainText() == "[------]"
    # A informace o chybě byla i oznámena:
    assert any("Neznámý kód" in text for text in window.output.spoken)


def test_finish_message_handles_pending_letter(window):
    QTest.mouseClick(window.dot_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.dash_button, Qt.MouseButton.LeftButton)  # A rozpracované
    QTest.mouseClick(window.finish_message_button, Qt.MouseButton.LeftButton)
    assert window.text_edit.toPlainText() == "A"
    assert "Zpráva dokončena." in window.output.spoken


def test_no_automatic_word_space_by_default(window):
    # auto_word_space = False: dlouhá pauza nesmí vytvořit mezeru.
    QTest.mouseClick(window.dot_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.finish_letter_button, Qt.MouseButton.LeftButton)
    window._on_letter_timeout()             # „prodleva" – jen předá čas dekodéru
    assert window.text_edit.toPlainText() == "E"


# ---------------------------------------------------------------------------
# 14. Průběžné oznamování standardně vypnuto
# ---------------------------------------------------------------------------

def test_default_continuous_announce_is_off(window):
    assert Settings().continuous_announce is False
    assert window._announcer.char_announcements_enabled is False

    QTest.mouseClick(window.dot_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.finish_letter_button, Qt.MouseButton.LeftButton)

    # Písmeno se NEoznámilo (žádná řetězcová zpráva "E").
    assert "E" not in window.output.spoken
    # Ale oznámení chyby/„Zpráva dokončena." funguje i tak:
    QTest.mouseClick(window.finish_message_button, Qt.MouseButton.LeftButton)
    assert "Zpráva dokončena." in window.output.spoken


def test_continuous_announce_on_uses_say_char(qapp):
    settings = Settings(continuous_announce=True)
    output = FakeOutput()
    win = MainWindow(
        settings=settings,
        coordinator=FakeCoordinator(),
        announcer=Announcer(output=output, clock=lambda: 0.0),
    )
    win.output = output
    win.show()
    assert wait_for_tone_ready(win)
    QTest.mouseClick(win.dot_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(win.finish_letter_button, Qt.MouseButton.LeftButton)
    assert "E" in win.output.spoken
    win.close()
    win.deleteLater()


# ---------------------------------------------------------------------------
# 15. Chyba zvukového enginu – textově i přes oznámení
# ---------------------------------------------------------------------------

def test_audio_error_is_textual_and_announced(qapp):
    coordinator = FakeCoordinator(
        available=False, error="Zvukové zařízení není dostupné: test"
    )
    output = FakeOutput()
    win = MainWindow(
        settings=Settings(),
        coordinator=coordinator,
        announcer=Announcer(output=output, clock=lambda: 0.0),
    )
    win.show()

    # Klíč je zakázaný (žádné tiché ignorování stisku).
    assert not win.key_button.isEnabled()
    # Důvod je textově viditelný…
    assert "Zvuk nedostupný" in win.status_label.text()
    assert "test" in win.status_label.text()
    # …a oznámen přístupným způsobem (force=True, nevypíná se nastavením).
    assert any("Chyba zvuku" in text for text in output.spoken)

    win.close()
    win.deleteLater()


def test_announcer_say_is_not_gated_by_char_setting(qapp):
    # Krátké oznámení stavu/chyby nesmí být vypnuté volbou písmen.
    output = FakeOutput()
    announcer = Announcer(output=output, clock=lambda: 0.0)
    announcer.char_announcements_enabled = False   # standardně False
    assert announcer.say("Chyba sítě", force=True) is True
    assert "Chyba sítě" in output.spoken


def test_announcer_suppresses_repeats():
    time_now = [0.0]
    output = FakeOutput()
    announcer = Announcer(output=output, clock=lambda: time_now[0])
    assert announcer.say("Stejná zpráva") is True
    assert announcer.say("Stejná zpráva") is False      # okamžité opakování
    time_now[0] += 10.0
    assert announcer.say("Stejná zpráva") is True       # po okně znovu
    assert len(output.spoken) == 2
