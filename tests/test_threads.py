"""Testy životního cyklu hlasových vláken a ovládání řeči (E4: 11, 14, 17, 18).

- **Žádný internet, žádné audio zařízení.** „Blokující HTTP“ simuluje
  vlákno, které čeká na ``threading.Event`` uvnitř ``stream()``.
- Výsledky s mockovanou sítí **nedokazují** funkční připojení ke
  Google TTS ani kvalitu reálného hlasu.
- ``pytest-qt`` se nepoužívá – QApplication vzniká vlastní fixture,
  čekání řeší vlastní ``wait_until`` točením event loop.

Položky: 11 (zastavení hlasu za přehrávání), 14 (dokončení zprávy
před čtením), 17 (responzivita GUI během blokovaného požadavku),
18 (žádné vlákno se nezničí dřív než skutečně skončí).
"""

from __future__ import annotations

import os
import threading

import pytest
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from morseapp.announce import Announcer
from morseapp.main_window import MainWindow
from morseapp.settings_store import Settings
from morseapp.speech import SpeechWorker


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


def wait_until(condition, timeout_ms: int = 5000) -> bool:
    """Točí event loop, dokud podmínka neplatí (bez pytest-qt)."""
    from PyQt6.QtCore import QEventLoop, QTimer

    if condition():
        return True
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(10)
    poll.timeout.connect(lambda: condition() and loop.quit())
    poll.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    poll.stop()
    return condition()


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeCoordinator(QObject):
    """Fake AudioCoordinator s rozhraním řeči – bez pygame."""

    speech_finished = pyqtSignal(int)
    speech_failed = pyqtSignal(int, str)

    def __init__(self, available: bool = True) -> None:
        super().__init__()
        self._available = available
        self.error_message = None
        self.calls: list[tuple] = []
        self.played: list[tuple] = []

    @property
    def is_available(self) -> bool:
        return self._available

    def initialize(self) -> bool:
        return self._available

    def prepare_tone(self, block) -> bool:
        return self._available

    def start_tone(self, volume: float = 1.0) -> bool:
        self.calls.append(("start_tone", volume))
        return self._available

    def release_tone(self) -> None:
        self.calls.append(("release_tone",))

    def stop_speech(self) -> None:
        self.calls.append(("stop_speech",))

    def play_speech(self, request_id: int, data: bytes, volume: float) -> bool:
        self.played.append((request_id, data, volume))
        self.calls.append(("play_speech", request_id))
        return True

    def stop_now(self) -> None:
        self.calls.append(("stop_now",))

    def shutdown(self) -> None:
        self.calls.append(("shutdown",))


class FakeOutput:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def speak(self, text, **kwargs):
        self.spoken.append(text)


class _WorkerSignals(QObject):
    completed = pyqtSignal(int, bytes)
    error = pyqtSignal(int, str)
    interrupted = pyqtSignal(int)


class ScriptedSpeechWorker(QObject):
    """Fake pro GUI testy: nikdy neběží, výsledek vypouští test."""

    finished = pyqtSignal()   # nikdy se nevypustí

    def __init__(self, request_id: int, text: str, cache=None, parent=None) -> None:
        super().__init__(parent)
        self.request_id = request_id
        self.text = text
        self.started = False
        self.interrupted = False
        self.signals = _WorkerSignals()

    def start(self) -> None:
        self.started = True

    def requestInterruption(self) -> None:
        self.interrupted = True


class ScriptedFactory:
    def __init__(self) -> None:
        self.created: list[ScriptedSpeechWorker] = []

    def __call__(self, request_id, text, cache) -> ScriptedSpeechWorker:
        worker = ScriptedSpeechWorker(request_id, text, cache)
        self.created.append(worker)
        return worker


class BlockingFactory:
    """Továrna na **skutečná** vlákna SpeechWorker blokující v „síti“.

    ``entered`` = worker je uvnitř blokujícího čtení; ``release`` ho
    pustí dál. Uvolňuje se vždy v teardown, aby vlákno nezůstalo viset.
    """

    def __init__(self) -> None:
        self.created: list[SpeechWorker] = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, request_id, text, cache) -> SpeechWorker:
        worker = SpeechWorker(request_id, text, cache, gtts_factory=self._gtts)
        self.created.append(worker)
        return worker

    def _gtts(self, text, lang, timeout, lang_check):
        outer = self

        class BlockingTTS:
            def stream(self):
                outer.entered.set()
                outer.release.wait(10)      # simulace blokujícího HTTP
                yield b"BLOCKED-MP3"

        return BlockingTTS()

    def shutdown(self) -> None:
        """Pustí všechna blokující vlákna (volá teardown)."""
        self.release.set()


def make_window(qapp, speech_factory) -> MainWindow:
    coordinator = FakeCoordinator()
    output = FakeOutput()
    win = MainWindow(
        settings=Settings(),
        coordinator=coordinator,
        announcer=Announcer(output=output, clock=lambda: 0.0),
        speech_factory=speech_factory,
    )
    win.output = output
    win.coordinator = coordinator
    win.show()
    if not win.key_button.isEnabled():
        from PyQt6.QtCore import QEventLoop, QTimer as QtTimer

        loop = QEventLoop()
        win.tone_ready.connect(loop.quit)
        QtTimer.singleShot(5000, loop.quit)
        loop.exec()
    assert win.key_button.isEnabled()
    return win


@pytest.fixture
def scripted_window(qapp):
    factory = ScriptedFactory()
    win = make_window(qapp, factory)
    win.factory = factory
    yield win
    win.close()
    win.deleteLater()


@pytest.fixture
def blocking_window(qapp):
    factory = BlockingFactory()
    win = make_window(qapp, factory)
    win.factory = factory
    yield win
    factory.shutdown()                       # uvolnit blokující vlákna
    wait_until(lambda: not win._speech_threads, 5000)
    win.close()
    win.deleteLater()


def enter_text(window) -> None:
    """Vloží písmeno E přes tlačítka (bez myši, přes QTest)."""
    QTest.mouseClick(window.dot_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.finish_letter_button, Qt.MouseButton.LeftButton)
    assert window.text_edit.toPlainText() == "E"


# ---------------------------------------------------------------------------
# 11. Zastavení hlasu během přehrávání
# ---------------------------------------------------------------------------

def test_stop_speech_during_playback(scripted_window):
    window = scripted_window
    enter_text(window)
    QTest.mouseClick(window.read_button, Qt.MouseButton.LeftButton)
    worker = window.factory.created[0]
    worker.signals.completed.emit(worker.request_id, b"MP3-DATA")

    # Přehrávání probíhá.
    assert window.coordinator.played == [
        (worker.request_id, b"MP3-DATA", Settings().speech_volume / 100.0)
    ]

    # Zastavit hlas: okamžitě zastaví přehrávání i generování.
    QTest.mouseClick(window.stop_speech_button, Qt.MouseButton.LeftButton)
    assert ("stop_speech",) in window.coordinator.calls
    assert worker.interrupted                    # požádáno o přerušení
    assert "zastaven" in window.status_label.text().lower()
    assert "Hlas zastaven." in window.output.spoken

    # Opožděný výsledek po zastavení se už nepřehraje.
    worker.signals.completed.emit(worker.request_id, b"LATE")
    assert len(window.coordinator.played) == 1


def test_stop_speech_while_generating_only(scripted_window):
    window = scripted_window
    enter_text(window)
    QTest.mouseClick(window.read_button, Qt.MouseButton.LeftButton)
    worker = window.factory.created[0]

    # Generování ještě nedokončeno – tlačítko Zastavit hlas.
    QTest.mouseClick(window.stop_speech_button, Qt.MouseButton.LeftButton)
    assert worker.interrupted
    # Výsledek dorazí později → nesmí se přehrát.
    worker.signals.completed.emit(worker.request_id, b"MP3")
    assert window.coordinator.played == []
    # Přehrávání se vůbec nezahajovalo, koordinátor nebyl volán.
    assert ("stop_speech",) in window.coordinator.calls


# ---------------------------------------------------------------------------
# 14. Dokončení zprávy s rozpracovaným znakem před čtením
# ---------------------------------------------------------------------------

def test_finish_message_completes_char_before_reading(scripted_window):
    window = scripted_window
    # Rozpracovaný znak (E = tečka) bez dokončení:
    QTest.mouseClick(window.dot_button, Qt.MouseButton.LeftButton)
    assert window._decoder.current_code == "."

    QTest.mouseClick(window.finish_message_button, Qt.MouseButton.LeftButton)

    # 1) Znak byl dokončen a pole aktualizováno…
    assert window.text_edit.toPlainText() == "E"
    assert window._decoder.current_code == ""
    # 2) …a teprve potom se četl **tento** aktualizovaný text.
    assert len(window.factory.created) == 1
    assert window.factory.created[0].text == "E"
    assert window.factory.created[0].text == window.text_edit.toPlainText()


# ---------------------------------------------------------------------------
# 17. GUI zůstává responzivní během blokované síťové operace
# ---------------------------------------------------------------------------

def test_gui_responsive_during_blocked_network(blocking_window):
    window = blocking_window
    enter_text(window)

    QTest.mouseClick(window.read_button, Qt.MouseButton.LeftButton)
    assert len(window.factory.created) == 1
    worker = window.factory.created[0]

    # Worker je uvnitř „blokujícího HTTP“ (ve SVÉM vlákně).
    assert window.factory.entered.wait(5.0), "worker se nedostal do vlákna"
    assert worker.isRunning()
    assert worker in window._speech_threads
    assert "generování" in window.status_label.text().lower()

    # GUI vlákno NENÍ zablokované – ovládání reaguje okamžitě.
    QTest.mouseClick(window.dash_button, Qt.MouseButton.LeftButton)
    assert window._decoder.current_code == "-"
    QTest.mouseClick(window.back_symbol_button, Qt.MouseButton.LeftButton)
    assert window._decoder.current_code == ""

    # Po uvolnění sítě se výsledek doručí do GUI a přehraje.
    window.factory.release.set()
    assert wait_until(lambda: window.coordinator.played, 5000)
    rid, data, _volume = window.coordinator.played[0]
    assert rid == worker.request_id
    assert data == b"BLOCKED-MP3"
    # A vlákno se řádně uklidí až po skutečném konci.
    assert wait_until(lambda: worker not in window._speech_threads, 5000)


# ---------------------------------------------------------------------------
# 18. Žádný pracovník se nezničí, dokud skutečně neskončí
# ---------------------------------------------------------------------------

def test_worker_reference_kept_until_thread_finishes(blocking_window):
    print("P1 fixture ready", flush=True)
    window = blocking_window
    enter_text(window)
    print("P2 text entered", flush=True)
    QTest.mouseClick(window.read_button, Qt.MouseButton.LeftButton)
    worker = window.factory.created[0]
    print("P3 read clicked", flush=True)

    assert window.factory.entered.wait(5.0)
    print("P4 blocked in network", flush=True)

    # Požadavek o přerušení ZA BĚHU (vlákno opravdu běží).
    worker.requestInterruption()
    print("P5 interruption requested", flush=True)
    assert worker in window._speech_threads
    assert worker.isRunning()
    assert not worker.isFinished()
    print("P6 asserts ok", flush=True)

    # I po projetí event loop zůstává reference – vlákno žije.
    for _ in range(3):
        QApplication.processEvents()
    print("P7 processed", flush=True)
    assert worker in window._speech_threads
    assert worker.isRunning()
    assert worker.request_id == 1                # objekt je stále použitelný
    print("P8 still alive", flush=True)

    # Teprve skutečné dokončení ho uvolní.
    window.factory.release.set()
    assert wait_until(lambda: not worker.isRunning(), 5000)
    print("P9 thread stopped", flush=True)
    assert wait_until(lambda: worker not in window._speech_threads, 5000)
    print("P10 released", flush=True)
    # Přerušený požadavek se nepřehrál.
    assert window.coordinator.played == []
    print("P11 end of body", flush=True)
