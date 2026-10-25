# Přístupný Morseův přepisovač

Windows aplikace pro zadávání Morseovy abecedy podržením tlačítka (myší
i klávesnicí), její převod na text a hlasité přečtení výsledku.

## Stav projektu

Implementace probíhá po etapách E0–E5 dle schváleného plánu v [`docs/plan.md`](docs/plan.md).

- **E0 (dokončeno):** kostra projektu, Git, `settings_store` s validací a výchozími
  hodnotami (práh 120 ms, průběžné hlasové oznamování vypnuto), testy `tests/test_settings.py`.
- **E1–E4 (dokončeno):** dekódovací tabulka, klasifikátor, dekodér, audio engine (`AudioCoordinator`), hlavní okno (`MainWindow`), přístupnost, Morseův klíč, hlasový výstup v češtině přes gTTS (`SpeechWorker`) a paměťová LRU mezipaměť (max. 50 položek).

## Hlasový výstup a soukromí (gTTS)

- gTTS používá online hlasový převod (Google Translate Text-to-Speech).
- Text se při generování řeči odesílá externí službě Google Translate Text-to-Speech.
- Generování řeči vyžaduje připojení k internetu.
- Text se **neposílá automaticky** při každé změně – převod se spouští výhradně na výslovný požadavku uživatele (tlačítka „Přečíst aktuální text“ nebo „Dokončit zprávu a přečíst“).
- Při chybě sítě (nebo výpadku) zůstane aplikace plně použitelná a chybu přehledně oznámí ve stavovém řádku i hlasovým oznámením.
- Mezipaměť MP3 souborů (`SpeechCache`) existuje **pouze v paměti** (nikdy se neukládá trvale na disk) a má pevnou kapacitu maximálně 50 položek s politikou LRU.
- Obsah zpráv se automaticky neukládá na disk.

## Spuštění testů

```
python -m pytest -v
```

## Závislosti

```
python -m pip install -r requirements.txt
```
