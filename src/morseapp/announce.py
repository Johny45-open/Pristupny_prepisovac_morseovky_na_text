"""Úzká vrstva nad accessible_output2 pro přístupná oznámení.

Rozlišuje:

- ``say(text)`` – krátké oznámení stavu či chyby; **nikdy** není vypnuto
  nastavením průběžného oznamování; potlačuje opakované totožné zprávy
  v krátkém okně (anti-spam), ale chyby lze vynutit ``force=True``;
- ``say_char(char)`` – volitelné oznámení dokončeného písmene; volá se
  **pouze pokud** je zapnuto ``char_announcements_enabled``
  (standardně **VYPNUTO**, odpovídá ``continuous_announce = False``).

Knihovna accessible_output2 je ověřena v lokálním prostředí: třída
``accessible_output2.outputs.auto.Auto``, metoda ``speak(text, **options)``.
Při selhání za běhu koordinátor chybu zachytí a zůstane stav ``False``
v ``available`` – aplikace nespadne a GUI stav zůstává viditelný textově.

Skutečná spolupráce s NVDA/Narratorem **nebyla automaticky ověřena** –
ručně se kontroluje podle docs/pristupnost_checklist.md.
"""

from __future__ import annotations

import time
from typing import Callable

# Okno pro potlačení opakování stejné zprávy (v sekundách).
DEFAULT_REPEAT_WINDOW_S = 1.5


class Announcer:
    """Odesílá krátká přístupná oznámení; bezpečné při chybě knihovny."""

    def __init__(
        self,
        output=None,
        clock: Callable[[], float] | None = None,
        repeat_window_s: float = DEFAULT_REPEAT_WINDOW_S,
    ) -> None:
        """``output`` a ``clock`` existují pro testy (fake objekt).

        V produkci se vytvoří ``accessible_output2.outputs.auto.Auto``.
        """
        if output is None:
            try:
                from accessible_output2.outputs.auto import Auto

                output = Auto()
            except Exception:
                output = None
        self._output = output
        self._clock = clock or time.monotonic
        self._repeat_window_s = float(repeat_window_s)
        self._last_text: str | None = None
        self._last_time = float("-inf")
        self.available = output is not None
        # Standardně vypnuto (odpovídá continuous_announce = False).
        self.char_announcements_enabled = False

    def say(self, text: str, force: bool = False) -> bool:
        """Krátké oznámení stavu či chyby.

        Potlačí totožné opakované zprávy v okně ``repeat_window_s``;
        ``force=True`` (chyby) potlačení obejde. Vrací ``True``, pokud
        se oznámení skutečně odeslalo.
        """
        if not text or self._output is None:
            return False
        now = self._clock()
        if (
            not force
            and text == self._last_text
            and (now - self._last_time) < self._repeat_window_s
        ):
            return False  # anti-spam
        try:
            self._output.speak(text)
        except Exception:
            self.available = False
            return False
        self._last_text = text
        self._last_time = now
        return True

    def say_char(self, char: str) -> bool:
        """Oznámí dokončené písmeno – **pouze pokud je volba zapnutá**."""
        if not self.char_announcements_enabled:
            return False
        return self.say(char)
