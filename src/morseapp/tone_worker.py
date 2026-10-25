"""Generování PCM dat Morseova tónu – čistá úloha bez pygame mixeru.

Tento modul (etapa E2):

- ``generate_tone_block(frequency_hz, ...)`` – vygeneruje blok sinusového
  signálu s **celým počtem period**, aby bylo možné blok plynule opakovat
  bez skoku vlny a bez periodických zeslabovacích ramp v bufferu.
  Náběh a doběh se řeší až při přehrávání v ``AudioCoordinator``.
- ``ToneWorker`` (QRunnable) – spustí generování mimo hlavní GUI vlákno a
  výsledek předá signálem. **Nikdy se nedotkne pygame mixeru** (ten smí
  volat výhradně ``AudioCoordinator``).

Formát výstupu (odpovídá konfiguraci mixeru):

- vzorkovací frekvence ``SAMPLE_RATE = 44100`` Hz,
- mono (1 kanál),
- 16bitové signed PCM (``array('h')``, little-endian).

Skutečná frekvence: počet vzorků na periodu je ``N = round(sample_rate /
frequency_hz)``; blok obsahuje ``cycles`` celých period, tj. ``cycles * N``
vzorků. **Skutečná frekvence je ``sample_rate / N``** a může se od požadované
hodnoty mírně lišit (např. 600 Hz → N = 74 → 595,95 Hz, odchylka < 1 %).
Generovaná frekvence proto není nikdy prezentována jako přesná.

Neplatné parametry (frekvence mimo rozsah, nekladný vzorkovací krok atd.)
vyvolají ``ValueError``; ``ToneWorker`` chybu zachytí a předá signálem
``error``, nikdy ji nenechá nekontrolovaně uniknout.
"""

from __future__ import annotations

import math
from array import array
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

SAMPLE_RATE = 44100        # Hz
CHANNELS = 1               # mono
SAMPLE_WIDTH_BYTES = 2     # 16 bit
DEFAULT_CYCLES = 20        # period v bloku (1 s při 600 Hz by bylo zbytečně moc)

MIN_FREQUENCY_HZ = 20.0      # pod touto hranicí je tón pro ucho těžko užitečný
MAX_FREQUENCY_HZ = 8000.0    # musí zůstat pod Nyquistem (22050 Hz) s rezervou


@dataclass(frozen=True)
class ToneBlock:
    """Vygenerovaný blok PCM dat připravený k vytvoření ``Sound``."""

    samples: array           # array('h'), 16bit signed PCM
    sample_rate: int         # vzorkovací frekvence použitá při generování
    requested_frequency_hz: float
    actual_frequency_hz: float   # sample_rate / samples_per_cycle
    samples_per_cycle: int       # N
    cycles: int                  # počet celých period v bloku

    @property
    def duration_ms(self) -> float:
        return 1000.0 * len(self.samples) / self.sample_rate

    def to_bytes(self) -> bytes:
        """PCM data ve formátu pro ``pygame.mixer.Sound(buffer=...)``."""
        return self.samples.tobytes()


def generate_tone_block(
    frequency_hz: float,
    sample_rate: int = SAMPLE_RATE,
    cycles: int = DEFAULT_CYCLES,
) -> ToneBlock:
    """Vygeneruje sinusový blok s celým počtem period.

    Vyhodí ``ValueError`` při neplatných parametrech:

    - ``frequency_hz`` mimo ``[MIN_FREQUENCY_HZ, MAX_FREQUENCY_HZ]``,
    - ``sample_rate`` není kladné celé číslo,
    - ``cycles`` není kladné celé číslo,
    - ``frequency_hz`` je vyšší než Nyquistova hranice ``sample_rate / 2``.
    """
    if not isinstance(frequency_hz, (int, float)) or isinstance(frequency_hz, bool):
        raise ValueError(f"frequency_hz musí být číslo, dostávám {frequency_hz!r}")
    if not MIN_FREQUENCY_HZ <= frequency_hz <= MAX_FREQUENCY_HZ:
        raise ValueError(
            f"frequency_hz {frequency_hz} mimo povolený rozsah "
            f"{MIN_FREQUENCY_HZ}–{MAX_FREQUENCY_HZ} Hz"
        )
    if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or sample_rate <= 0:
        raise ValueError(f"sample_rate musí být kladné celé číslo, dostávám {sample_rate!r}")
    if frequency_hz >= sample_rate / 2:
        raise ValueError(
            f"frequency_hz {frequency_hz} je nad Nyquistovou hranicí {sample_rate / 2} Hz"
        )
    if not isinstance(cycles, int) or isinstance(cycles, bool) or cycles <= 0:
        raise ValueError(f"cycles musí být kladné celé číslo, dostávám {cycles!r}")

    samples_per_cycle = max(2, round(sample_rate / frequency_hz))
    actual_frequency = sample_rate / samples_per_cycle
    amplitude = 32767.0

    samples = array("h")
    # Fáze pokračuje plynule; blok končí přesně na hranici periody,
    # takže opakování (loops=-1) nezpůsobí skok vlny ani kolísání hlasitosti.
    append = samples.append
    two_pi_over_n = 2.0 * math.pi / samples_per_cycle
    for index in range(samples_per_cycle * cycles):
        append(int(amplitude * math.sin(two_pi_over_n * index)))

    return ToneBlock(
        samples=samples,
        sample_rate=sample_rate,
        requested_frequency_hz=float(frequency_hz),
        actual_frequency_hz=actual_frequency,
        samples_per_cycle=samples_per_cycle,
        cycles=cycles,
    )


class ToneWorkerSignals(QObject):
    """Signály pracovní úlohy generování tónu."""

    finished = pyqtSignal(object)   # ToneBlock
    error = pyqtSignal(str)


class ToneWorker(QRunnable):
    """Asynchronní generování PCM dat tónu.

    Úloha **pouze generuje data** a předá je signálem ``finished(ToneBlock)``.
    Nesmí inicializovat mixer, vytvářet ``Sound``, přehrávat ani ukončovat
    ``pygame.mixer`` – to vše patří výhradně do ``AudioCoordinator``.
    """

    def __init__(
        self,
        frequency_hz: float,
        sample_rate: int = SAMPLE_RATE,
        cycles: int = DEFAULT_CYCLES,
    ) -> None:
        super().__init__()
        self.signals = ToneWorkerSignals()
        self._frequency_hz = frequency_hz
        self._sample_rate = sample_rate
        self._cycles = cycles

    def run(self) -> None:
        """Spuštění úlohy (buď ve vlákně, nebo přímo v testech)."""
        try:
            block = generate_tone_block(
                self._frequency_hz,
                sample_rate=self._sample_rate,
                cycles=self._cycles,
            )
        except Exception as exc:  # nikdy nenecháme výjimku uniknout z úlohy
            self.signals.error.emit(str(exc))
            return
        self.signals.finished.emit(block)
