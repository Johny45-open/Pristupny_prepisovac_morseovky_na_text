"""Style sheet aplikace s per-třídními selektory fokusu.

``Q:focus`` není univerzálním selektorem – používají se konkrétní třídy
skutečně použitých interaktivních widgetů. Rámeček je řešen ``border``
(vlastnost podporovaná Qt Style Sheets); výchozí rámeček je průhledný
a má stejnou šířku jako fokusový, takže se zaměřením **neposkakuje
rozložení**. Fokus se také liší tloušťkou viditelného orámování, ne jen
barvou.

Viditelnost fokusu se testuje jen na úrovni existence pravidel;
skutečný vzhled se kontroluje ručně (docs/pristupnost_checklist.md).
"""

# Konstantní šířka rámečku zabraňuje skokům rozložení při fokusu.
BORDER_WIDTH = "3px"
FOCUS_COLOR = "#005fcc"

APP_STYLESHEET = f"""
QPushButton {{
    border: {BORDER_WIDTH} solid transparent;
    padding: 3px 8px;
}}
QPushButton:focus {{
    border: {BORDER_WIDTH} solid {FOCUS_COLOR};
}}
QLineEdit:focus {{
    border: {BORDER_WIDTH} solid {FOCUS_COLOR};
}}
QTextEdit:focus {{
    border: {BORDER_WIDTH} solid {FOCUS_COLOR};
}}
QSpinBox:focus {{
    border: {BORDER_WIDTH} solid {FOCUS_COLOR};
}}
QSlider:focus {{
    border: {BORDER_WIDTH} solid {FOCUS_COLOR};
}}
QCheckBox:focus {{
    border: {BORDER_WIDTH} solid {FOCUS_COLOR};
}}
"""
