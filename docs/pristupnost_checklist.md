# Checklist ručního ověření přístupnosti

> **Toto je šablona – zatím NENÍ vyplněná ani provedená.**
> Žádná položka níže nebyla otestována. Automatické testy
> (`tests/test_accessibility.py`, `tests/test_key_button.py`) ruční
> ověření s odečítačem obrazovky nenahrazují.
>
> Datum ověření: ____________  Ověřoval: ____________  Verze: ____________
> Screen reader: □ NVDA  □ Narrator  □ Jiné: ________

## Spuštění

- [ ] Aplikace se spustí bez chyby a okno je viditelné.
- [ ] Při spuštění screen reader oznámí název okna srozumitelně.

## Pořadí Tab a názvy prvků

- [ ] Tab postupně prochází: Morseův klíč → Vložit tečku → Vložit čárku →
      Dokončit písmeno → Vložit mezeru → Vrátit poslední signál →
      Vrátit poslední znak → Dokončit zprávu → Výsledný text.
- [ ] Každý prvek má srozumitelný název čtený screen readerem.
- [ ] Popisy klíče, tečky/čárky a Dokončit zprávu jsou předneseny
      a dávají smysl.

## Morseův klíč – klávesnice

- [ ] Mezerník při stisku spustí tón, při uvolnění ho ukončí.
- [ ] Držení mezerníku nevytváří opakované signály (auto-repeat).
- [ ] Krátký stisk = tečka, dlouhý = čárka (slyšet i vidět ve stavu).
- [ ] Ztráta fokusu během držení tón bezpečně ukončí.

## Morseův klíč – myš

- [ ] Stisk myší spustí tón, uvolnění ho ukončí.
- [ ] Uvolnění myši mimo tlačítko nezanechá tón hrát.

## Ovládání dekodéru bez myši

- [ ] Přímé vložení tečky a čárky tlačítky jen klávesnicí.
- [ ] Dokončit písmeno / Vložit mezeru / Vrátit / Dokončit zprávu
      fungují klávesnicí.
- [ ] Výsledný text je procházelný šipkami a kopírovatelný.
- [ ] Neznámý kód se zobrazí jako `[kód]` a screen reader ho přečte.

## Viditelný fokus

- [ ] Zaměřený prvek je zřetelně orámován (styk 3 px, ne jen barva).
- [ ] Při procházení Tab není fokus ztracen mezi prvky.
- [ ] Rozložení se při fokusu neskáče.

## Stav a chyby

- [ ] Rozpracovaný Morseův kód je čitelný ze stavového řádku.
- [ ] Stav zvuku (připraven / nedostupný) je textově a nahlas.
- [ ] Chyba zvuku / generování tónu je oznámena i vidět textově.
- [ ] Oznámení se neopakují zbytečně (spam).
- [ ] Průběžné oznamování písmen je ve výchozím stavu VYPNUTÉ;
      po zapnutí v nastavení se písmena oznamují.

## Zvuk (poslech na skutečném zařízení)

- [ ] Tón začíná bez znatelné prodlevy.
- [ ] Náběh tónu nekliká.
- [ ] Doběh při uvolnění nekliká.
- [ ] Frekvence a hlasitost odpovídají nastavení.
- [ ] Tón a případný hlasový výstup se nepřekrývají.

## Poznámky

