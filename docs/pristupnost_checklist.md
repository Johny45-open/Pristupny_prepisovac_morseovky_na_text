# Checklist přístupnosti – Přístupný Morseův přepisovač

Tento dokument slouží jako ověřovací seznam pro splnění požadavků na přístupnost a ovládání aplikace.

## 1. Ověření klávesnicového ovládání a fokusu

- [x] **Průchod aplikací klávesou Tab:** Všechny interaktivní prvky v hlavním okně i v dialogu nastavení jsou dosažitelné klávesou Tab v logickém pořadí (klíč -> tečka -> čárka -> dokončit písmeno -> mezera -> vrátit signál -> vrátit znak -> dokončit zprávu -> textové pole -> přečíst text -> zastavit hlas -> nastavení).
- [x] **Viditelný fokus:** Všechny ovládací prvky mají explicitně definované per-třídní selektory (`:focus`) se zřetelným ohraničením (outline/border) a dostatečným kontrastem bez posunu layoutu.
- [x] **Ovládání Morseova klíče:** Klíč lze ovládat stiskem a uvolněním klávesy Mezerovník (přičemž systémový auto-repeat klávesnice je spolehlivě odfiltrován) i kliknutím myší.
- [x] **Dialog nastavení:** Prvky formuláře v dialogu jsou propojeny s popisky pomocí `QLabel.setBuddy()`, obsahují přístupné názvy (`setAccessibleName`) a popisy (`setAccessibleDescription`). Dialog lze plně ovládat z klávesnice (Esc ruší, Enter/Uložit potvrzuje).

## 2. Zvuk, oznamování a čtečky obrazovky (NVDA / odečítače)

- [x] **Textový stavový řádek:** Veškerý důležitý stav (rozpracovaný Morseův kód, dostupnost zvuku, stav hlasu) je indikován textově ve stavovém řádku, který je přístupný pro odečítače obrazovky.
- [x] **Průběžné oznamování písmen:** Standardně vypnuto (`continuous_announce = False`). Lze jej zapnout v dialogu nastavení, aniž by to omezovalo explicitní hlasové čtení celého textu.
- [x] **Explicitní čtení textu a hlasové funkce:** Tlačítka „Přečíst aktuální text“, „Dokončit zprávu a přečíst“ a „Zastavit hlas“ fungují na výslovný pokyn uživatele. gTTS nikdy negeneruje řeč automaticky při běžném psaní Morseovky.
- [x] **Chybové stavy sítě a audia:** Při chybě sítě (timeout, výpadek připojení) nebo nedostupném audio zařízení se aplikace nezhroutí, zůstane plně použitelná a chybu oznámí textově i přístupně.

## 3. Životní cyklus, vlákna a bezpečné ukončení

- [x] **Asynchronní shutdown:** Zavření okna nespustí okamžité zničení event loopu (`setQuitOnLastWindowClosed(False)`). Aplikace čeká na kooperativní dokončení běžících pracovních vláken (`SpeechWorker` / `ToneWorker`) bez blokování hlavního GUI vlákna.
- [x] **Žádné násilné ničení vláken:** K žádnému ukončování vláken se nepoužívá `QThread.terminate()`. Všechna vlákna reagují na `requestInterruption()`.
- [x] **Vzájemné vyloučení tónu a řeči:** `AudioCoordinator` zajišťuje, že tón a řeč se nikdy nepřehrávají současně (spuštění jednoho okamžitě zastaví druhé).

---
*Poznámka: Položky označené `[x]` byly ověřity automatizovanými testy (včetně testů přístupnosti widgetů, Tab pořádku, dialogu a shutdownu). Ruční ověření s fyzickým zařízením NVDA závisí na konkrétním nasazení v operačním systému Windows.*
