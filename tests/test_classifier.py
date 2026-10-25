"""Testy klasifikátoru délky stisku (požadavky č. 3 a 4 plánu).

Deterministické – žádné čekání v reálném čase, žádné Qt.
"""

from __future__ import annotations

import pytest

from morseapp.classifier import (
    DEFAULT_MIN_PRESS_MS,
    DEFAULT_THRESHOLD_MS,
    Signal,
    classify,
)


def test_default_values_match_plan():
    assert DEFAULT_THRESHOLD_MS == 120
    assert DEFAULT_MIN_PRESS_MS == 30


def test_plan_boundary_29_is_ignore():
    assert classify(29) is Signal.IGNORE


def test_plan_boundary_30_is_dot():
    assert classify(30) is Signal.DOT


def test_plan_boundary_119_is_dot():
    assert classify(119) is Signal.DOT


def test_plan_boundary_120_is_dash():
    assert classify(120) is Signal.DASH


def test_plan_boundary_200_is_dash():
    assert classify(200) is Signal.DASH


def test_typical_dot_and_dash():
    assert classify(80) is Signal.DOT
    assert classify(360) is Signal.DASH


def test_very_short_press_is_ignored():
    assert classify(0) is Signal.IGNORE
    assert classify(1) is Signal.IGNORE
    assert classify(5) is Signal.IGNORE


def test_negative_duration_is_ignored_not_crash():
    assert classify(-10) is Signal.IGNORE


def test_float_durations_work():
    assert classify(29.9) is Signal.IGNORE
    assert classify(30.0) is Signal.DOT
    assert classify(119.9) is Signal.DOT
    assert classify(120.0) is Signal.DASH


def test_custom_threshold_is_respected():
    assert classify(149, threshold=150) is Signal.DOT
    assert classify(150, threshold=150) is Signal.DASH
    assert classify(40, threshold=50, min_press=40) is Signal.DOT
    assert classify(39, threshold=50, min_press=40) is Signal.IGNORE


def test_invalid_config_raises():
    with pytest.raises(ValueError):
        classify(100, threshold=0)
    with pytest.raises(ValueError):
        classify(100, threshold=-5)
    with pytest.raises(ValueError):
        classify(100, min_press=0)
    with pytest.raises(ValueError):
        classify(100, threshold=100, min_press=101)


def test_function_is_pure_and_deterministic():
    # Stejný vstup → stejný výsledek, nezávisí na čase ani Qt.
    results = {classify(119) for _ in range(10)}
    assert results == {Signal.DOT}
