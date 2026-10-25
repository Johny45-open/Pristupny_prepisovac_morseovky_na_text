"""Přístupný dialog nastavení aplikace (etapa E5).

Umožňuje upravit podporované parametry:
- Frekvence tónu (Hz)
- Hlasitost tónu (%)
- Práh tečka/čárka (ms)
- Min. délka stisku (ms)
- Prodleva ukončení písmene (ms)
- Automatické mezery mezi slovy (zapnuto/vypnuto)
- Prodleva pro automatickou mezeru (ms)
- Průběžné hlasové oznamování (zapnuto/vypnuto)
- Hlasitost řeči (%)

Zajišťuje:
- Propojení popisků pomocí setBuddy().
- Přístupné názvy a popisy pro odečítače obrazovky.
- Logické pořadí Tab a viditelný fokus.
- Validaci hodnot (zápis přes normalize z settings_store).
- Tlačítka Uložit a Zrušit (při zrušení se změny neaplikují).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .settings_store import RANGES, Settings, normalize


class SettingsDialog(QDialog):
    """Dialog nastavení aplikace."""

    def __init__(self, current_settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nastavení – Přístupný Morseův přepisovač")
        self.setAccessibleName("Dialog nastavení")
        self.setAccessibleDescription("Úprava parametrů zvuku, časování a chování aplikace.")
        self._initial_settings = current_settings
        self._result_settings = current_settings

        self._build_ui()
        self._load_values(current_settings)

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        form_layout = QFormLayout()

        # 1. Frekvence tónu
        self.tone_freq_spin = QSpinBox()
        self.tone_freq_spin.setRange(RANGES["tone_frequency_hz"][0], RANGES["tone_frequency_hz"][1])
        self.tone_freq_spin.setSuffix(" Hz")
        self.tone_freq_spin.setAccessibleName("Frekvence tónu")
        self.tone_freq_spin.setAccessibleDescription("Frekvence generovaného Morseova tónu v Hertzech.")
        freq_label = QLabel("&Frekvence tónu:")
        freq_label.setBuddy(self.tone_freq_spin)
        form_layout.addRow(freq_label, self.tone_freq_spin)

        # 2. Hlasitost tónu
        self.tone_vol_spin = QSpinBox()
        self.tone_vol_spin.setRange(RANGES["tone_volume"][0], RANGES["tone_volume"][1])
        self.tone_vol_spin.setSuffix(" %")
        self.tone_vol_spin.setAccessibleName("Hlasitost tónu")
        self.tone_vol_spin.setAccessibleDescription("Hlasitost přehrávaného Morseova tónu v procentech.")
        tone_vol_label = QLabel("H&lasitost tónu:")
        tone_vol_label.setBuddy(self.tone_vol_spin)
        form_layout.addRow(tone_vol_label, self.tone_vol_spin)

        # 3. Práh tečka/čárka
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(RANGES["threshold_ms"][0], RANGES["threshold_ms"][1])
        self.threshold_spin.setSuffix(" ms")
        self.threshold_spin.setAccessibleName("Práh tečky a čárky")
        self.threshold_spin.setAccessibleDescription("Délka stisku v milisekundách pro rozlišení tečky a čárky.")
        threshold_label = QLabel("&Práh tečka / čárka:")
        threshold_label.setBuddy(self.threshold_spin)
        form_layout.addRow(threshold_label, self.threshold_spin)

        # 4. Min. délka stisku
        self.min_press_spin = QSpinBox()
        self.min_press_spin.setRange(RANGES["min_press_ms"][0], RANGES["min_press_ms"][1])
        self.min_press_spin.setSuffix(" ms")
        self.min_press_spin.setAccessibleName("Minimální délka stisku")
        self.min_press_spin.setAccessibleDescription("Kratší stisky než tato hodnota jsou ignorovány.")
        min_press_label = QLabel("&Minimální délka stisku:")
        min_press_label.setBuddy(self.min_press_spin)
        form_layout.addRow(min_press_label, self.min_press_spin)

        # 5. Prodleva ukončení písmene
        self.letter_gap_spin = QSpinBox()
        self.letter_gap_spin.setRange(RANGES["letter_gap_ms"][0], RANGES["letter_gap_ms"][1])
        self.letter_gap_spin.setSuffix(" ms")
        self.letter_gap_spin.setAccessibleName("Prodleva ukončení písmene")
        self.letter_gap_spin.setAccessibleDescription("Čas bez signálu pro automatické dokončení rozpracovaného písmene.")
        letter_gap_label = QLabel("Prodleva ukončení &písmene:")
        letter_gap_label.setBuddy(self.letter_gap_spin)
        form_layout.addRow(letter_gap_label, self.letter_gap_spin)

        # 6. Automatické mezery mezi slovy
        self.auto_word_space_check = QCheckBox("&Automatické mezery mezi slovy")
        self.auto_word_space_check.setAccessibleName("Automatické mezery mezi slovy")
        self.auto_word_space_check.setAccessibleDescription("Zda vkládat mezeru mezi slovy na základě dlouhé prodlevy.")
        form_layout.addRow("", self.auto_word_space_check)

        # 7. Prodleva pro automatickou mezeru
        self.auto_word_gap_spin = QSpinBox()
        self.auto_word_gap_spin.setRange(RANGES["auto_word_gap_ms"][0], RANGES["auto_word_gap_ms"][1])
        self.auto_word_gap_spin.setSuffix(" ms")
        self.auto_word_gap_spin.setAccessibleName("Prodleva pro automatickou mezeru")
        self.auto_word_gap_spin.setAccessibleDescription("Čas bez signálu pro vložení mezery mezi slova.")
        word_gap_label = QLabel("Prodleva pro automatickou &mezeru:")
        word_gap_label.setBuddy(self.auto_word_gap_spin)
        form_layout.addRow(word_gap_label, self.auto_word_gap_spin)

        # 8. Průběžné hlasové oznamování
        self.continuous_announce_check = QCheckBox("P&růběžné hlasové oznamování písmen")
        self.continuous_announce_check.setAccessibleName("Průběžné hlasové oznamování písmen")
        self.continuous_announce_check.setAccessibleDescription("Zda hlasitě oznamovat každé nově dokončené písmeno.")
        form_layout.addRow("", self.continuous_announce_check)

        # 9. Hlasitost řeči
        self.speech_vol_spin = QSpinBox()
        self.speech_vol_spin.setRange(RANGES["speech_volume"][0], RANGES["speech_volume"][1])
        self.speech_vol_spin.setSuffix(" %")
        self.speech_vol_spin.setAccessibleName("Hlasitost řeči")
        self.speech_vol_spin.setAccessibleDescription("Hlasitost hlasového výstupu v procentech.")
        speech_vol_label = QLabel("Hlasitost &řeči:")
        speech_vol_label.setBuddy(self.speech_vol_spin)
        form_layout.addRow(speech_vol_label, self.speech_vol_spin)

        main_layout.addLayout(form_layout)

        # Tlačítka Uložit / Zrušit
        btn_layout = QHBoxLayout()
        self.save_button = QPushButton("&Uložit")
        self.save_button.setDefault(True)
        self.save_button.setAccessibleName("Uložit nastavení")
        self.save_button.setAccessibleDescription("Uloží změny a zavře dialog nastavení.")

        self.cancel_button = QPushButton("Z&rušit")
        self.cancel_button.setAccessibleName("Zrušit nastavení")
        self.cancel_button.setAccessibleDescription("Zavře dialog bez uložení změn.")

        btn_layout.addStretch()
        btn_layout.addWidget(self.save_button)
        btn_layout.addWidget(self.cancel_button)
        main_layout.addLayout(btn_layout)

        self.save_button.clicked.connect(self._on_save)
        self.cancel_button.clicked.connect(self.reject)

    def _load_values(self, settings: Settings) -> None:
        self.tone_freq_spin.setValue(settings.tone_frequency_hz)
        self.tone_vol_spin.setValue(settings.tone_volume)
        self.threshold_spin.setValue(settings.threshold_ms)
        self.min_press_spin.setValue(settings.min_press_ms)
        self.letter_gap_spin.setValue(settings.letter_gap_ms)
        self.auto_word_space_check.setChecked(settings.auto_word_space)
        self.auto_word_gap_spin.setValue(settings.auto_word_gap_ms)
        self.continuous_announce_check.setChecked(settings.continuous_announce)
        self.speech_vol_spin.setValue(settings.speech_volume)

    def _on_save(self) -> None:
        raw = {
            "tone_frequency_hz": self.tone_freq_spin.value(),
            "tone_volume": self.tone_vol_spin.value(),
            "threshold_ms": self.threshold_spin.value(),
            "min_press_ms": self.min_press_spin.value(),
            "letter_gap_ms": self.letter_gap_spin.value(),
            "auto_word_space": self.auto_word_space_check.isChecked(),
            "auto_word_gap_ms": self.auto_word_gap_spin.value(),
            "continuous_announce": self.continuous_announce_check.isChecked(),
            "speech_volume": self.speech_vol_spin.value(),
        }
        # Validace a normalizace přes robustní normalize z settings_store
        self._result_settings = normalize(raw)
        self.accept()

    @property
    def settings(self) -> Settings:
        return self._result_settings
