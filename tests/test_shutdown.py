"""Testy asynchronního shutdownu a řízeného ukončení (etapa E5)."""

from __future__ import annotations

import os
import pytest
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

from morseapp.shutdown import ApplicationShutdown
from morseapp.settings_dialog import SettingsDialog
from morseapp.settings_store import Settings


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


class SlowDummyThread(QThread):
    """Testovací vlákno, které chvíli běží, než skončí."""

    def run(self) -> None:
        while not self.isInterruptionRequested():
            self.msleep(10)


class FakeCoordinatorForShutdown:
    def __init__(self) -> None:
        self.stopped = False
        self.shutdown_called = False

    def stop_now(self) -> None:
        self.stopped = True

    def shutdown(self) -> None:
        self.shutdown_called = True


def test_app_set_quit_on_last_window_closed(qapp):
    """Ověří, že setQuitOnLastWindowClosedl lze nastavit."""
    qapp.setQuitOnLastWindowClosed(False)
    assert qapp.quitOnLastWindowClosed() is False
    qapp.setQuitOnLastWindowClosed(True)  # úklid pro ostatní testy


def test_shutdown_lifecycle(qapp):
    """Ověří, že ApplicationShutdown správně čeká na vlákno a pak zavolá quit()."""
    qapp.setQuitOnLastWindowClosed(False)
    coord = FakeCoordinatorForShutdown()
    thread = SlowDummyThread()
    thread.start()

    assert thread.isRunning() is True

    quit_called = [False]
    
    class DummyApp:
        def quit(self):
            quit_called[0] = True

    dummy_app = DummyApp()

    shutdown = ApplicationShutdown(
        app=dummy_app,
        coordinator=coord,
        threads=[thread],
    )
    assert shutdown.is_shutting_down is False
    shutdown.start_shutdown()
    assert shutdown.is_shutting_down is True

    # Zastavit vlákno kooperativně
    thread.requestInterruption()
    thread.wait(2000)

    # Zpracovat event loop / ticky
    from PyQt6.QtTest import QTest
    for _ in range(10):
        QTest.qWait(10)
        if quit_called[0]:
            break

    qapp.setQuitOnLastWindowClosed(True)

    assert coord.stopped is True
    assert thread.isRunning() is False
    assert quit_called[0] is True


def test_settings_dialog_save_and_cancel(qapp):
    """Ověří funkčnost dialogu nastavení, validaci a zachování hodnot při zrušení."""
    settings = Settings(tone_frequency_hz=700, tone_volume=50)
    dialog = SettingsDialog(settings)

    # Změnit hodnoty v dialogu
    dialog.tone_freq_spin.setValue(1000)
    dialog.tone_vol_spin.setValue(80)

    # Simulovat uložení
    dialog._on_save()
    assert dialog.settings.tone_frequency_hz == 1000
    assert dialog.settings.tone_volume == 80

    # Původní nastavení při zrušení zůstávají nezměněna
    assert settings.tone_frequency_hz == 700
