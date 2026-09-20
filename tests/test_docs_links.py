"""文書どうしのリンクが切れていないこと、記録表とノートが食い違わないこと。

README を分割して記録ノートを docs/records/ へ出したので、リンクが
「ファイルをまたぐ」ようになった。相対パスは静かに切れるし、記録表とノートの
frontmatter は同じ数字を2か所に持っている。どちらも検査で留める。
"""

from __future__ import annotations

import pathlib
import re
import unicodedata

import pytest
from conftest import ROOT

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6} (.+)$")
# 記録表の1行: | 1 | `impl/01_wrapper/` | ... | **6:33:28** | **1.36×** | 2026-09-14 | ... |
ROW = re.compile(
    r"^\| (\d+) \| `impl/([^`]+?)/` \| [^|]* \| \*\*([\d:]+)\*\* \| "
    r"\*?\*?([\d.]+)×\*?\*? \| ([\d-]+) \|"
)
FRONT = re.compile(r"^(\w+): (.+)$", re.M)


def documents() -> list[pathlib.Path]:
    found = [ROOT / "README.md", ROOT / "CLAUDE.md"]
    for pattern in ("docs/**/*.md", "experiments/**/*.md"):
        found += sorted(ROOT.glob(pattern))
    return [p for p in found if p.is_file()]


def anchors(path: pathlib.Path) -> set[str]:
    """GitHub が見出しから作るアンカー (記号を落として空白をハイフンに)。"""
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = HEADING.match(line)
        if m:
            text = re.sub(r"[`*]", "", m.group(1)).strip().lower()
            out.add(re.sub(r"[^\w　-鿿＀-￯ -]", "", text).replace(" ", "-"))
    return out


def relative_links() -> list[tuple[pathlib.Path, str]]:
    out: list[tuple[pathlib.Path, str]] = []
    for src in documents():
        for raw in LINK.findall(src.read_text(encoding="utf-8")):
            if not raw.startswith(("http://", "https://", "mailto:")):
                out.append((src, raw))
    return out


def record_rows() -> dict[int, tuple[str, str, str, str]]:
    """README の記録表から (実装, タイム, 倍率, 日付) を拾う。"""
    rows: dict[int, tuple[str, str, str, str]] = {}
    for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m:
            rows[int(m.group(1))] = (m.group(2), m.group(3), m.group(4), m.group(5))
    return rows


def note_for(number: int) -> pathlib.Path:
    found = sorted((ROOT / "docs" / "records").glob(f"{number:02d}-*.md"))
    assert len(found) == 1, f"記録 #{number} のノートが {len(found)} 本ある"
    return found[0]


@pytest.mark.parametrize(("src", "raw"), relative_links(), ids=lambda v: str(v)[-60:])
def test_every_relative_link_resolves(src: pathlib.Path, raw: str) -> None:
    path, _, fragment = raw.partition("#")
    target = (src.parent / path).resolve() if path else src.resolve()
    assert target.exists(), f"{src.relative_to(ROOT)} のリンク先が無い: {raw}"
    if fragment and target.is_file() and target.suffix == ".md":
        assert unicodedata.normalize("NFC", fragment.lower()) in anchors(target), (
            f"{src.relative_to(ROOT)}: {raw} に当たる見出しが無い"
        )


def test_the_record_numbers_run_from_one_without_gaps() -> None:
    """件数は固定しない。記録 #13 を足したら通るのが正しい。

    見るのは番号が1から連番であること。抜けや重複があれば落ちる。
    """
    numbers = sorted(record_rows())
    assert numbers, "記録表が読めていない (表の書式が変わった可能性)"
    assert numbers == list(range(1, len(numbers) + 1)), f"番号が連番でない: {numbers}"


def test_the_table_and_the_notes_match_one_to_one() -> None:
    """記録表とノートの過不足。片側だけ足したら落ちる。"""
    notes = {int(p.name[:2]) for p in (ROOT / "docs" / "records").glob("[0-9][0-9]-*.md")}
    rows = set(record_rows())
    assert notes - rows == set(), f"記録表に行の無いノート: {sorted(notes - rows)}"
    assert rows - notes == set(), f"ノートの無い記録表の行: {sorted(rows - notes)}"


@pytest.mark.parametrize("number", sorted(record_rows()))
def test_each_record_row_links_to_its_note(number: int) -> None:
    """記録表の行から、その試行のノートへ行けること。"""
    note = note_for(number)
    rel = note.relative_to(ROOT).as_posix()
    row = next(
        line
        for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
        if ROW.match(line) and int(str(ROW.match(line).group(1))) == number  # type: ignore[union-attr]
    )
    assert f"]({rel})" in row, f"記録 #{number} の行が {rel} を指していない"


@pytest.mark.parametrize("number", sorted(record_rows()))
def test_the_note_frontmatter_agrees_with_the_record_table(number: int) -> None:
    """同じ数字を2か所に置いているので、ずれたら落とす。"""
    impl, time, speedup, date = record_rows()[number]
    front = dict(FRONT.findall(note_for(number).read_text(encoding="utf-8").split("---")[1]))
    assert front["record"] == str(number)
    assert front["impl"] == f"impl/{impl}/"
    assert front["time"].strip('"') == time
    assert front["speedup"] == speedup
    assert front["date"] == date


def test_the_index_lists_every_note() -> None:
    index = (ROOT / "docs" / "records" / "README.md").read_text(encoding="utf-8")
    for path in sorted((ROOT / "docs" / "records").glob("[0-9][0-9]-*.md")):
        assert f"({path.name})" in index, f"{path.name} が索引に無い"
