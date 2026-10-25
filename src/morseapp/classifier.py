"""Klasifikace délky stisku na tečku, čárku nebo ignorování.

Čistý Python bez Qt a bez závislosti na reálném čase – volající předává
naměřenou délku, funkce je deterministická (testovatelná bez čekání).

Pravidla (dle schváleného plánu):

- ``duration < min_press``  → ``IGNORE`` (náhodné ťuknutí, rušení)
- ``min_press <= duration < threshold`` → ``DOT``
- ``duration >= threshold`` → ``DASH`` (hranice patří čárce)

Výchozí hodnoty: ``threshold = 120 ms``, ``min_press = 30 ms``
(119 ms → DOT, 120 ms → DASH, 29 ms → IGNORE, 30 ms → DOT).
"""

from __future__ import annotations

from enum import Enum, auto


class Signal(Enum):
    """Výsledek klasifikace jednoho stisku."""

    DOT = auto()     # tečka
    DASH = auto()    # čárka
    IGNORE = auto()  # stisk příliš krátký – nezaznamenat


# Výchozí hodnoty dle schváleného plánu.
DEFAULT_THRESHOLD_MS = 120
DEFAULT_MIN_PRESS_MS = 30


def classify(
    duration_ms: float,
    threshold: float = DEFAULT_THRESHOLD_MS,
    min_press: float = DEFAULT_MIN_PRESS_MS,
) -> Signal:
    """Klasifikuje délku stisku podle pravidel výše.

    Vyhodí ``ValueError`` při neplatné konfiguraci:

    - ``threshold`` není kladné,
    - ``min_press`` není kladné,
    - ``min_press > threshold`` (rozdílení by bylo nesmyslné).

    Záporná nebo nulová ``duration`` je považována za ``IGNORE``
    (neobvyklý vstup, ale nesmí spadnout).
    """
    if threshold <= 0:
        raise ValueError(f"threshold musí být kladné, dostávám {threshold}")
    if min_press <= 0:
        raise ValueError(f"min_press musí být kladný, dostávám {min_press}")
    if min_press > threshold:
        raise ValueError(
            f"min_press ({min_press}) nesmí být větší než threshold ({threshold})"
        )

    if duration_ms < min_press:
        return Signal.IGNORE
    if duration_ms < threshold:
        return Signal.DOT
    return Signal.DASH
