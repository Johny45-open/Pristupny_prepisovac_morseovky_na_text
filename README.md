# Přístupný Morseův přepisovač

Windows aplikace pro zadávání Morseovy abecedy podržením tlačítka (myší
i klávesnicí), její převod na text a hlasité přečtení výsledku.

## Stav projektu

Implementace probíhá po etapách E0–E5 dle schváleného plánu v [`docs/plan.md`](docs/plan.md).

- **E0 (dokončeno):** kostra projektu, Git, `settings_store` s validací a výchozími
  hodnotami (práh 120 ms, průběžné hlasové oznamování vypnuto), testy `tests/test_settings.py`.

## Spuštění testů

```
python -m pytest -v
```

## Závislosti

```
python -m pip install -r requirements.txt
```
