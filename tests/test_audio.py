"""Testy zvukového enginu (požadavky č. 1–11 plánu, etapa E2).

Testy fungují **bez fyzického audio zařízení** – používají fake mixer a
fake časovač, takže nepotřebují Qt event loop ani ``pytest-qt``.

Upozornění: jde o testy logiky a volání API, **nikoli o poslechový test**.
Skutečná akustická kvalita (klikání, slyšitelnost fade) se ověřuje ručně.
"""

from __future__ import annotations

import inspect
import pathlib

import pytest

from morseapp.audio import AudioCoordinator, AudioState
from morseapp import audio as audio_module
from morseapp.tone_worker import (
    MAX_FREQUENCY_HZ,
    MIN_FREQUENCY_HZ,
    ToneBlock,
    ToneWorker,
    generate_tone_block,
)

SRC_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "morseapp"


# ---------------------------------------------------------------------------
# Fake mixer a fake časovač
# ---------------------------------------------------------------------------

class FakeChannel:
    def __init__(self, index: int) -> None:
        self.index = index
        self.playing = False
        self.loops = 0
        self.volume = 1.0
        self.fadeout_ms = None
        self.play_calls = 0
        self.stop_calls = 0

    def play(self, sound, loops=0):
        self.play_calls += 1
        self.playing = True
        self.loops = loops
        self.fadeout_ms = None

    def stop(self):
        self.stop_calls += 1
        self.playing = False

    def fadeout(self, ms):
        self.fadeout_ms = ms
        self.playing = False

    def set_volume(self, value):
        self.volume = value


class FakeSound:
    def __init__(self, buffer: bytes) -> None:
        self.buffer = buffer


class FakeMixer:
    """Napodobuje rozhraní pygame.mixer jen s API, které koordinátor používá."""

    def __init__(self, fail_init: bool = False) -> None:
        self.fail_init = fail_init
        self.init_calls = 0
        self.quit_calls = 0
        self.pre_init_args = None
        self.channels = {}

    def pre_init(self, *args):
        self.pre_init_args = args

    def init(self, **kwargs):
        self.init_calls += 1
        if self.fail_init:
            raise RuntimeError("no audio device")

    def Channel(self, index):
        if index not in self.channels:
            self.channels[index] = FakeChannel(index)
        return self.channels[index]

    def Sound(self, buffer=None):
        return FakeSound(buffer)

    def quit(self):
        self.quit_calls += 1


class FakeTimer:
    """Fake QTimer – start() jen uloží interval, testy volají tick() ručně."""

    class _Timeout:
        def __init__(self) -> None:
            self._callbacks = []

        def connect(self, callback):
            self._callbacks.append(callback)

    def __init__(self) -> None:
        self.interval = None
        self.active = False
        self.single_shot = False
        self.timeout = FakeTimer._Timeout()

    def setSingleShot(self, value):
        self.single_shot = value

    def start(self, interval):
        self.interval = interval
        self.active = True

    def stop(self):
        self.active = False

    def tick(self):
        """Simulace timeoutu časovače."""
        self.active = False
        for callback in self.timeout._callbacks:
            callback()


def make_coordinator(**kwargs) -> tuple[AudioCoordinator, FakeMixer]:
    mixer = FakeMixer()
    timers: list[FakeTimer] = []

    def timer_factory():
        timer = FakeTimer()
        timers.append(timer)
        return timer

    coordinator = AudioCoordinator(mixer=mixer, timer_factory=timer_factory, **kwargs)
    coordinator._test_timers = timers  # přístup pro testy
    return coordinator, mixer


def ready_coordinator() -> tuple[AudioCoordinator, FakeMixer, ToneBlock]:
    coordinator, mixer = make_coordinator()
    assert coordinator.initialize() is True
    block = generate_tone_block(600, cycles=5)
    assert coordinator.prepare_tone(block) is True
    return coordinator, mixer, block


# ---------------------------------------------------------------------------
# 1–4. Generování sinusového signálu
# ---------------------------------------------------------------------------

def test_generate_produces_non_empty_16bit_mono_pcm():
    block = generate_tone_block(600)
    assert isinstance(block, ToneBlock)
    assert len(block.samples) > 0
    assert block.samples.itemsize == 2          # 16 bit
    assert block.sample_rate == 44100
    assert len(block.samples) == block.samples_per_cycle * block.cycles


def test_block_contains_whole_cycles_and_loops_seamlessly():
    block = generate_tone_block(600, cycles=20)
    assert len(block.samples) == block.samples_per_cycle * 20

    # Skok v opakovacím bodě (poslední → první vzorek) musí být stejně
    # malý jako běžný krok sousedních vzorků uvnitř signálu.
    samples = list(block.samples)
    interior_steps = [abs(samples[i + 1] - samples[i]) for i in range(len(samples) - 1)]
    max_interior_step = max(interior_steps)
    loop_step = abs(samples[0] - samples[-1])
    # Tolerance: sinus 600 Hz má největší krok ~2760; skok přes nulu
    # u konce periody by byl řádově větší (dvojnásobná amplituda).
    assert loop_step <= max_interior_step * 1.5
    assert loop_step < 7000


def test_effective_frequency_is_sample_rate_over_n():
    block = generate_tone_block(600)
    assert block.samples_per_cycle == round(44100 / 600)      # 74
    assert block.actual_frequency_hz == pytest.approx(44100 / 74)  # 595.95
    # Skutečná frekvence se mírně liší od požadované – dokumentované chování.
    assert block.actual_frequency_hz != 600
    assert abs(block.actual_frequency_hz - 600) < 5


def test_buffer_round_trip_bytes():
    block = generate_tone_block(700, cycles=3)
    data = block.to_bytes()
    assert isinstance(data, bytes)
    assert len(data) == len(block.samples) * 2
    assert data != b"\x00" * len(data)   # není prázdný signál


@pytest.mark.parametrize("bad_freq", [0, -100, MIN_FREQUENCY_HZ - 1,
                                      MAX_FREQUENCY_HZ + 1, 30000, "600", None, True])
def test_invalid_frequency_rejected(bad_freq):
    with pytest.raises(ValueError):
        generate_tone_block(bad_freq)


@pytest.mark.parametrize("bad_rate", [0, -44100, 44100.5, "44100", None])
def test_invalid_sample_rate_rejected(bad_rate):
    with pytest.raises(ValueError):
        generate_tone_block(600, sample_rate=bad_rate)


@pytest.mark.parametrize("bad_cycles", [0, -5, 2.5, "20", None])
def test_invalid_cycles_rejected(bad_cycles):
    with pytest.raises(ValueError):
        generate_tone_block(600, cycles=bad_cycles)


def test_frequency_above_nyquist_rejected():
    with pytest.raises(ValueError):
        generate_tone_block(600, sample_rate=1000)   # Nyquist = 500


# ---------------------------------------------------------------------------
# 5–7. Spuštění, uvolnění, časovače
# ---------------------------------------------------------------------------

def test_start_tone_plays_on_dedicated_channel_with_loop():
    coordinator, mixer, _ = ready_coordinator()
    assert coordinator.start_tone() is True
    channel = mixer.channels[0]
    assert channel.playing is True
    assert channel.loops == -1
    assert channel.play_calls == 1
    assert coordinator.state is AudioState.TONE


def test_fade_in_ramps_volume_to_target():
    coordinator, _, _ = ready_coordinator()
    coordinator.start_tone(volume=0.8)
    timers = coordinator._test_timers
    fade_timer = timers[-1]
    channel = coordinator._channel

    volumes = []
    while fade_timer.active:
        volumes.append(channel.volume)
        fade_timer.tick()
    # Hlasitost roustě a končí na cílové hodnotě.
    assert volumes == sorted(volumes)
    assert volumes[0] == 0.0
    assert channel.volume == pytest.approx(0.8)
    # Náběh je krátký: 5 kroků po 5 ms = 25 ms (v rozsahu 20–30 ms).
    assert coordinator._fade_in_ms == 25
    assert fade_timer.interval == 5


def test_release_tone_uses_fadeout_and_stops():
    coordinator, mixer, _ = ready_coordinator()
    coordinator.start_tone()
    channel = mixer.channels[0]
    coordinator.release_tone()
    assert channel.fadeout_ms == 20               # doběh ~15–30 ms
    assert channel.playing is False
    assert coordinator.state is AudioState.IDLE


def test_release_without_tone_is_safe_noop():
    coordinator, _, _ = ready_coordinator()
    coordinator.release_tone()                    # nic nehraje
    assert coordinator.state is AudioState.IDLE


def test_stale_timer_cannot_stop_new_tone():
    # Rychlá posloupnost: stisk → uvolnění → stisk. Časovač prvního
    # náběhu nesmí zasáhnout do druhého přehrávání.
    coordinator, _, _ = ready_coordinator()
    coordinator.start_tone()
    first_timer = coordinator._test_timers[-1]

    coordinator.release_tone()
    coordinator.start_tone()                      # nové přehrávání
    second_timer = coordinator._test_timers[-1]
    channel = coordinator._channel

    assert first_timer is not second_timer
    first_timer.tick()                            # zastaralý časovač
    # Nový tón stále hraje a jeho hlasitost se řídí až jeho vlastním časovačem.
    assert channel.playing is True
    assert coordinator.state is AudioState.TONE
    # Nový časovač ještě nedokončil náběh → hlasitost zůstává nízká.
    assert channel.volume <= 0.8


def test_start_during_fadeout_returns_to_active_state():
    coordinator, mixer, _ = ready_coordinator()
    coordinator.start_tone()
    coordinator.release_tone()                    # začal doběh
    assert mixer.channels[0].fadeout_ms == 20
    assert coordinator.start_tone() is True       # nový stisk během doběhu
    channel = mixer.channels[0]
    assert channel.playing is True
    assert channel.play_calls == 2                # přehrání od začátku
    assert coordinator.state is AudioState.TONE


def test_stop_now_is_immediate():
    coordinator, mixer, _ = ready_coordinator()
    coordinator.start_tone()
    coordinator.stop_now()
    channel = mixer.channels[0]
    assert channel.playing is False
    assert channel.fadeout_ms is None             # žádný doběh, okamžité stop
    assert coordinator.state is AudioState.IDLE


def test_invalid_volume_rejected():
    coordinator, _, _ = ready_coordinator()
    with pytest.raises(ValueError):
        coordinator.start_tone(volume=1.5)
    with pytest.raises(ValueError):
        coordinator.start_tone(volume=-0.1)


def test_start_without_prepared_sound_is_false():
    coordinator, _ = make_coordinator()
    coordinator.initialize()
    assert coordinator.start_tone() is False
    assert coordinator.state is AudioState.IDLE


# ---------------------------------------------------------------------------
# 8–9. Selhání inicializace a bezpečné ukončení
# ---------------------------------------------------------------------------

def test_init_failure_does_not_crash_and_reports():
    mixer = FakeMixer(fail_init=True)
    coordinator = AudioCoordinator(mixer=mixer, timer_factory=FakeTimer)

    assert coordinator.initialize() is False      # nespadne
    assert coordinator.is_available is False
    assert coordinator.error_message is not None
    assert "není dostupné" in coordinator.error_message
    # Nepředstírá úspěch:
    assert coordinator.start_tone() is False
    assert coordinator.prepare_tone(generate_tone_block(600, cycles=2)) is False
    assert coordinator.state is AudioState.IDLE


def test_availability_signal_emitted_on_failure():
    mixer = FakeMixer(fail_init=True)
    coordinator = AudioCoordinator(mixer=mixer, timer_factory=FakeTimer)
    seen = []
    coordinator.availability_changed.connect(seen.append)
    coordinator.initialize()
    assert seen == [False]


def test_shutdown_stops_tone_and_quits_mixer():
    coordinator, mixer, _ = ready_coordinator()
    coordinator.start_tone()
    coordinator.shutdown()
    channel = mixer.channels[0]
    assert channel.playing is False
    assert mixer.quit_calls == 1
    assert coordinator.is_available is False
    assert coordinator.state is AudioState.IDLE
    # Po ukončení už nelze hrát:
    assert coordinator.start_tone() is False


def test_shutdown_without_init_is_safe():
    coordinator, mixer = make_coordinator()
    coordinator.shutdown()                         # nic neinicializováno – nesmí spadnout
    assert mixer.quit_calls == 0                   # quit jen pokud se inicializovalo


def test_double_initialize_is_idempotent():
    coordinator, mixer = make_coordinator()
    assert coordinator.initialize() is True
    assert coordinator.initialize() is True
    assert mixer.init_calls == 1


# ---------------------------------------------------------------------------
# 10–11. Jedinný vlastník mixeru; ToneWorker mixer nepoužívá
# ---------------------------------------------------------------------------

def _pygame_imports(path: pathlib.Path) -> bool:
    """Přes AST zjistí, zda soubor importuje pygame (bez shody v docstringech)."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.startswith("pygame") for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("pygame"):
                return True
    return False


def test_only_audio_module_imports_pygame():
    """pygame.mixer smí volat výhradně audio.py (jediný vlastník)."""
    importers = {path.name for path in SRC_DIR.glob("*.py") if _pygame_imports(path)}
    assert importers == {"audio.py"}, (
        f"pygame importuje {importers}, povoleno je jen audio.py"
    )


def test_tone_worker_never_touches_pygame():
    import ast

    source = pathlib.Path(inspect.getfile(ToneWorker)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    # Worker nesmí importovat pygame ani mixer – jen generuje data.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.startswith("pygame") for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert not (node.module and node.module.startswith("pygame"))
    # Worker generuje data a předá je signálem:
    worker = ToneWorker(600, cycles=3)
    received = []
    worker.signals.finished.connect(received.append)
    errors = []
    worker.signals.error.connect(errors.append)
    worker.run()                                   # přímo, deterministicky
    assert errors == []
    assert len(received) == 1
    assert isinstance(received[0], ToneBlock)


def test_tone_worker_reports_error_without_crash():
    worker = ToneWorker(0)                         # neplatná frekvence
    received = []
    worker.signals.finished.connect(received.append)
    errors = []
    worker.signals.error.connect(errors.append)
    worker.run()                                   # nesmí spadnout
    assert received == []
    assert len(errors) == 1


def test_coordinator_only_audio_module_owns_channel():
    """Koordinátor pracuje s vyhrazeným kanálem 0."""
    coordinator, mixer, _ = ready_coordinator()
    coordinator.start_tone()
    assert 0 in mixer.channels
    assert mixer.channels[0].index == 0
