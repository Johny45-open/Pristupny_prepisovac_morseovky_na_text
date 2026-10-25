# Plán: Přístupný Morseův přepisovač pro Windows

Schválená verze plánu (poslední revize). Tento dokument je závazný pro implementaci.

## 1. Výchozí stav a pravidla

- Projekt byl při zahájení prázdný; žádný projektový `AGENTS.md`/`AI_rules.txt`.
- Výhradně PyQt6 (žádný Tkinter/PySide).
- Závislosti: PyQt6, accessible_output2, gTTS, pygame; testovací pytest + pytest-qt.

## 2. Architektura

```
main.py                              – vstup, QApplication, setQuitOnLastWindowClosed(False),
                                      složení, řízené ukončení
src/morseapp/
    __init__.py
    morse_table.py                   – explicitní tabulka Morseových kódů PRO DEKÓDOVÁNÍ
                                      (bez encoderu); normalizace české diakritiky
    classifier.py                    – čistá funkce classify(duration_ms, threshold, min_press)
    decoder.py                       – stavový automat; čas předává volající (testovatelné bez Qt)
    audio.py                         – AudioCoordinator: JEDINÝ vlastník pygame.mixer
    tone_worker.py                   – QRunnable: generování PCM dat tónu (mimo GUI vlákno)
    speech.py                        – SpeechWorker (QThread): gTTS.stream() → MP3 chunks → signál
    announce.py                      – accessible_output2 + potlačení spamu + podmínka volby
    settings_store.py                – QSettings + validace + defaulty
    main_window.py                   – okno, layout, Tab pořádek, dostupnost, signály
    shutdown.py                      – asynchronní řízené ukončení (bez pevné lhůty)
    style_sheet.py                   – stylesheet s per-třídními focus selektory
    widgets/__init__.py
    widgets/key_button.py            – Morseův klíč (myš + mezerník, filtr auto-repeatu)
    settings_dialog.py               – dialog nastavení
tests/…, docs/pristupnost_checklist.md, requirements.txt, README.md, pyproject.toml
```

Pravidla: decoder a classifier = čistý Python bez Qt; všechna volání `pygame.mixer`
jen v `AudioCoordinator`; worker gTTS se dotýká jen sítě a `io.BytesIO`.

## 3. Zvuk a tón

- Ne `winsound.Beep` (blokuje vlákno, nelze předčasně ukončit, nelze měnit hlasitost).
- `pygame.mixer.pre_init(44100, -16, 1, 512)` + `init()`; blok PCM generovaný
  v `tone_worker.py`: sinus s celým počtem cyklů (N = round(44100/f), délka = k×N)
  → spojitý v bodě opakování, žádné rampy v bufferu. U 600 Hz odchylka frekvence < 1 %.
- `Sound.play(loops=-1)` neblokující; náběh = kroky `set_volume` přes QTimer;
  doběh = `Sound.fadeout(15–30 ms)`.
- `AudioCoordinator` (GUI vlákno): jediný vlastník mixeru; stavový stroj
  IDLE / TONE / SPEECH; vzájemné vyloučení. Chyba inicializace → `audio_safe = False`,
  aplikace běží dál, chyba textově i hlasem.
- řeč přes `pygame.mixer.music`, tón přes `Sound`; koordinátor je nikdy nehraje současně.

## 4. Měření stisku a oddělování písmen

- `time.monotonic()` → `duration_ms`; `classifier.classify(duration_ms, threshold, min_press)`:
  - `< min_press` → IGNORE, `min_press ≤ d < threshold` → DOT, `d ≥ threshold` → DASH.
- Default: `threshold = 120 ms`, `min_press = 30 ms`, nastavitelné (prah 50–1000 ms).
  Odůvodnění: dot = 1200/WPM ms; pro 15–25 WPM ideální tečky 48–80 ms, čárky 144–240 ms;
  práh 120 ms leží mezi ideálními délkami. Hranice: 119 → DOT, 120 → DASH,
  29 → IGNORE, 30 → DOT.
- Klávesnice: mezerník; `isAutoRepeat()` ignorováno + flag `key_down`. Myš: press/release
  + grab/`leaveEvent`.
- Ukončení písmene: `QTimer.singleShot` restartovaný po signálu, default 1200 ms (300–3000 ms).
- Ruční ovládání: Dokončit písmeno, Mezera, Dokončit zprávu a přečíst, Poslední signál zpět.
- Auto-mezery mezi slovy: standardně VYPNUTO (volitelný režim, prodleva 3500 ms).
- Mezery: žádná na začátku, max jedna mezi slovy, koncová oříznuta.

## 5. Přístupnost

- `setAccessibleName` + `setAccessibleDescription` u interaktivních prvků; `QLabel.setBuddy`.
- Tab pořádek: klíč → tečka → čárka → dokončit písmeno → mezera → opravy → text →
  čtecí tlačítka → nastavení.
- Viditelný fokus: per-třídní selektory (`QPushButton:focus`, `QLineEdit:focus`,
  `QTextEdit:focus`, `QSpinBox:focus`, `QSlider:focus`, `QCheckBox:focus`);
  `Q:focus` se nepoužívá. Zvětšený border/outline s rezervou, bez skoků layoutu.
- Stav vždy textově ve stavovém poli.
- Podmíněná oznámení: `announce_char(ch)` volá accessible_output2 POUZE pokud je volba
  zapnutá; default VYPNUTO. Přečíst aktuální text / Dokončit zprávu a přečíst fungují
  nezávisle na tomto nastavení.

## 6. Řeč, vlákna a asynchronní ukončení

SpeechWorker:

```python
tts = gTTS(text, lang='cs', timeout=SOCKET_TIMEOUT)
buf = io.BytesIO()
for chunk in tts.stream():        # MP3 části po částech
    if QThread.currentThread().isInterruptionRequested():
        emit interrupted(); return
    buf.write(chunk)
emit mp3_ready(request_id, buf.getvalue())
```

- `stream()` umožňuje kooperativní kontrolu přerušení mezi částmi; každý jednotlivý
  `next()` je stále synchronní blokující HTTP (omezený timeoutem) – uvnitř části
  přerušit nelze.
- LRU mezipaměť (text, lang) → MP3 bytes (~50 položek); ID požadavku brání aplikaci
  neaktuálních výsledků.

Asynchronní ukončení:

1. `main.py` volá `QApplication.setQuitOnLastWindowClosed(False)` – zavření okna
   samo o sobě neukončí event loop.
2. Při zavření: okno skryto (`hide()`), přehrávání zastaveno (tone fadeout,
   `music.stop()`) přes `AudioCoordinator`.
3. Kooperativní ukončení workerů (`requestInterruption()`).
4. Žádný blokující `wait()` v GUI vlákně; event loop běží dál; reference drží
   „hřbitov" (`active_threads`), dokud všichni neohlásí `finished`.
5. Až všichni potřební pracovníci ohlásí `finished` → `pygame.mixer.quit()` →
   `QApplication.quit()`.
6. Běžící `QThread` se nikdy nezničí; pevná lhůta se nepoužívá ani neinzeruje.

## 7. Tabulka souborů

| Soubor | Akce | Etapa |
|---|---|---|
| `requirements.txt`, `pyproject.toml`, `README.md`, `.gitignore`, `docs/plan.md` | vytvořit | E0 |
| `src/morseapp/{__init__,settings_store}.py` | vytvořit | E0 |
| `tests/test_settings.py` | vytvořit | E0 |
| `src/morseapp/{morse_table,classifier,decoder}.py` | vytvořit | E1 |
| `tests/{test_morse_table,test_classifier,test_decoder}.py` | vytvořit | E1 |
| `src/morseapp/{audio,tone_worker}.py` | vytvořit | E2 |
| `tests/test_audio.py` (jen bezpečné zastavení enginu) | vytvořit | E2 |
| `src/morseapp/{main_window,announce,style_sheet}.py`, `widgets/{__init__,key_button}.py` | vytvořit | E3 |
| `tests/{test_accessibility,test_key_button}.py` | vytvořit | E3 |
| `src/morseapp/{speech,shutdown}.py`, `settings_dialog.py` | vytvořit | E4 |
| `tests/{test_speech,test_threads}.py` | vytvořit | E4 |
| `docs/pristupnost_checklist.md` (šablona) | vytvořit | E3 |
| `tests/test_shutdown.py` (úplný test asynchronního zavření) | vytvořit | E5 |
| `docs/pristupnost_checklist.md` (vyplnění) | dokončit | E5 |

## 8. Etapy E0–E5

- **E0 – Kostra a Git.** `git init`, `.gitignore`, úvodní commit; `settings_store`
  s validací (threshold 120 ms, announce OFF); `requirements.txt`, `pyproject.toml`.
  Kritérium: `pytest` zelený pro `test_settings.py`; Git ≥ 1 commit.
- **E1 – Dekódovací jádro.** `morse_table` (dekódovací tabulka bez encoderu),
  `classifier`, `decoder`. Kritérium: testy 1–9 zelené (literální očekávané kódy).
- **E2 – Zvukový engine.** `audio.py`, `tone_worker.py`. Kritérium: testy zvuku
  včetně bezpečného zastavení enginu zelené.
- **E3 – GUI a přístupnost.** `main_window.py`, `announce.py`, `style_sheet.py`,
  `key_button.py`. Kritérium: testy přístupnosti zelené.
- **E4 – Řeč a vlákna.** `speech.py`, `test_speech.py`, `test_threads.py`.
  Kritérium: testy 12, 13 zelené; kontrola přerušení mezi částmi streamu otestována.
- **E5 – Ukončení, dialog, dokončení.** `shutdown.py`, `settings_dialog.py`,
  `test_shutdown.py`, checklist. Kritérium: úplný asynchronní shutdown otestován
  (zavření okna neukončí event loop před `finished` všech workerů); kompletní
  `pytest -v` zelený.

## 9. Testy

| # | Test | Etapa |
|---|---|---|
| 1 | Písmena a číslice | E1 |
| 2 | Interpunkce | E1 |
| 3 | Tečka/čárka podle délky | E1+E2 |
| 4 | Hranice 119/120 ms, minimum 29/30 ms | E1 |
| 5 | Auto i ruční oddělení písmen | E1 |
| 6 | Mezery mezi slova | E1 |
| 7 | Dokončení zprávy s rozpracovaným písmenem | E1 |
| 8 | Neznámý/neúplný kód | E1 |
| 9 | Mazání a opravy | E1 |
| 10 | Ukládání/obnova nastavení | E0 |
| 11 | Ukončení: zastavení enginu (E2) / úplný asynchronní shutdown (E5) | E2+E5 |
| 12 | Selhání internetu | E4 |
| 13 | GUI nezamrzne; přerušení streamu mezi částmi | E4 |
| 14 | Přístupnost (jen interaktivní prvky; fokus přes per-třídní selektory) | E3 |

## 10. Rizika

- accessible_output2 + PyQt6 neověřeno předem; ověřit v E3 s NVDA.
- gTTS: každá část streamu je blokující HTTP; ukončení čeká na skutečné `finished`.
- Sinus: odchylka frekvence < 1 % kvůli celým cyklům (neslyšitelná).
- Focus stylesheet: test ověří existenci pravidel; vizuální kontrola ručně v E5.

## 11. Závislosti

- Již nainstalováno: PyQt6, accessible_output2, gTTS, pygame, pytest.
- Chybí: pytest-qt (test-only).
- Až po schválení relevantní etapy: `python -m pip install pytest-qt`, `python -m pytest -v`.
