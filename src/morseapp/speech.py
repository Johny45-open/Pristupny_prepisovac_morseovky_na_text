"""Hlasový pracovník: gTTS → MP3 data + sdílená LRU mezipaměť (E4).

``SpeechWorker`` je úloha založená na ``QThread``. Provádí **jen síť**
a ukládání do mezipaměti; nikdy se nedotkne ``pygame.mixer`` (ten řídí
výhradně ``AudioCoordinator``). Výsledek předá signálem s ID požadavku.

gTTS API nainstalované verze 2.5.4 (ověřeno):

- ``gTTS(text, lang="cs", timeout=..., lang_check=False)`` – ``timeout``
  je přímo parametr; ``lang_check=False`` šetří zbytečný síťový požadavek
  na ověření jazyka (jazyk ``cs`` je pevně dán);
- ``stream()`` vrací iterátor MP3 částí – umožňuje kontrolu přerušení
  **mezi** částmi.

Přerušování – tři odlišné věci:

1. ``requestInterruption()`` – kooperativní příznak. **Nezruší** právě
   probíhající blokující HTTP požadavek; ten je ohraničen jen
   ``timeout`` (výchozí 5 s na požadavek).
2. Worker příznak kontroluje **před každým** ``next()`` ve streamu i
   před odesláním výsledku – po návratu z blokující části proto
   nepokračuje do dalších částí a **nikdy neodešle neúspěšný/neúplný
   výsledek jako úspěšný**.
3. Ukončení celého vlákna – ``run()`` se vždy vrátí; ``QThread`` se
   nikdy nezničí dříve než po skutečném ``finished`` (reference drží
   ``MainWindow``; úplné řízené zavření dokončí ``shutdown.py`` v E5).

``interrupted`` signál se odesílá jen, pokud bylo přerušení vyžádáno –
zastaralý požadavek se nehlásí jako chyba opakovaně.
"""

from __future__ import annotations

import io
import threading
from collections import OrderedDict

from PyQt6.QtCore import QObject, QThread, pyqtSignal

# Timeout jednoho síťového požadavku gTTS (sekundy).
SOCKET_TIMEOUT = 5.0
# Maximální počet položek LRU mezipaměti (dle plánu 50).
CACHE_MAX_ITEMS = 50
LANGUAGE = "cs"


class SpeechCache:
    """Thread-safe LRU mezipaměť kompletních MP3 dat – pouze v paměti.

    Klíč = (přesný text, jazyk). Ukládají se **jen kompletní úspěšná**
    data; chyby, přerušení a neúplné výstupy se neukládají.
    """

    def __init__(self, max_items: int = CACHE_MAX_ITEMS) -> None:
        if max_items <= 0:
            raise ValueError("max_items musí být kladné")
        self._max_items = max_items
        self._items: OrderedDict[tuple[str, str], bytes] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, text: str, lang: str) -> bytes | None:
        """Vrátí data a přesune položku na konec LRU pořadí."""
        key = (text, lang)
        with self._lock:
            if key not in self._items:
                return None
            self._items.move_to_end(key)
            return self._items[key]

    def put(self, text: str, lang: str, data: bytes) -> None:
        """Uloží kompletní data; při přetečení odstraní nejpoužívanější."""
        if not data:
            return  # prázdná/nedokončená data se neukládají
        key = (text, lang)
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
            self._items[key] = data
            while len(self._items) > self._max_items:
                self._items.popitem(last=False)   # nejméně nedávno použitá

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class _SpeechWorkerSignals(QObject):
    completed = pyqtSignal(int, bytes)   # request_id, kompletní MP3
    error = pyqtSignal(int, str)         # request_id, popis chyby
    interrupted = pyqtSignal(int)        # request_id


class SpeechWorker(QThread):
    """Generuje MP3 data přes gTTS mimo GUI vlákno.

    Použití::

        worker = SpeechWorker(request_id, text, cache)
        worker.signals.completed.connect(on_completed)
        worker.start()
        ...
        worker.requestInterruption()      # kooperativní přerušení
    """

    def __init__(
        self,
        request_id: int,
        text: str,
        cache: SpeechCache | None = None,
        lang: str = LANGUAGE,
        timeout: float = SOCKET_TIMEOUT,
        gtts_factory=None,
        parent=None,
    ) -> None:
        """``gtts_factory(text, lang, timeout, lang_check)`` existuje pro
        testy; výchozí je skutečná ``gtts.gTTS``."""
        super().__init__(parent)
        if not text:
            raise ValueError("text nesmí být prázdný – neposílá se do sítě")
        self._request_id = int(request_id)
        self._text = text
        self._lang = lang
        self._timeout = timeout
        self._cache = cache
        if gtts_factory is None:
            from gtts import gTTS as _gTTS

            def gtts_factory(text, lang, timeout, lang_check):  # noqa: F811
                return _gTTS(
                    text, lang=lang, timeout=timeout, lang_check=lang_check
                )
        self._gtts_factory = gtts_factory
        self.signals = _SpeechWorkerSignals()
        # Vlastní kooperativní příznak (viz requestInterruption níže).
        self._manual_interrupt = False
        self._interrupt_lock = threading.Lock()

    @property
    def request_id(self) -> int:
        return self._request_id

    def requestInterruption(self) -> None:
        """Kooperativní požadavek na ukončení – funkční kdykoli.

        Qt6 **ignoruje** ``QThread.requestInterruption()`` u vlákna,
        které ještě nikdy nebylo spuštěno (ověřeno lokálně proti
        nainstalovanému PyQt6), a tím by šly obcházet testy i
        okamžité zrušení ještě nerozběhlého požadavku. Proto tento
        přepis nastavuje i **vlastní příznak**, který ``run()``
        kontroluje spolu s příznakem Qt. Volání Qt ponecháváme, aby
        za běhu platil i standardní mechanismus.
        """
        with self._interrupt_lock:
            self._manual_interrupt = True
        super().requestInterruption()   # za běhu nastaví i Qt příznak

    def _interrupt_requested(self) -> bool:
        """``True``, pokud bylo požádáno o přerušení (náš i Qt příznak)."""
        with self._interrupt_lock:
            if self._manual_interrupt:
                return True
        return self.isInterruptionRequested()

    # ------------------------------------------------------------------

    def run(self) -> None:
        """Tělo vlákna – nikdy nenechá výjimku uniknout."""
        request_id = self._request_id
        try:
            # Cache hit = žádný síťový požadavek.
            if self._cache is not None:
                cached = self._cache.get(self._text, self._lang)
                if cached is not None:
                    if not self._interrupt_requested():
                        self.signals.completed.emit(request_id, cached)
                    else:
                        self.signals.interrupted.emit(request_id)
                    return
            if self._interrupt_requested():
                self.signals.interrupted.emit(request_id)
                return

            tts = self._gtts_factory(
                text=self._text,
                lang=self._lang,
                timeout=self._timeout,
                lang_check=False,
            )
            buffer = io.BytesIO()
            iterator = iter(tts.stream())
            while True:
                # Kontrola PŘED každým blokujícím next() – včetně první.
                if self._interrupt_requested():
                    self.signals.interrupted.emit(request_id)
                    return
                try:
                    chunk = next(iterator)
                except StopIteration:
                    break
                buffer.write(chunk)

            # Přerušení vyžádané během posledního blokujícího čtení:
            # neúspěšný výsledek se NEODEŠLE jako úspěšný.
            if self._interrupt_requested():
                self.signals.interrupted.emit(request_id)
                return

            data = buffer.getvalue()
            if not data:
                self.signals.error.emit(request_id, "Převod nevrátil žádná data.")
                return
            if self._cache is not None:
                self._cache.put(self._text, self._lang, data)
            self.signals.completed.emit(request_id, data)
        except Exception as exc:  # síť, timeout, chyba gTTS
            if self._interrupt_requested():
                # Přerušený požadavek se nehlásí jako opakovaná chyba.
                self.signals.interrupted.emit(request_id)
                return
            self.signals.error.emit(request_id, str(exc) or type(exc).__name__)
