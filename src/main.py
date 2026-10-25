"""Spouštěcí bod Přístupného Morseova přepisovače (etapa E5).

Nastavuje:
- QApplication s `setQuitOnLastWindowClosed(False)` pro asynchronní shutdown;
- organizaci a aplikaci pro QSettings;
- globální app stylesheet;
- inicializaci `MainWindow` a spuštění event loopu.
"""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from morseapp.main_window import MainWindow
from morseapp.settings_store import SettingsStore
from morseapp.style_sheet import APP_STYLESHEET


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Klíčové pro asynchronní shutdown v E5
    app.setStyleSheet(APP_STYLESHEET)

    store = SettingsStore()
    settings = store.load()

    window = MainWindow(settings=settings)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
