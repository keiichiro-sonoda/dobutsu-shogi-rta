"""テスト共通の定数とフィクスチャ。"""

from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ORACLE_DIR = ROOT / "oracle"
BASELINE_DIR = ROOT / "baseline"
RESULTS_DIR = ROOT / "results"

# (深さ, "win" | "lose", 局面数)
DistRow = tuple[int, str, int]


def load_distribution() -> list[DistRow]:
    rows: list[DistRow] = []
    text = (ORACLE_DIR / "distribution.tsv").read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        depth, result, count = line.split("\t")
        rows.append((int(depth), result, int(count)))
    return rows


def load_totals() -> dict[str, int]:
    totals: dict[str, int] = {}
    text = (ORACLE_DIR / "totals.tsv").read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        key, value = line.split("\t")[:2]
        totals[key] = int(value)
    return totals


@pytest.fixture(scope="session")
def distribution() -> list[DistRow]:
    return load_distribution()


@pytest.fixture(scope="session")
def totals() -> dict[str, int]:
    return load_totals()
