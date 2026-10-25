"""Modul asynchronního a řízeného ukončení aplikace (etapa E5).

Řídí bezpečné uzavření aplikace bez blokujícího čekání v hlavním GUI vlákně:
1. Zabrání spouštění nových úloh (stav SHUTTING_DOWN).
2. Zastaví tón i přehrávanou řeč přes AudioCoordinator.
3. Požádá běžící pracovníky (SpeechWorker, ToneWorker / QThreadPool)
   o kooperativní přerušení (``requestInterruption()``).
4. Udržuje reference na běžící ``QThread`` v aktivním seznamu
   ("hřbitov" / referenční buffer), dokud každý z nich neemituje
   signál ``finished``.
5. Event loop běží dál; čeká se asynchronně přes QTimer / signály.
6. Až všichni pracovníci skončí, bezpečně se ukončí zvukový systém
   (``pygame.mixer.quit()``) a zavolá se ``QApplication.quit()``.

Žádný QThread se NIKDY neničí násilně (žádné `terminate()`).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QApplication
    from .audio import AudioCoordinator

logger = logging.getLogger(__name__)


class ApplicationShutdown(QObject):
    """Koordinátor asynchronního a bezpečeného ukončení aplikace."""

    all_done = pyqtSignal()

    def __init__(
        self,
        app: QApplication,
        coordinator: AudioCoordinator,
        threads: list[QThread],
        on_finished: Callable[[], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._app = app
        self._coordinator = coordinator
        self._threads = list(threads)  # kopie seznamu živých vláken
        self._on_finished = on_finished
        self._shutting_down = False
        self._check_timer: QTimer | None = None

    @property
    def is_shutting_down(self) -> bool:
        return self._shutting_down

    def start_shutdown(self) -> None:
        """Zahájí proces asynchronního shutdownu (pouze jednou)."""
        if self._shutting_down:
            return
        self._shutting_down = True

        # 1. Okamžitě zastavit veškerý zvuk a tón
        try:
            self._coordinator.stop_now()
        except Exception:
            pass
        try:
            self._coordinator.shutdown()
        except Exception:
            pass

        # 2. Poslat požadavek na přerušení všem známým vláknům
        for thread in self._threads:
            if thread is not None:
                try:
                    thread.requestInterruption()
                except Exception:
                    pass

        # 3. Spustit asynchronní kontrolu dokončení vláken (neblokující QTimer)
        timer = QTimer(self)
        timer.setSingleShot(False)
        timer.timeout.connect(self._check_threads_finished)
        self._check_timer = timer
        timer.start(50)  # kontrola každých 50 ms

        # Okamžitá první kontrola (pokud už žádná vlákna neběží)
        self._check_threads_finished()

    def _check_threads_finished(self) -> None:
        """Zkontroluje, která vlákna ještě běží."""
        # Odfiltrovat vlákna, která již neběží (isRunning() == False)
        active = [t for t in self._threads if t is not None and t.isRunning()]
        self._threads = active

        if active:
            # Stále některá vlákna běží – event loop běží dál, počkáme na další tick
            return

        # Všichni pracovníci skončili!
        if self._check_timer is not None:
            self._check_timer.stop()
            self._check_timer = None

        # Bezpečné ukončení mixeru / audia
        try:
            import sys
            pygame_mod = sys.modules.get("pygame")
            if pygame_mod is not None and hasattr(pygame_mod, "mixer"):
                if pygame_mod.mixer.get_init():
                    pygame_mod.mixer.quit()
        except Exception:
            pass

        self.all_done.emit()
        if self._on_finished is not None:
            try:
                self._on_finished()
            except Exception:
                pass

        # Nakonec ukončit aplikaci
        try:
            self._app.quit()
        except Exception:
            pass
