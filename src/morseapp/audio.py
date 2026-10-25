"""``AudioCoordinator`` – jediný vlastník pygame mixeru (etapa E2).

Koordinátor je **jediným místem v celé aplikaci**, které smí volat
``pygame.mixer``. ``ToneWorker`` generuje jen data; ``Sound``, kanál,
přehrávání, hlasitost, fade-in/fade-out a ``mixer.quit()`` řídí výhradně
tento objekt.

Všechna volání mixeru probíhají v jediném vlákně vlastníka – v hlavním
GUI vlákně. Koordinátor se volá jen z GUI vlákna.

Stavový stroj (E4 doplňuje ``SPEECH``):

    IDLE --start_tone()--> TONE --release_tone()/stop_now()--> IDLE
    IDLE --play_speech()--> SPEECH --dohrání/stop_speech()--> IDLE

Vzájemné vyloučení: zahájení řeči zastaví tón; zahájení tónu zastaví
řeč. Tón a řeč nikdy nehrají současně. Přehrávání řeči využívá
``pygame.mixer.music`` (odděleně od ``Channel`` pro tón) – všechna
volání ale zůstávají **jen uvnitř** tohoto koordinátoru. Konec
přehrávání řeči (``music`` není Qt signál) detekuje ``QTimer``
s ``get_busy()`` a generační číslo – zastaralý callback nikdy nezmění
stav novějšího přehrávání.

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

import io
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

# Kontrola konce přehrávání řeči (pygame.mixer.music není Qt signál).
SPEECH_POLL_MS = 100


class AudioState(Enum):
    """Stav audio enginu."""

    IDLE = auto()    # nic nehraje
    TONE = auto()    # hraje Morseův tón
    SPEECH = auto()  # hraje řeč z gTTS (pygame.mixer.music)


class AudioCoordinator(QObject):
    """Jediný vlastník pygame mixeru; ovládá tón Morseova klíče."""

    # Bezpečné signály pro GUI (bez volání mixeru v obsluze).
    availability_changed = pyqtSignal(bool)   # True = zvuk dostupný
    tone_started = pyqtSignal()
    tone_stopped = pyqtSignal()
    speech_finished = pyqtSignal(int)         # request_id – řeč dohrála
    speech_failed = pyqtSignal(int, str)      # request_id, příčina

    def __init__(
        self,
        mixer=None,
        timer_factory: Callable[[], QTimer] | None = None,
        fade_in_ms: int = DEFAULT_FADE_IN_MS,
        fade_in_steps: int = DEFAULT_FADE_IN_STEPS,
        fade_out_ms: int = DEFAULT_FADE_OUT_MS,
        music=None,
    ) -> None:
        """``mixer``, ``music`` a ``timer_factory`` existují pro testování
        s mocky.

        V produkci se předá ``pygame.mixer`` (výchozí), ``music`` je
        ``pygame.mixer.music`` (dopočítá se) a vytvářejí se skutečné
        ``QTimer``. Testy předají fakes, takže nepotřebují fyzické audio
        zařízení ani Qt event loop.
        """
        super().__init__()
        if fade_in_ms < 0 or fade_out_ms < 0:
            raise ValueError("fade hodnoty nesmí být záporné")
        if fade_in_steps <= 0:
            raise ValueError("fade_in_steps musí být kladné")
        if mixer is None:
            import pygame.mixer as _mixer
            mixer = _mixer
        if music is None:
            # v pygame 2.6 je music dostupné jako atribut mixer.music
            # (interně pygame.mixer_music), ne jako importovatelný modul.
            import pygame.mixer as _mixer_for_music
            music = _mixer_for_music.music
        self._mixer = mixer
        self._music = music
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
        # Řeč: životnost BytesIO musí trvat po dobu přehrávání.
        self._speech_timer: QTimer | None = None
        self._speech_request_id: int | None = None
        self._speech_stream: io.BytesIO | None = None

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
        """Bezpečné ukončení: zastaví tón i řeč a uvolní mixer.

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
        # Vzájemné vyloučení: nový tón zastaví případnou hrající řeč.
        self._halt_speech()
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
        """Okamžité bezpečné zastavení tónu i řeči (bez doběhu)."""
        self._cancel_fade_timer()
        self._generation += 1
        was_playing = self._state is AudioState.TONE
        if self._available and self._channel is not None:
            try:
                self._channel.stop()
            except Exception:
                pass
        self._halt_speech()
        self._state = AudioState.IDLE
        if was_playing:
            self.tone_stopped.emit()

    # ------------------------------------------------------------------
    # Řeč (E4) – pygame.mixer.music výhradně zde
    # ------------------------------------------------------------------

    def play_speech(self, request_id: int, data: bytes, volume: float = 1.0) -> bool:
        """Přehraje kompletní MP3 data z ``SpeechWorker``.

        Nejprve zastaví aktivní tón, pak načte data přes
        ``music.load(io.BytesIO(data), namehint="mp3")`` a spustí
        přehrávání. Přechod do stavu ``SPEECH``; konec hlídá poll
        časovač s ``get_busy()`` a generační číslem.

        Při chybě dekódování/přehrávání emituje ``speech_failed``
        (s ID požadavku), vrátí ``False`` a nic nepředstírá.
        """
        if not self._available:
            self.speech_failed.emit(
                request_id, self._error_message or "Zvuk není dostupný."
            )
            return False
        if not 0.0 <= volume <= 1.0:
            raise ValueError(f"hlasitost musí být v [0, 1], dostávám {volume}")
        if not data:
            self.speech_failed.emit(request_id, "Prázdná MP3 data.")
            return False

        # Vzájemné vyloučení: řeč zastaví případný tón.
        self._cancel_fade_timer()
        self._generation += 1
        generation = self._generation
        tone_was_active = self._state is AudioState.TONE
        if tone_was_active:
            try:
                self._channel.stop()
            except Exception:
                pass
        self._halt_speech()   # předchozí řeč (byť jakákoli) zastavit

        try:
            # Životnost streamu: referenci držíme po dobu přehrávání.
            stream = io.BytesIO(data)
            self._music.load(stream, namehint="mp3")
            self._music.set_volume(volume)
            self._music.play()
        except Exception as exc:
            self._speech_stream = None
            self._state = AudioState.IDLE
            if tone_was_active:
                self.tone_stopped.emit()
            self.speech_failed.emit(request_id, f"Chyba přehrávání řeči: {exc}")
            return False

        self._speech_stream = stream
        self._speech_request_id = request_id
        self._state = AudioState.SPEECH
        if tone_was_active:
            self.tone_stopped.emit()
        self._start_speech_poll(generation)
        return True

    def stop_speech(self) -> None:
        """Okamžitě zastaví právě hrající řeč (bez čekání na generování).

        Tón, který uživatel mezitím stihl spustit, **nezastavuje**
        (stav není ``SPEECH`` → no-op). Žádný signál se neodesílá –
        o zneplatnění požadavku se stará ``MainWindow`` podle ID.
        """
        if self._state is not AudioState.SPEECH:
            return  # tón se při zastavení řeči nesmí rušit
        self._generation += 1           # staré callbacky jsou neplatné
        self._halt_speech()
        self._state = AudioState.IDLE

    def _halt_speech(self) -> None:
        """Zastaví music, ruší poll časovač a uvolní reference.

        NESAHEJ na stav ani na generaci – to řídí volající. Nikdy
        neemituje signály (volá se i při zastavení tónu).
        """
        timer = self._speech_timer
        self._speech_timer = None
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
        try:
            # Bezpečné i když nic nehraje; kanál tónu to neovlivní.
            self._music.stop()
        except Exception:
            pass
        self._speech_stream = None      # BytesIO může skončit
        self._speech_request_id = None

    def _start_speech_poll(self, generation: int) -> None:
        """Spuštění neblokujícího pollingu konce přehrávání."""
        timer = self._timer_factory()
        timer.setSingleShot(False)
        timer.timeout.connect(lambda: self._speech_tick(generation))
        self._speech_timer = timer
        timer.start(SPEECH_POLL_MS)

    def _speech_tick(self, generation: int) -> None:
        """Jedna kontrola ``get_busy()``; zastaralé generace no-op."""
        if generation != self._generation or self._state is not AudioState.SPEECH:
            return  # zastaralý callback nesmí změnit stav novějšího přehrávání
        try:
            busy = bool(self._music.get_busy())
        except Exception:
            busy = False
        if busy:
            if self._speech_timer is not None:
                self._speech_timer.start(SPEECH_POLL_MS)
            return
        # Konce přehrávání: dokončit podle ID tehdy platného požadavku.
        request_id = self._speech_request_id
        self._halt_speech()
        self._state = AudioState.IDLE
        if request_id is not None:
            self.speech_finished.emit(request_id)

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
