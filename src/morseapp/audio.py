"""``AudioCoordinator`` – jediný vlastník pygame mixeru (etapa E2).

Koordinátor je **jediným místem v celé aplikaci**, které smí volat
``pygame.mixer``. ``ToneWorker`` generuje jen data; ``Sound``, kanál,
přehrávání, hlasitost, fade-in/fade-out a ``mixer.quit()`` řídí výhradně
tento objekt.

Všechna volání mixeru probíhají v jediném vlákně vlastníka – v hlavním
GUI vlákně. Koordinátor se volá jen z GUI vlákna.

Stavový stroj (E2 implementuje ``IDLE`` a ``TONE``; ``SPEECH`` je
vyhrazen pro E4, architektura ho bezpečně doplní):

    IDLE --start_tone()--> TONE --release_tone()/stop_now()--> IDLE

Řešení rychlých posloupností (stisk–uvolnění–stisk): každé spuštění nebo
zastavení tónu zvýší ``generation``; časovače náležející starší generaci
se při spuštění zruší a jejich callback se při prověření generace stane
no-opem. Zrušený nebo opožděný časovač tedy **nikdy nezastaví nově
spuštěný tón**.

Náběh (fade-in) při stisku: krátký, přibližně 20–30 ms (5 kroků po 5 ms),
neblokující – řízen QTimerem. Doběh (fade-out) při uvolnění: přibližně
15–30 ms přes ``Channel.fadeout`` (lineární doběh řídí SDL).

Selhání inicializace (žádné audio zařízení): koordinátor nespadne,
nepředstírá úspěch; ``is_available`` je ``False``, ``error_message``
popisuje příčinu a všechny operace tónu jsou bezpečné no-op s návratem
``False``.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .tone_worker import ToneBlock

# Výchozí parametry náběhu a doběhu (laditelné; nesmějí blokovat GUI).
DEFAULT_FADE_IN_MS = 25      # ~20–30 ms
DEFAULT_FADE_IN_STEPS = 5
DEFAULT_FADE_OUT_MS = 20     # ~15–30 ms

# Index vyhrazeného kanálu pro Morseův tón.
TONE_CHANNEL = 0


class AudioState(Enum):
    """Stav audio enginu."""

    IDLE = auto()    # nic nehraje
    TONE = auto()    # hraje Morseův tón
    SPEECH = auto()  # vyhrazeno pro E4 (řeč); v E2 se nepoužívá


class AudioCoordinator(QObject):
    """Jediný vlastník pygame mixeru; ovládá tón Morseova klíče."""

    # Bezpečné signály pro GUI (bez volání mixeru v obsluze).
    availability_changed = pyqtSignal(bool)   # True = zvuk dostupný
    tone_started = pyqtSignal()
    tone_stopped = pyqtSignal()

    def __init__(
        self,
        mixer=None,
        timer_factory: Callable[[], QTimer] | None = None,
        fade_in_ms: int = DEFAULT_FADE_IN_MS,
        fade_in_steps: int = DEFAULT_FADE_IN_STEPS,
        fade_out_ms: int = DEFAULT_FADE_OUT_MS,
    ) -> None:
        """``mixer`` a ``timer_factory`` existují pro testování s mocky.

        V produkci se předá ``pygame.mixer`` (výchozí) a vytvářejí se
        skutečné ``QTimer``. Testy předají fake mixer a fake časovač,
        takže nepotřebují fyzické audio zařízení ani Qt event loop.
        """
        super().__init__()
        if fade_in_ms < 0 or fade_out_ms < 0:
            raise ValueError("fade hodnoty nesmí být záporné")
        if fade_in_steps <= 0:
            raise ValueError("fade_in_steps musí být kladné")
        if mixer is None:
            import pygame.mixer as _mixer
            mixer = _mixer
        self._mixer = mixer
        self._timer_factory = timer_factory or QTimer
        self._fade_in_ms = int(fade_in_ms)
        self._fade_in_steps = int(fade_in_steps)
        self._fade_out_ms = int(fade_out_ms)

        self._state = AudioState.IDLE
        self._available = False
        self._error_message: str | None = None
        self._initialized = False
        self._channel = None
        self._sound = None
        self._target_volume = 1.0
        self._generation = 0          # ochrana před zastaralými časovači
        self._fade_timer: QTimer | None = None
        self._fade_step = 0

    # ------------------------------------------------------------------
    # Stav
    # ------------------------------------------------------------------

    @property
    def state(self) -> AudioState:
        return self._state

    @property
    def is_available(self) -> bool:
        """``True``, pokud je mixer inicializovaný a připravený hrát."""
        return self._available

    @property
    def error_message(self) -> str | None:
        """Popis chyby inicializace; ``None``, pokud žádná nenastala."""
        return self._error_message

    # ------------------------------------------------------------------
    # Inicializace a ukončení
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Zkusí inicializovat mixer; nikdy nespadne.

        Vrací ``True`` jen při skutečném úspěchu. Při selhání je
        ``is_available`` ``False`` a ``error_message`` obsahuje příčinu.
        """
        if self._initialized:
            return self._available
        try:
            # Odpovídá konfiguraci generátoru: 44100 Hz, 16bit signed, mono.
            self._mixer.pre_init(44100, -16, 1, 512)
            self._mixer.init()
            self._channel = self._mixer.Channel(TONE_CHANNEL)
        except Exception as exc:  # např. žádné audio zařízení
            self._available = False
            self._error_message = f"Zvukové zařízení není dostupné: {exc}"
            self._initialized = True
            self.availability_changed.emit(False)
            return False
        self._available = True
        self._error_message = None
        self._initialized = True
        self.availability_changed.emit(True)
        return True

    def shutdown(self) -> None:
        """Bezpečné ukončení: zastaví tón a uvolní mixer.

        Volá se z GUI vlákna při zavírání aplikace (až po skutečném
        dokončení pracovních vláken – viz ``shutdown.py`` v E5).
        """
        self.stop_now()
        if not self._initialized:
            return
        self._initialized = False
        self._available = False
        try:
            self._mixer.quit()
        except Exception:
            pass  # ukončení nesmí nikdy spadnout

    # ------------------------------------------------------------------
    # Příprava tónu
    # ------------------------------------------------------------------

    def prepare_tone(self, block: ToneBlock) -> bool:
        """Vytvoří ``Sound`` z vygenerovaných PCM dat (v GUI vlákně).

        Volá se po obdržení ``ToneBlock`` z ``ToneWorker``. Při
        nedostupném zvuku vrací ``False`` a nic nepředstírá.
        """
        if not self._available:
            return False
        try:
            self._sound = self._mixer.Sound(buffer=block.to_bytes())
        except Exception as exc:
            self._available = False
            self._error_message = f"Chyba při vytváření zvuku: {exc}"
            self.availability_changed.emit(False)
            return False
        return True

    # ------------------------------------------------------------------
    # Ovládání tónu
    # ------------------------------------------------------------------

    def start_tone(self, volume: float = 1.0) -> bool:
        """Spustí připravený tón (náběh ~20–30 ms).

        Bezpečné při rychlém opakování: ruší časovače starší generace.
        Vrací ``False``, pokud zvuk není dostupný nebo není připraven
        žádný ``Sound``.
        """
        if not self._available or self._sound is None:
            return False
        if not 0.0 <= volume <= 1.0:
            raise ValueError(f"hlasitost musí být v [0, 1], dostávám {volume}")
        self._cancel_fade_timer()
        self._generation += 1
        generation = self._generation
        self._target_volume = volume
        try:
            self._channel.stop()        # případný doběh starší generace
            self._channel.play(self._sound, loops=-1)
        except Exception as exc:
            self._available = False
            self._error_message = f"Chyba při spouštění tónu: {exc}"
            self.availability_changed.emit(False)
            return False
        self._state = AudioState.TONE
        self._begin_fade_in(generation)
        self.tone_started.emit()
        return True

    def release_tone(self) -> None:
        """Uvolnění klíče: krátký doběh a zastavení tónu."""
        if self._state is not AudioState.TONE:
            return
        self._cancel_fade_timer()
        self._generation += 1           # staré časovače jsou teď neplatné
        try:
            self._channel.fadeout(self._fade_out_ms)
        except Exception:
            try:
                self._channel.stop()
            except Exception:
                pass
        self._state = AudioState.IDLE
        self.tone_stopped.emit()

    def stop_now(self) -> None:
        """Okamžité bezpečné zastavení tónu (bez doběhu)."""
        self._cancel_fade_timer()
        self._generation += 1
        was_playing = self._state is AudioState.TONE
        if self._available and self._channel is not None:
            try:
                self._channel.stop()
            except Exception:
                pass
        self._state = AudioState.IDLE
        if was_playing:
            self.tone_stopped.emit()

    # ------------------------------------------------------------------
    # Náběh (fade-in)
    # ------------------------------------------------------------------

    def _begin_fade_in(self, generation: int) -> None:
        """Lineární náběh hlasitosti; neblokující, řízený časovačem."""
        interval = max(1, self._fade_in_ms // self._fade_in_steps)
        self._fade_step = 0
        timer = self._timer_factory()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._fade_tick(generation))
        self._fade_timer = timer
        try:
            self._channel.set_volume(0.0)
        except Exception:
            pass
        timer.start(interval)

    def _fade_tick(self, generation: int) -> None:
        """Jeden krok náběhu; starší generace se ignoruje."""
        if generation != self._generation or self._state is not AudioState.TONE:
            return  # zastaralý časovač nesmí zasáhnout do nového přehrávání
        self._fade_step += 1
        fraction = min(1.0, self._fade_step / self._fade_in_steps)
        try:
            self._channel.set_volume(self._target_volume * fraction)
        except Exception:
            return
        if fraction >= 1.0:
            self._cancel_fade_timer()
            return
        if self._fade_timer is not None:
            self._fade_timer.start(max(1, self._fade_in_ms // self._fade_in_steps))

    def _cancel_fade_timer(self) -> None:
        timer = self._fade_timer
        self._fade_timer = None
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
