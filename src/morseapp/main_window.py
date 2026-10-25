"""Hlavní okno přístupného Morseova přepisovače (PyQt6, etapa E3).

Propojuje:

- ``Decoder`` – dekódovací logika; čas mu předává ``QTimer``
  (``_letter_timer``) voláním ``tick(now_ms)``; žádné ``sleep()``;
- ``ToneWorker`` – generování PCM mimo GUI vlákno (``QThreadPool``);
- ``AudioCoordinator`` – jediný vlastník pygame mixeru;
- ``Announcer`` – přístupná oznámení (průběžné oznamování písmen
  standardně **vypnuto**).

Rozhraní: Morseův klíč, přímé tlačítko tečky/čárky, dokončit písmeno,
mezera, vrátit signál, vrátit znak, dokončit zprávu, pole výsledného
textu (QTextEdit pouze pro čtení, procházetelné a kopírovatelné) a
textový stavový řádek. Žádný důležitý stav není jen barevně ani jen
zvukem – vše je textově ve stavovém řádku.

Zvuk: při startu se inicializuje koordinátor a spustí se příprava
výchozího tónu. Pokud tón ještě není připravený nebo zvuk není
dostupný, je klíč **dočasně zakázán** a důvod je zobrazen ve stavu
i oznámen – stisk se netichu ignoruje.

V E3 nejsou tlačítka hlasového čtení (gTTS přijde v E4) ani dialog
nastavení (E5).
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QEvent, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QTextCursor
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .announce import Announcer
from .audio import AudioCoordinator
from .decoder import DASH_SYMBOL, DOT_SYMBOL, DecodeStatus, Decoder
from .settings_store import Settings
from .style_sheet import APP_STYLESHEET
from .tone_worker import ToneBlock, ToneWorker
from .widgets.key_button import KeyButton

# Bezpečná (neběžná) záloha frekvence, pokud se nastavení načíst nepovede.
DEFAULT_FREQUENCY_HZ = 600


class MainWindow(QMainWindow):
    """Hlavní okno aplikace."""

    # Pro testy: signal po úspěšné přípravě tónu.
    tone_ready = pyqtSignal()

    def __init__(
        self,
        settings: Settings | None = None,
        coordinator: AudioCoordinator | None = None,
        announcer: Announcer | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings if settings is not None else Settings()
        self._announcer = announcer if announcer is not None else Announcer()
        # Průběžné oznamování písmen standardně vypnuto.
        self._announcer.char_announcements_enabled = self._settings.continuous_announce

        self._coordinator = (
            coordinator if coordinator is not None else AudioCoordinator()
        )
        self._decoder = Decoder(
            letter_gap_ms=self._settings.letter_gap_ms,
            auto_word_space=self._settings.auto_word_space,
            auto_word_gap_ms=self._settings.auto_word_gap_ms,
        )

        self._pool = QThreadPool.globalInstance()
        self._tone_ready_flag = False
        self._stopping = False
        self._status_parts: dict[str, str] = {}

        self._build_ui()
        self._connect_signals()
        self._start_audio_preparation()

    # ------------------------------------------------------------------
    # Vytvoření rozhraní
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("Přístupný Morseův přepisovač")
        self.setStyleSheet(APP_STYLESHEET)

        central = QWidget(self)
        layout = QVBoxLayout(central)

        # 1) Morseův klíč
        self.key_button = KeyButton(settings_provider=lambda: self._settings)
        self.key_button.setMinimumHeight(80)
        self.key_button.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.key_button)

        # 2–3) Přímé vložení tečky a čárky
        self.dot_button = QPushButton("Vložit tečku")
        self.dot_button.setAccessibleDescription(
            "Vloží tečku bez měření délky stisku."
        )
        self.dash_button = QPushButton("Vložit čárku")
        self.dash_button.setAccessibleDescription(
            "Vloží čárku bez měření délky stisku."
        )
        layout.addWidget(self.dot_button)
        layout.addWidget(self.dash_button)

        # 4) Dokončit písmeno
        self.finish_letter_button = QPushButton("Dokončit písmeno")
        self.finish_letter_button.setAccessibleDescription(
            "Ručně ukončí aktuální rozpracovaný Morseův znak."
        )
        layout.addWidget(self.finish_letter_button)

        # 5) Mezera
        self.space_button = QPushButton("Vložit mezeru")
        self.space_button.setAccessibleDescription(
            "Vloží mezeru mezi slova; nejdřív dokončí rozpracovaný znak."
        )
        layout.addWidget(self.space_button)

        # 6–7) Vracení
        self.back_symbol_button = QPushButton("Vrátit poslední signál")
        self.back_symbol_button.setAccessibleDescription(
            "Odstraní poslední tečku nebo čárku z rozpracovaného znaku."
        )
        layout.addWidget(self.back_symbol_button)

        self.back_char_button = QPushButton("Vrátit poslední znak")
        self.back_char_button.setAccessibleDescription(
            "Odstraní poslední dokončený znak včetně placeholderu neznámého kódu."
        )
        layout.addWidget(self.back_char_button)

        # 8) Dokončit zprávu
        self.finish_message_button = QPushButton("Dokončit zprávu")
        self.finish_message_button.setAccessibleDescription(
            "Zpracuje poslední rozpracovaný znak a ukončí zprávu."
        )
        layout.addWidget(self.finish_message_button)

        # 9) Pole výsledného textu (pro čtení, procházetelné klávesnicí)
        text_label = QLabel("Výsledný text:")
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setAccessibleName("Výsledný text")
        self.text_edit.setAccessibleDescription(
            "Dekódovaná zpráva. Pole je pouze pro čtení, text lze "
            "procházet šipkami a kopírovat."
        )
        text_label.setBuddy(self.text_edit)
        layout.addWidget(text_label)
        layout.addWidget(self.text_edit)

        # 10) Stavový řádek (textový, odečitatelný)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleName("Stav aplikace")
        self.status_label.setAccessibleDescription(
            "Textový stav: rozpracovaný kód, dostupnost zvuku a chyby."
        )
        layout.addWidget(self.status_label)

        self.setCentralWidget(central)

        # Explicitní pořadí Tab (jen existující prvky E3).
        order = [
            self.key_button,
            self.dot_button,
            self.dash_button,
            self.finish_letter_button,
            self.space_button,
            self.back_symbol_button,
            self.back_char_button,
            self.finish_message_button,
            self.text_edit,
        ]
        for first, second in zip(order, order[1:]):
            self.setTabOrder(first, second)

        # Časovač pro automatické dokončení písmene – jen předává čas.
        self._letter_timer = QTimer(self)
        self._letter_timer.setSingleShot(True)
        self._letter_timer.setInterval(int(self._settings.letter_gap_ms))
        self._letter_timer.timeout.connect(self._on_letter_timeout)

        self._update_status()

    # ------------------------------------------------------------------
    # Signály
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.key_button.tone_start.connect(self._on_tone_start)
        self.key_button.tone_end.connect(self._on_tone_end)
        self.key_button.symbol_entered.connect(self._on_symbol)

        self.dot_button.clicked.connect(lambda: self._on_symbol(DOT_SYMBOL))
        self.dash_button.clicked.connect(lambda: self._on_symbol(DASH_SYMBOL))
        self.finish_letter_button.clicked.connect(self._on_finish_letter)
        self.space_button.clicked.connect(self._on_word_space)
        self.back_symbol_button.clicked.connect(self._on_back_symbol)
        self.back_char_button.clicked.connect(self._on_back_char)
        self.finish_message_button.clicked.connect(self._on_finish_message)

    # ------------------------------------------------------------------
    # Zvuk
    # ------------------------------------------------------------------

    def _start_audio_preparation(self) -> None:
        """Inicializuje koordinátor a nechá vygenerovat výchozí tón.

        Dokud tón není připraven, je klíč zakázán (žádné tiché
        ignorování stisku).
        """
        self.key_button.setEnabled(False)
        if not self._coordinator.initialize():
            self._audio_unavailable(self._coordinator.error_message)
            return
        self._request_tone_block(self._settings.tone_frequency_hz)

    def _request_tone_block(self, frequency_hz: float) -> None:
        worker = ToneWorker(frequency_hz)
        worker.signals.finished.connect(self._on_tone_block_ready)
        worker.signals.error.connect(self._on_tone_error)
        self._pool.start(worker)

    def _on_tone_block_ready(self, block: ToneBlock) -> None:
        if self._stopping:
            return
        if not self._coordinator.prepare_tone(block):
            self._audio_unavailable(self._coordinator.error_message)
            return
        self._tone_ready_flag = True
        self.key_button.setEnabled(True)
        self._update_status()
        self.tone_ready.emit()

    def _on_tone_error(self, message: str) -> None:
        self._audio_unavailable(f"Chyba generování tónu: {message}")

    def _audio_unavailable(self, message: str | None) -> None:
        self._tone_ready_flag = False
        self.key_button.setEnabled(False)
        text = message or "Zvuk není dostupný."
        self._set_status_part("zvuk", f"Zvuk nedostupný: {text}")
        self._announcer.say(f"Chyba zvuku: {text}", force=True)
        self._update_status()

    def _on_tone_start(self) -> None:
        if not self._tone_ready_flag:
            self.key_button.cancel_press()
            self._announcer.say("Tón ještě není připraven.", force=True)
            self._update_status()
            return
        self._coordinator.start_tone(
            volume=self._settings.tone_volume / 100.0
        )

    def _on_tone_end(self) -> None:
        self._coordinator.release_tone()

    # ------------------------------------------------------------------
    # Dekodér
    # ------------------------------------------------------------------

    @staticmethod
    def _now_ms() -> float:
        return time.monotonic() * 1000.0

    def _on_symbol(self, symbol: str) -> None:
        result = self._decoder.on_symbol(symbol, self._now_ms())
        if result is not None:
            self._apply_result(result)
        self._letter_timer.start()
        self._update_status()

    def _on_letter_timeout(self) -> None:
        """Callback časovače – jen předá čas dekodéru."""
        result = self._decoder.tick(self._now_ms())
        if result is not None:
            self._apply_result(result)
        self._update_status()

    def _on_finish_letter(self) -> None:
        self._letter_timer.stop()
        result = self._decoder.finalize_letter(self._now_ms())
        self._apply_result(result)
        self._update_status()

    def _on_word_space(self) -> None:
        self._letter_timer.stop()
        result = self._decoder.word_space(self._now_ms())
        self._apply_result(result)
        self._update_status()

    def _on_back_symbol(self) -> None:
        if not self._decoder.backspace_symbol():
            self._announcer.say("Není co vrátit.")
        self._refresh_text()
        self._update_status()

    def _on_back_char(self) -> None:
        if not self._decoder.backspace_char(self._now_ms()):
            self._announcer.say("Není co vrátit.")
        self._refresh_text()
        self._update_status()

    def _refresh_text(self) -> None:
        self.text_edit.setPlainText(self._decoder.text)
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def _on_finish_message(self) -> None:
        self._letter_timer.stop()
        result = self._decoder.finish_message(self._now_ms())
        self._apply_result(result)
        self._update_status()
        self._announcer.say("Zpráva dokončena.")

    def _apply_result(self, result) -> None:
        """Aktualizuje text a volitelně oznámí dokončené písmeno."""
        self._refresh_text()
        if result.status is DecodeStatus.OK and result.char:
            # Podmíněné oznamování – jen pokud je volba zapnutá.
            self._announcer.say_char(result.char)
        elif result.status is DecodeStatus.UNKNOWN and result.code:
            self._announcer.say(f"Neznámý kód: {result.code}")

    # ------------------------------------------------------------------
    # Stav
    # ------------------------------------------------------------------

    def _set_status_part(self, key: str, text: str) -> None:
        self._status_parts[key] = text

    def _update_status(self) -> None:
        parts: list[str] = []
        code = self._decoder.current_code
        if code:
            parts.append(f"Rozpracovaný kód: {code}")
        else:
            parts.append("Rozpracovaný kód: žádný")
        if not self._tone_ready_flag:
            parts.append("Tón připravován – klíč dočasně zakázán.")
        for value in self._status_parts.values():
            parts.append(value)
        self.status_label.setText(" | ".join(parts))

    # ------------------------------------------------------------------
    # Aktivace / deaktivace
    # ------------------------------------------------------------------

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow():
                # Deaktivace okna nesmí nechat tón hrát.
                self.key_button.cancel_press()

    def event(self, ev) -> bool:
        # Ztráta fokusu celého okna (přepnutí aplikace).
        if ev.type() == QEvent.Type.WindowDeactivate:
            self.key_button.cancel_press()
        return super().event(ev)

    def closeEvent(self, event: QCloseEvent) -> None:
        # Ukončení zvuku při zavření (úplný asynchronní shutdown až v E5).
        self._stopping = True
        self.key_button.cancel_press()
        self._coordinator.stop_now()
        self._coordinator.shutdown()
        super().closeEvent(event)
