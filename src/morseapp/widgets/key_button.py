"""Morseův klíč – hlavní ovládací prvek zadávání signálů.

Widget odvozený od ``QPushButton``:

- **Myš**: stisk začne tón a spustí měření, uvolnění tón ukončí a
  naměřenou délku předá klasifikátoru. Qt implicitně zachytí myš při
  stisku, takže uvolnění mimo tlačítko dorazí sem (žádné ``grabMouse()``,
  tedy není co uvolňovat). Dlouhé držení nevytváří další signály.
- **Klávesnice**: mezerník začíná/ukončuje tón; události
  ``isAutoRepeat()`` se ignorují; interní příznak ``_pressed`` brání
  dvojímu zpracování. Ztráta fokusu bezpečně ukončí tón bez signálu.
- **Měření**: ``time.monotonic()`` (injektovatelný ``clock`` pro testy).
  Klasifikaci provádí výhradně ``morseapp.classifier.classify`` s
  hodnotami ze ``Settings`` (práh 120 ms, minimum 30 ms); widget
  neobsahuje druhou kopii klasifikační logiky.

Signály:

- ``tone_start`` – začíná tón (stisk).
- ``tone_end`` – tón končí (uvolnění nebo bezpečné přerušení).
- ``symbol_entered('.')`` / ``symbol_entered('-')`` – klasifikovaný signál.

``cancel_press()`` ukončí rozpracovaný stisk bez vytvoření signálu
(používá se při ztrátě fokusu a deaktivaci okna).
"""

from __future__ import annotations

import time
from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QPushButton

from ..classifier import Signal, classify
from ..settings_store import Settings
from ..decoder import DASH_SYMBOL, DOT_SYMBOL

__all__ = ["KeyButton", "DOT_SYMBOL", "DASH_SYMBOL"]


def _default_settings() -> Settings:
    return Settings()


class KeyButton(QPushButton):
    """Morseův klíč ovládaný myší i klávesnicí."""

    tone_start = pyqtSignal()
    tone_end = pyqtSignal()
    symbol_entered = pyqtSignal(str)   # "." nebo "-"

    def __init__(
        self,
        settings_provider: Callable[[], Settings] | None = None,
        clock: Callable[[], float] | None = None,
        parent=None,
    ) -> None:
        """``settings_provider`` vrací aktuální ``Settings``; ``clock``
        vrací čas v sekundách (výchozí ``time.monotonic``)."""
        super().__init__("Morseův klíč", parent)
        self._settings_provider = settings_provider or _default_settings
        self._clock = clock or time.monotonic
        self._pressed = False
        self._press_time = 0.0

        self.setAutoRepeat(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleDescription(
            "Hlavní Morseův klíč. Držte pro zadání signálu: "
            "krátký stisk je tečka, dlouhý stisk je čárka. "
            "Ovládání také mezerníkem."
        )

    # ------------------------------------------------------------------
    # Stav
    # ------------------------------------------------------------------

    @property
    def is_pressed(self) -> bool:
        """``True``, pokud je klíč aktuálně držen."""
        return self._pressed

    # ------------------------------------------------------------------
    # Interní logika stisku
    # ------------------------------------------------------------------

    def _begin(self) -> None:
        if self._pressed:
            return  # opakovaný stisk nic nedělá (žádné vícenásobné signály)
        self._pressed = True
        self._press_time = self._clock()
        self.tone_start.emit()

    def _end(self) -> None:
        if not self._pressed:
            return
        self._pressed = False
        duration_ms = (self._clock() - self._press_time) * 1000.0
        self.tone_end.emit()
        settings = self._settings_provider()
        signal = classify(duration_ms, settings.threshold_ms, settings.min_press_ms)
        if signal is Signal.DOT:
            self.symbol_entered.emit(DOT_SYMBOL)
        elif signal is Signal.DASH:
            self.symbol_entered.emit(DASH_SYMBOL)
        # IGNORE: příliš krátký stisk se nezaznamená.

    def cancel_press(self) -> None:
        """Bezpečně ukončí rozpracovaný stisk **bez** vytvoření signálu."""
        if not self._pressed:
            return
        self._pressed = False
        self.tone_end.emit()

    # ------------------------------------------------------------------
    # Myš
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._begin()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        # Qt doručí událost sem i při puštění mimo tlačítko (implicitní grab).
        if event.button() == Qt.MouseButton.LeftButton:
            self._end()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # Klávesnice
    # ------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space:
            if event.isAutoRepeat():
                event.accept()
                return  # filtr auto-repeatu
            self._begin()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space:
            if event.isAutoRepeat():
                event.accept()
                return
            self._end()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:
        # Ztráta fokusu během držení nesmí nechat tón hrát.
        self.cancel_press()
        super().focusOutEvent(event)
