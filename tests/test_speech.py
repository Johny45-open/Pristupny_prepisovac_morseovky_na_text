"""Testy hlasového výstupu (požadavky 1–10, 15–16 z E4).

- Síť je **vždy mockovaná** – žádný test nepotřebuje internet ani
  skutečné audio zařízení. Výsledek s mockovanou sítí **nedokazuje**
  funkční připojení ke Google TTS ani kvalitu reálného hlasu.
- ``SpeechWorker.run()`` se v testech volá přímo (synchronně);
  signály se zachytávají spojením na seznamy.
- GUI testy používají fake koordinátor a „scénářové“ pracovníky,
  kteří nikdy skutečně neběží – výsledky vypouští test ručně.

``pytest-qt`` se nepoužívá – QApplication vzniká vlastní fixture.
"""

from __future__ import annotations

import os

import pytest
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from morseapp.announce import Announcer
from morseapp.main_window import MainWindow
from morseapp.settings_store import Settings
from morseapp.speech import CACHE_MAX_ITEMS, SpeechCache, SpeechWorker


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Fakes: gTTS, pracovník pro GUI, koordinátor, výstup screen readeru
# ---------------------------------------------------------------------------


class FakeGTTS:
    """Napodobuje gTTS: ``stream()`` vrací připravené MP3 části."""

    def __init__(self, chunks: list[bytes] | None = None,
                 error: Exception | None = None,
                 on_stream=None) -> None:
        self.chunks = chunks or []
        self.error = error
        self.on_stream = on_stream      # hook při volání stream()
        self.calls: list[dict] = []

    def stream(self):
        self.calls.append({"stream": True})
        if self.on_stream is not None:
            self.on_stream()
        if self.error is not None:
            raise self.error
        yield from self.chunks


class RecordingFactory:
    """``gtts_factory`` zaznamená volání; lze i selhat."""

    def __init__(self, chunks=None, error=None, on_stream=None) -> None:
        self.created: list[FakeGTTS] = []
        self._chunks = chunks
        self._error = error
        self._on_stream = on_stream

    def __call__(self, text, lang, timeout, lang_check):
        if self._error is not None and not self._chunks:
            raise self._error                     # chyba už v konstruktoru
        fake = FakeGTTS(self._chunks, self._error, self._on_stream)
        fake.text, fake.lang, fake.timeout = text, lang, timeout
        self.created.append(fake)
        return fake


def capture(worker: SpeechWorker) -> dict:
    """Připojí signály pracovníka na seznamy pro pozdější aserci."""
    log = {"completed": [], "error": [], "interrupted": []}
    worker.signals.completed.connect(
        lambda rid, data: log["completed"].append((rid, data))
    )
    worker.signals.error.connect(
        lambda rid, msg: log["error"].append((rid, msg))
    )
    worker.signals.interrupted.connect(
        lambda rid: log["interrupted"].append(rid)
    )
    return log


def run_worker(request_id, text, cache=None, factory=None) -> tuple[SpeechWorker, dict]:
    """Vytvoří pracovníka, zachytí signály a **synchronně** spustí run()."""
    factory = factory if factory is not None else RecordingFactory([b"mp3-data"])
    worker = SpeechWorker(request_id, text, cache, gtts_factory=factory)
    log = capture(worker)
    worker.run()
    return worker, log


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


class ScriptedSpeechWorker(QObject):
    """Fake pracovník pro GUI testy: nic neběží, výsledek vypouští test.

    Nikdy nevytvoří vlákno ani síťový požadavek. ``finished`` se
    neodesílá, takže zůstává v ``_speech_threads`` (žádné mazání).
    """

    finished = pyqtSignal()   # nikdy se nevypustí – pro kompatibilitu API

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


class _WorkerSignals(QObject):
    completed = pyqtSignal(int, bytes)
    error = pyqtSignal(int, str)
    interrupted = pyqtSignal(int)


class RecordingFactoryGui:
    """Továrna pro MainWindow – vytvoří ScriptedSpeechWorker a zaznamená je."""

    def __init__(self) -> None:
        self.created: list[ScriptedSpeechWorker] = []

    def __call__(self, request_id, text, cache) -> ScriptedSpeechWorker:
        worker = ScriptedSpeechWorker(request_id, text, cache)
        self.created.append(worker)
        return worker


@pytest.fixture
def window(qapp):
    settings = Settings()
    coordinator = FakeCoordinator()
    output = FakeOutput()
    factory = RecordingFactoryGui()
    win = MainWindow(
        settings=settings,
        coordinator=coordinator,
        announcer=Announcer(output=output, clock=lambda: 0.0),
        speech_factory=factory,
    )
    win.output = output
    win.coordinator = coordinator
    win.factory = factory
    win.show()
    # Počkat na přípravu tónu (bez pytest-qt).
    from PyQt6.QtCore import QEventLoop, QTimer

    if not win.key_button.isEnabled():
        loop = QEventLoop()
        win.tone_ready.connect(loop.quit)
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
    assert win.key_button.isEnabled(), "tón se nepřipravil"
    yield win
    win.close()
    win.deleteLater()


# ---------------------------------------------------------------------------
# 1–2. Úspěšné generování a kompletní data se správným ID
# ---------------------------------------------------------------------------

def test_successful_generation_returns_complete_mp3():
    factory = RecordingFactory(chunks=[b"AAA", b"BBB", b"CCC"])
    _, log = run_worker(7, "Ahoj", factory=factory)
    assert log["completed"] == [(7, b"AAABBBCCC")]   # ID i kompletní data
    assert log["error"] == []
    assert log["interrupted"] == []


def test_completed_carries_request_id_and_full_concatenation():
    factory = RecordingFactory(chunks=[b"12", b"34", b"56"])
    worker, log = run_worker(42, "test", factory=factory)
    assert worker.request_id == 42
    rid, data = log["completed"][0]
    assert rid == 42
    assert data == b"123456"
    # Data jsou skutečně MP3-like buffer, ne jednotlivá písmena.
    assert isinstance(data, bytes)


# ---------------------------------------------------------------------------
# 3. Cache hit bez nového volání gTTS
# ---------------------------------------------------------------------------

def test_cache_hit_skips_network():
    cache = SpeechCache()
    cache.put("Ahoj", "cs", b"cached-mp3")

    def must_not_be_called(**kwargs):
        raise AssertionError("při cache hitu se nesmí volat gTTS")

    factory = RecordingFactory(chunks=[b"new"])
    worker = SpeechWorker(1, "Ahoj", cache, gtts_factory=factory)
    log = capture(worker)
    worker.run()
    assert log["completed"] == [(1, b"cached-mp3")]
    assert factory.created == []          # gTTS se vůbec nevytvořil


def test_cache_hit_still_respects_interruption():
    cache = SpeechCache()
    cache.put("text", "cs", b"data")
    factory = RecordingFactory()
    worker = SpeechWorker(3, "text", cache, gtts_factory=factory)
    log = capture(worker)
    worker.requestInterruption()          # ještě před startem
    worker.run()
    assert log["completed"] == []
    assert log["interrupted"] == [3]


# ---------------------------------------------------------------------------
# 4. LRU chování při překročení 50 položek
# ---------------------------------------------------------------------------

def test_lru_capacity_is_50():
    assert CACHE_MAX_ITEMS == 50
    cache = SpeechCache()
    for i in range(CACHE_MAX_ITEMS + 1):
        cache.put(f"t{i}", "cs", f"d{i}".encode())
    assert len(cache) == CACHE_MAX_ITEMS
    assert cache.get("t0", "cs") is None            # nejstarší vypadl
    assert cache.get("t50", "cs") == b"d50"


def test_lru_get_moves_item_to_end():
    cache = SpeechCache(max_items=3)
    cache.put("a", "cs", b"a")
    cache.put("b", "cs", b"b")
    cache.put("c", "cs", b"c")
    assert cache.get("a", "cs") == b"a"             # „a“ se použil
    cache.put("d", "cs", b"d")                      # přetečení
    assert cache.get("a", "cs") == b"a"             # přežil (byl nejnovější)
    assert cache.get("b", "cs") is None             # vypadl „b“


def test_cache_key_includes_lang_and_text():
    cache = SpeechCache()
    cache.put("ahoj", "cs", b"cs")
    assert cache.get("ahoj", "en") is None          # jiný jazyk
    assert cache.get("Ahoj", "cs") is None          # jiný text (přesná shoda)
    assert cache.get("ahoj", "cs") == b"cs"


# ---------------------------------------------------------------------------
# 5. Ukládání pouze kompletních úspěšných výsledků
# ---------------------------------------------------------------------------

def test_error_result_is_not_cached():
    cache = SpeechCache()
    factory = RecordingFactory(error=ConnectionError("boom"))
    worker = SpeechWorker(1, "text", cache, gtts_factory=factory)
    log = capture(worker)
    worker.run()
    assert log["error"] and log["completed"] == []
    assert len(cache) == 0                          # chyba se neukládá


def test_interrupted_result_is_not_cached():
    cache = SpeechCache()

    def on_stream():
        worker.requestInterruption()

    factory = RecordingFactory(chunks=[b"part"], on_stream=on_stream)
    worker = SpeechWorker(1, "text", cache, gtts_factory=factory)
    log = capture(worker)
    worker.run()
    assert log["interrupted"] == [1]
    assert log["completed"] == []
    assert len(cache) == 0                          # přerušení se neukládá


def test_success_is_cached():
    cache = SpeechCache()
    run_worker(1, "text", cache, factory=RecordingFactory([b"data"]))
    assert cache.get("text", "cs") == b"data"


def test_empty_text_never_reaches_network():
    # Worker prázdný text odmítne už konstruktorem – žádný gTTS objekt.
    with pytest.raises(ValueError):
        SpeechWorker(1, "", SpeechCache(), gtts_factory=RecordingFactory())


# ---------------------------------------------------------------------------
# 6. Timeout / síťová výjimka → chybový signál
# ---------------------------------------------------------------------------

def test_network_exception_emits_error_with_id():
    factory = RecordingFactory(error=TimeoutError("překročen timeout 5 s"))
    worker, log = run_worker(9, "text", factory=factory)
    assert log["completed"] == []
    assert log["error"] == [(9, "překročen timeout 5 s")]
    assert log["interrupted"] == []


def test_exception_during_stream_emits_error():
    # Výjimka přímo ze streamu (ne v konstruktoru) → chyba s ID.
    fake = FakeGTTS(error=ConnectionError("middleware down"))
    worker = SpeechWorker(1, "text", gtts_factory=lambda **kw: fake)
    log = capture(worker)
    worker.run()
    assert log["error"] == [(1, "middleware down")]
    assert log["completed"] == []


def test_error_does_not_escape_from_run():
    # Výjimka nesmí uniknout z run() – jinak by mohla shodit aplikaci.
    factory = RecordingFactory(error=RuntimeError("neočekávaná"))
    worker = SpeechWorker(1, "text", gtts_factory=factory)
    log = capture(worker)
    worker.run()                                    # nesmí spadnout
    assert log["error"]


# ---------------------------------------------------------------------------
# 7–9. Přerušení: před streamem, mezi částmi, během blokující části
# ---------------------------------------------------------------------------

def test_interruption_before_first_chunk():
    factory = RecordingFactory(chunks=[b"a", b"b"])
    worker = SpeechWorker(5, "text", gtts_factory=factory)
    log = capture(worker)
    worker.requestInterruption()                  # ještě před run()
    worker.run()
    assert log["interrupted"] == [5]
    assert log["completed"] == []
    assert factory.created == []                  # gTTS se ani nevytvořil


def test_interruption_between_chunks():
    """Přerušení „mezi“ částmi: nastane při prvním čtení, takže worker
    ještě **nevyžádá žádnou další část** – po první části se zastaví."""
    state = {"worker": None, "reads": 0}

    class Stream:
        def __iter__(self):
            return self

        def __next__(self):
            state["reads"] += 1
            if state["reads"] == 1:
                # Příznak vznikne těsně po dodání první části
                # (odpovídá přerušení vyžádanému mezi dvěma čteními).
                state["worker"].requestInterruption()
                return b"chunk1"
            raise AssertionError("worker nesmí číst další část")

    fake = FakeGTTS()
    fake.stream = Stream
    worker = SpeechWorker(6, "text", gtts_factory=lambda **kw: fake)
    state["worker"] = worker
    log = capture(worker)
    worker.run()
    assert log["interrupted"] == [6]
    assert log["completed"] == []                 # neúplný výsledek neodchází
    assert state["reads"] == 1                    # další část nevyžádal


def test_interruption_during_blocking_read_no_success():
    """Přerušení vyžádané **během** blokujícího čtení části.

    Po návratu z blokující části worker zpracuje už načtená data,
    ale podle příznaku nedočte zbytek streamu a neodešle neúplná data
    jako úspěšný výsledek.
    """
    state = {"worker": None, "reads": 0}

    class Stream:
        def __iter__(self):
            return self

        def __next__(self):
            state["reads"] += 1
            if state["reads"] == 1:
                return b"chunk1"
            if state["reads"] == 2:
                # Příznak vznikne až uvnitř „blokujícího“ čtení a část
                # se ještě stihne vrátit.
                state["worker"].requestInterruption()
                return b"chunk2"
            raise AssertionError("worker nesmí pokračovat do další části")

    fake = FakeGTTS()
    fake.stream = Stream
    worker = SpeechWorker(8, "text", gtts_factory=lambda **kw: fake)
    state["worker"] = worker
    log = capture(worker)
    worker.run()
    assert log["interrupted"] == [8]
    assert log["completed"] == []                 # žádný neúspěšný „úspěch“
    assert state["reads"] == 2                    # třetí část nenačetl


# ---------------------------------------------------------------------------
# 10. Ignorování opožděného výsledku staršího požadavku (GUI)
# ---------------------------------------------------------------------------

def test_stale_result_older_request_is_ignored(window):
    # Nejdřív nějaký text, jinak by šlo o test prázdného textu.
    QTest.mouseClick(window.dot_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.finish_letter_button, Qt.MouseButton.LeftButton)  # E

    QTest.mouseClick(window.read_button, Qt.MouseButton.LeftButton)
    assert len(window.factory.created) == 1
    first = window.factory.created[0]

    # Druhý požadavek zneplatní první.
    QTest.mouseClick(window.read_button, Qt.MouseButton.LeftButton)
    assert len(window.factory.created) == 2
    second = window.factory.created[1]
    assert first.interrupted                    # starý požadavek přerušen
    assert first.request_id != second.request_id

    # Opožděný výsledek starého požadavku se NESMÍ přehrát.
    first.signals.completed.emit(first.request_id, b"stale")
    assert window.coordinator.played == []

    # Aktuální požadavek se přehraje.
    second.signals.completed.emit(second.request_id, b"fresh")
    assert window.coordinator.played == [
        (second.request_id, b"fresh", Settings().speech_volume / 100.0)
    ]


def test_error_of_stale_request_is_not_announced(window):
    QTest.mouseClick(window.dot_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.finish_letter_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.read_button, Qt.MouseButton.LeftButton)
    first = window.factory.created[0]
    QTest.mouseClick(window.read_button, Qt.MouseButton.LeftButton)

    before = list(window.output.spoken)
    first.signals.error.emit(first.request_id, "stará chyba")
    assert window.output.spoken == before         # zastaralá chyba se nehlásí


# ---------------------------------------------------------------------------
# 15. Prázdný text bez síťového požadavku
# ---------------------------------------------------------------------------

def test_empty_text_creates_no_worker_and_is_announced(window):
    # Žádný text → klávesa „Přečíst“ nesmí vytvořit požadavek.
    assert window._decoder.text == ""
    QTest.mouseClick(window.read_button, Qt.MouseButton.LeftButton)
    assert window.factory.created == []           # žádný worker, žádná síť
    assert any("prázdný" in text.lower() for text in window.output.spoken)
    assert "prázdný" in window.status_label.text().lower()


def test_empty_text_after_message_also_skipped(window):
    # Dokončení zprávy bez jediného znaku: přečte se jen hláška, ne síť.
    QTest.mouseClick(window.finish_message_button, Qt.MouseButton.LeftButton)
    assert window.factory.created == []
    assert "Zpráva dokončena." in window.output.spoken


# ---------------------------------------------------------------------------
# 16. continuous_announce = False neoznamuje písmena (explicitní čtení ano)
# ---------------------------------------------------------------------------

def test_default_announce_off_but_explicit_reading_works(window):
    assert Settings().continuous_announce is False
    QTest.mouseClick(window.dot_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.finish_letter_button, Qt.MouseButton.LeftButton)
    assert "E" not in window.output.spoken         # písmeno se neoznámilo

    # Explicitní tlačítko „Přečíst“ NENÍ tímto nastavením blokované.
    QTest.mouseClick(window.read_button, Qt.MouseButton.LeftButton)
    assert len(window.factory.created) == 1
    worker = window.factory.created[0]
    assert worker.text == "E"
    worker.signals.completed.emit(worker.request_id, b"mp3")
    assert window.coordinator.played != []


def test_reading_uses_result_text_not_letters(window):
    # Do gTTS jde normální text, nikoli vyhláskování po písmenech.
    QTest.mouseClick(window.dot_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.dash_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.finish_letter_button, Qt.MouseButton.LeftButton)  # A
    QTest.mouseClick(window.read_button, Qt.MouseButton.LeftButton)
    worker = window.factory.created[-1]
    assert worker.text == "A"                     # „A“, ne „. -“
