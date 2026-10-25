"""Stavový automat dekodéru Morseovy abecedy – čistý Python, bez PyQt6.

Deterministické časování: modul nepoužívá ``QTimer``, ``sleep()`` ani
reálný čas. Volající předává čas v milisekundách (např. z
``time.monotonic() * 1000``) metodám ``on_symbol(symbol, now_ms)`` a
``tick(now_ms)``.

API dekodéru:

- ``on_symbol(symbol, now_ms)`` – přijme tečku ``"."`` nebo čárku ``"-"``.
  Pokud už existuje rozpracovaný znak a prodleva ``letter_gap_ms`` už
  uplynula, **nejdřív dokončí předchozí znak** (i bez samostatného
  ``tick()``) a teprve pak přidá nový signál.
- ``tick(now_ms)`` – kontrola automatického dokončení písmene (a
  volitelné automatické mezeru); vrátí výsledek dokončení nebo ``None``.
- ``finalize_letter(now_ms)`` – ruční dokončení písmene.
- ``word_space(now_ms)`` – ruční mezeru mezi slovy; nejdřív dokončí
  rozpracovaný znak.
- ``finish_message(now_ms)`` – dokončí zprávu včetně posledního
  rozpracovaného písmene a ořízne koncovou mezeru.
- ``backspace_symbol()`` – smaže poslední signál z rozpracovaného znaku
  (vrací ``False``, pokud není co mazat).
- ``backspace_char(now_ms)`` – smaže poslední dokončený znak (vrací
  ``False``, pokud není co mazat).

Stavy a chování:

- ``PARTIAL`` – znak je rozpracovaný (``current_code`` neprázdný);
  ještě není v textu, jen se zobrazuje jako ``current_code``.
- ``MISSING`` – ``finalize_letter``/``word_space``/``finish_message``
  zavolány, ale žádný signál nezadal. nic se nepřidá, vrací status.
- ``UNKNOWN`` – dokončený kód není v tabulce; do textu se zapíše
  viditelný placeholder ``[kód]`` (např. ``[......]``), aby uživatel
  přišel o informaci o chybě. Aplikace přitom nespadne.
- ``OK`` – znak úspěšně zdekódován a přidán do textu.

Automatické vkládání mezer mezi slovy je **standardně vypnuté**
(``auto_word_space=False``); dlouhá pauza sama o sobě nikdy nevytvoří
mezeru. Volitelný režim používá samostatnou prodlevu ``auto_word_gap_ms``
(default 3500 ms) a při zapnutí vkládá nejvýše jednu mezeru.

Pravidla mezer: žádná na začátku textu, opakované mezery se slučují,
koncová mezera se ořízne při ``finish_message()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .morse_table import decode

DOT_SYMBOL = "."
DASH_SYMBOL = "-"
_VALID_SYMBOLS = frozenset({DOT_SYMBOL, DASH_SYMBOL})

DEFAULT_LETTER_GAP_MS = 1200.0
DEFAULT_AUTO_WORD_GAP_MS = 3500.0


class DecodeStatus(Enum):
    """Status poslední operace s textem."""

    OK = auto()        # znak zdekódován a přidán
    UNKNOWN = auto()   # kód není v tabulce → přidán placeholder [kód]
    MISSING = auto()   # žádný signál – nic se nepřidalo
    NOOP = auto()      # operace nic nezměnila (např. opakovaná mezera)


@dataclass(frozen=True)
class DecodeResult:
    """Výsledek operace, která může dokončit znak."""

    status: DecodeStatus
    code: str | None          # dokončený Morseův kód (None u MISSING/NOOP)
    char: str | None          # zdekódovaný znak (None u UNKNOWN/MISSING/NOOP)
    appended: str             # co se přesně přidalo do textu ("" pokud nic)
    text: str                 # aktuální úplný text

    @property
    def ok(self) -> bool:
        return self.status is DecodeStatus.OK


def _noop(text: str) -> DecodeResult:
    return DecodeResult(DecodeStatus.MISSING, None, None, "", text)


class Decoder:
    """Stavový automat Morseova dekodéru."""

    def __init__(
        self,
        letter_gap_ms: float = DEFAULT_LETTER_GAP_MS,
        auto_word_space: bool = False,
        auto_word_gap_ms: float = DEFAULT_AUTO_WORD_GAP_MS,
    ) -> None:
        if letter_gap_ms <= 0:
            raise ValueError("letter_gap_ms musí být kladné")
        if auto_word_gap_ms <= 0:
            raise ValueError("auto_word_gap_ms musí být kladné")
        self._letter_gap_ms = float(letter_gap_ms)
        self._auto_word_space = bool(auto_word_space)
        self._auto_word_gap_ms = float(auto_word_gap_ms)

        self._current: list[str] = []   # rozpracované signály
        self._tokens: list[str] = []    # dokončené části textu (znaky a mezery)
        self._last_event_ms: float | None = None  # čas posledního signálu
        self._auto_space_added = False  # zabrání opakované auto-mezeře

    # ------------------------------------------------------------------
    # Stav
    # ------------------------------------------------------------------

    @property
    def current_code(self) -> str:
        """Rozpracovaný Morseův kód (např. ``".-"``); prázdný, pokud nic."""
        return "".join(self._current)

    @property
    def is_partial(self) -> bool:
        """Stav ``PARTIAL``: existuje rozpracovaný znak."""
        return bool(self._current)

    @property
    def text(self) -> str:
        """Aktuální úplný text (bez rozpracovaného znaku)."""
        return "".join(self._tokens)

    @property
    def auto_word_space_enabled(self) -> bool:
        return self._auto_word_space

    def set_auto_word_space(self, enabled: bool, auto_word_gap_ms: float | None = None) -> None:
        """Zapne/vypne volitelný automatický režim mezer."""
        self._auto_word_space = bool(enabled)
        if auto_word_gap_ms is not None:
            if auto_word_gap_ms <= 0:
                raise ValueError("auto_word_gap_ms musí být kladné")
            self._auto_word_gap_ms = float(auto_word_gap_ms)

    # ------------------------------------------------------------------
    # Přidávání textu (hlídá pravidla mezer)
    # ------------------------------------------------------------------

    def _append_char(self, char: str) -> str:
        if not self._tokens and char == " ":
            return ""  # žádná mezera na začátku textu
        if self._tokens and self._tokens[-1] == " " and char == " ":
            self._tokens[-1] = char  # opakovaná mezera se slučuje
            return char
        self._tokens.append(char)
        return char

    def _append_space(self) -> str:
        if not self._tokens:
            return ""  # žádná mezera na začátku textu
        if self._tokens[-1] == " ":
            return ""  # opakovaná mezera → nic
        self._tokens.append(" ")
        return " "

    # ------------------------------------------------------------------
    # Dokončování znaku
    # ------------------------------------------------------------------

    def _finalize_current(self) -> DecodeResult:
        """Dokončí rozpracovaný znak; bez signálu vrací MISSING."""
        if not self._current:
            return _noop(self.text)
        code = "".join(self._current)
        self._current = []
        char = decode(code)
        if char is None:
            # UNKNOWN: viditelný placeholder, informace se neztratí.
            appended = self._append_char(f"[{code}]")
            return DecodeResult(DecodeStatus.UNKNOWN, code, None, appended, self.text)
        appended = self._append_char(char)
        return DecodeResult(DecodeStatus.OK, code, char, appended, self.text)

    def _auto_finalize_if_expired(self, now_ms: float) -> DecodeResult | None:
        """Dokončí znak, pokud prodleva od posledního signálu vypršela."""
        if not self._current or self._last_event_ms is None:
            return None
        if now_ms - self._last_event_ms >= self._letter_gap_ms:
            return self._finalize_current()
        return None

    def _maybe_auto_space(self, now_ms: float) -> None:
        """Volitelná automatická mezera (standardně vypnuto)."""
        if not self._auto_word_space or self._auto_space_added:
            return
        if self._last_event_ms is None:
            return
        if now_ms - self._last_event_ms >= self._auto_word_gap_ms:
            if self._append_space():
                self._auto_space_added = True

    # ------------------------------------------------------------------
    # Veřejné operace
    # ------------------------------------------------------------------

    def on_symbol(self, symbol: str, now_ms: float) -> DecodeResult | None:
        """Přijme tečku nebo čárku.

        Pokud od posledního signálu uplynula prodleva pro dokončení
        písmene, **nejdřív dokončí předchozí znak** (vrací jeho výsledek)
        a nový signál přidá až potom; výsledek nového znaku je zatím
        ``PARTIAL`` (vrací se ``None``). Bez prodlevy vrací ``None``.
        """
        if symbol not in _VALID_SYMBOLS:
            raise ValueError(f"neplatný symbol: {symbol!r}")

        finalize_result: DecodeResult | None = None
        # Hraniční případ: nový signál po vypršení prodlevy dokončí starý znak.
        if self._current and self._last_event_ms is not None:
            if now_ms - self._last_event_ms >= self._letter_gap_ms:
                finalize_result = self._finalize_current()

        self._current.append(symbol)
        self._last_event_ms = now_ms
        self._auto_space_added = False
        return finalize_result

    def tick(self, now_ms: float) -> DecodeResult | None:
        """Kontrola automatického dokončení; ``None``, pokud se nic neděje."""
        result = self._auto_finalize_if_expired(now_ms)
        if result is not None:
            self._last_event_ms = now_ms  # znak právě skončil teď, ne v minulosti
            return result
        self._maybe_auto_space(now_ms)
        return None

    def finalize_letter(self, now_ms: float) -> DecodeResult:
        """Ruční dokončení písmene (bez signálu → ``MISSING``)."""
        result = self._finalize_current()
        self._last_event_ms = now_ms
        return result

    def word_space(self, now_ms: float) -> DecodeResult:
        """Ruční mezera mezi slovy; nejdřív dokončí rozpracovaný znak.

        Vrací výsledek dokončení znaku (``MISSING``, pokud nebyl žádný
        rozpracovaný). Mezera se přidá vždy po dokončení; prázdná na
        začátku nebo opakovaná mezera → text se nemění.
        """
        result = self._finalize_current()
        self._append_space()
        self._last_event_ms = now_ms
        self._auto_space_added = False
        return result

    def finish_message(self, now_ms: float) -> DecodeResult:
        """Dokončí zprávu: doplní poslední rozpracovaný znak, ořízne koncovou mezeru."""
        result = self._finalize_current()
        if self._tokens and self._tokens[-1] == " ":
            self._tokens.pop()
        self._last_event_ms = now_ms
        return DecodeResult(result.status, result.code, result.char, result.appended, self.text)

    def backspace_symbol(self) -> bool:
        """Smaže poslední signál z rozpracovaného znaku.

        ``False``, pokud rozpracovaný znak není (není co mazat).
        """
        if not self._current:
            return False
        self._current.pop()
        return True

    def backspace_char(self, now_ms: float) -> bool:
        """Smaže poslední dokončený znak (včetně placeholderu ``[kód]``).

        Pokud existuje rozpracovaný znak, nejdřív ho dokončí (aby šlo
        „vrátit" poslední znak přirozeně). ``False``, pokud není co mazat.
        """
        if self._current:
            self._finalize_current()
        if not self._tokens:
            return False
        self._tokens.pop()
        self._last_event_ms = now_ms
        return True

    def reset(self) -> None:
        """Vymaže celý stav (text i rozpracovaný znak)."""
        self._current = []
        self._tokens = []
        self._last_event_ms = None
        self._auto_space_added = False
