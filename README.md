# Přístupný Morseův přepisovač

Windows aplikace pro zadávání Morseovy abecedy podržením tlačítka (myší
i klávesnicí), její převod na text, hlasité čtení a správu nastavení.

## Hlavní funkce

- **Zadávání Morseovky:** Pomocí Morseova klíče (podržení myši nebo mezerníku s odfiltrováním auto-repeatu), přímých tlačítek tečky a čárky.
- **Automatické a ruční dokončování:** Automatické rozpoznávání písmen a mezer mezi slovy pomocí časovačů, možnost ručního dokončení písmene, mezery či celé zprávy.
- **Opravy:** Možnost vrátit poslední signál (tečku/čárku) nebo poslední dokončený znak.
- **Zvukový engine:** Generování čistého sinusového tónu mimo GUI vlákno (`ToneWorker`) s plynulým náběhem a doběhem přes `AudioCoordinator`.
- **Hlasový výstup (gTTS):** Přečtení aktuálního textu nebo dokončené zprávy v češtině. Hlas se negeneruje automaticky při každé změně, nýbrž výhradně na výslovný pokyn uživatele. Obsahuje paměťovou LRU mezipaměť (max. 50 položek) a podporuje okamžité zastavení.
- **Dialog nastavení:** Přístupný dialog pro úpravu frekvence tónu, hlasitosti, práhu tečky a čárky, časování, průběžného oznamování a hlasitosti řeči.
- **Přístupnost:** Plná ovladatelnost klávesnicí, logické pořadí Tab, viditelný fokus pro všechny prvky, přístupné názvy a popisy, textový stavový řádek pro odečítače obrazovky (NVDA).
- **Asynchronní ukončení (Shutdown):** Bezpečné uzavření aplikace s čekáním na dokončení běžících pracovních vláken bez zablokování hlavního GUI vlákna.

## Spuštění aplikace

```
python src/main.py
```

## Spuštění automatických testů

```
python -m pytest -v
```

## Ochrana soukromí a síť (gTTS)

- gTTS používá online hlasový převod (Google Translate Text-to-Speech).
- Text se při generování řeči odesílá externí službě Google Translate Text-to-Speech (vyžaduje připojení k internetu).
- Text se neposílá automaticky při každé změně, ale pouze na výslovný pokyn uživatele.
- Při chybě sítě aplikace zůstane plně použitelná a chybu oznámí.
- MP3 cache existuje pouze v paměti a má maximálně 50 položek.
