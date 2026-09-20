"""tools/doc_lint.py — 文書の分量の上限を機械に持たせる。

規約だけでは止まらなかった (CLAUDE.md に書いてあったのに README は 1479行、
`⚠️` 139個まで伸びた) ので、上限を検査にした。既存の債務は baseline に
固定してあり、新しく増えたぶんだけが FAIL になる。

ここではルールごとに小さな文書を作って、境界と「言及は数えない」を確かめる。
最後に、リポジトリの実物に対して新規違反がゼロであることも見る。
"""

from __future__ import annotations

import pathlib

import doc_lint
import pytest

WARN = "⚠️"
KEY = "\U0001f511"


def write(root: pathlib.Path, rel: str, text: str) -> pathlib.Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_sections_splits_on_headings_and_keeps_the_preamble() -> None:
    got = doc_lint.sections("まえがき\n\n## あ\n1\n\n### い\n2\n")
    assert [loc for loc, _ in got] == [doc_lint.PREAMBLE, "あ", "い"]
    assert "まえがき" in got[0][1]
    assert "1" in got[1][1] and "2" in got[2][1]


def test_the_heading_line_itself_counts_toward_its_section() -> None:
    """見出しに付けた警告も1個と数える。節の外に逃がせては意味がない。"""
    ((loc, body),) = doc_lint.sections(f"## {WARN} あぶない\n")[1:]
    assert loc == f"{WARN} あぶない"
    assert body.count(WARN) == 1


def test_a_repeated_heading_gets_a_suffix() -> None:
    """baseline の1行を一意にするため。同じ見出しは #2 以降に印を付ける。"""
    got = doc_lint.sections("## 予測と実測\nあ\n## 予測と実測\nい\n")
    assert [loc for loc, _ in got][1:] == ["予測と実測", "予測と実測 [2]"]


def test_symbols_inside_code_are_mentions_not_uses(tmp_path: pathlib.Path) -> None:
    """規約を書いた文書が、その規約で落ちないようにする。

    この検査を入れないと、CLAUDE.md や doc_lint.py の説明そのものが引っかかる。
    """
    body = f"`{WARN}` は1節1個まで。`{WARN}` を2度書いても、`{KEY}` を出しても数えない。"
    write(tmp_path, "docs/a.md", f"## 規約\n{body}\n")
    assert list(doc_lint.inspect(tmp_path / "docs/a.md", tmp_path)) == []
    assert doc_lint.sections(f"## 規約\n{body}\n")[1][1].count(WARN) == 0


def test_a_longer_fence_can_contain_a_shorter_one(tmp_path: pathlib.Path) -> None:
    """```` の中の ``` はフェンスを閉じない。

    ⚠️ 印の長さを見ずに出てくるたび反転させると、コードの中身を違反に数える。
    """
    body = f"## 例\n````\n```\n{WARN} {WARN} {WARN}\n```\n````\n\n## 本文\n{WARN}\n{WARN}\n"
    write(tmp_path, "docs/a.md", body)
    assert list(doc_lint.inspect(tmp_path / "docs/a.md", tmp_path)) == [
        ("D2", "docs/a.md", "本文", 2)
    ]


def test_an_unbalanced_inner_fence_does_not_silence_the_rest(tmp_path: pathlib.Path) -> None:
    """内側の印が奇数でも、以降の本文を見逃さない。

    反転で数えていたときは、ここで検査が最後まで黙っていた (違反ゼロと報告した)。
    見逃しは誤検知より悪いので、この向きを別に固定する。
    """
    body = f"## 例\n````\n```\nなかみ\n````\n\n## 本文\n{WARN}\n{WARN}\n{WARN}\n"
    write(tmp_path, "docs/a.md", body)
    assert list(doc_lint.inspect(tmp_path / "docs/a.md", tmp_path)) == [
        ("D2", "docs/a.md", "本文", 3)
    ]


def test_a_fence_only_closes_on_a_bare_line_of_the_same_kind(tmp_path: pathlib.Path) -> None:
    """情報文字列の付いた行や、別の文字の行では閉じない。"""
    write(tmp_path, "docs/a.md", f"## 例\n```\n{WARN}\n``` ruby\n{WARN}\n~~~\n{WARN}\n```\n")
    assert list(doc_lint.inspect(tmp_path / "docs/a.md", tmp_path)) == []
    # 逆に、開いた印より長い行では閉じられる
    write(tmp_path, "docs/b.md", f"## 例\n```\n{WARN}\n`````\n\n## 本文\n{WARN}\n{WARN}\n")
    assert list(doc_lint.inspect(tmp_path / "docs/b.md", tmp_path)) == [
        ("D2", "docs/b.md", "本文", 2)
    ]


def test_a_tilde_fence_may_hold_backticks(tmp_path: pathlib.Path) -> None:
    write(tmp_path, "docs/a.md", f"## 例\n~~~markdown\n```\n{WARN} {WARN}\n```\n~~~\n")
    assert list(doc_lint.inspect(tmp_path / "docs/a.md", tmp_path)) == []


def test_backticks_in_a_backtick_info_string_are_not_a_fence(tmp_path: pathlib.Path) -> None:
    """``` のあとにバッククォートが来る行はフェンスではない (Markdown の規則)。"""
    write(tmp_path, "docs/a.md", f"## 例\n``` `x`\n{WARN}\n{WARN}\n")
    assert list(doc_lint.inspect(tmp_path / "docs/a.md", tmp_path)) == [
        ("D2", "docs/a.md", "例", 2)
    ]


@pytest.mark.parametrize("ticks", ["`", "``", "```"])
def test_inline_code_closes_with_the_same_number_of_backticks(
    tmp_path: pathlib.Path, ticks: str
) -> None:
    """``⚠️`` を1文字ずつ見ると「空のコード + 記号 + 空のコード」になり、記号が残る。"""
    write(tmp_path, "docs/a.md", f"## 規約\n{ticks}{WARN}{ticks} と {ticks}{KEY}{ticks}\n")
    assert list(doc_lint.inspect(tmp_path / "docs/a.md", tmp_path)) == []


def test_a_longer_run_of_backticks_cannot_close_a_shorter_one(
    tmp_path: pathlib.Path,
) -> None:
    """`a`` x ` は「1本で開いて1本の塊で閉じる」1つのコード。

    塊の途中を閉じ記号に使えてしまうと、2本の塊の2本目で閉じたことになり、
    残りが本文に漏れる。前後を (?<!`) (?!`) で挟んでそれを止めている。
    """
    write(tmp_path, "docs/a.md", f"## 例\n説明 `a`` {KEY} b`\n")
    assert list(doc_lint.inspect(tmp_path / "docs/a.md", tmp_path)) == []


def test_an_unclosed_backtick_is_not_code(tmp_path: pathlib.Path) -> None:
    """閉じていないバッククォートはコードにしない (記号は本文として数える)。"""
    write(tmp_path, "docs/a.md", f"## 例\n`閉じていない {KEY}\n")
    assert list(doc_lint.inspect(tmp_path / "docs/a.md", tmp_path)) == [
        ("D3", "docs/a.md", "例", 1)
    ]


def test_fenced_blocks_are_ignored(tmp_path: pathlib.Path) -> None:
    write(tmp_path, "docs/a.md", f"## 例\n```\n{WARN} {WARN} {WARN}\n{KEY}\n```\n")
    assert list(doc_lint.inspect(tmp_path / "docs/a.md", tmp_path)) == []


def test_d2_allows_one_warning_per_section_and_flags_two(tmp_path: pathlib.Path) -> None:
    write(tmp_path, "docs/a.md", f"## あ\n{WARN} ひとつ\n")
    assert list(doc_lint.inspect(tmp_path / "docs/a.md", tmp_path)) == []
    write(tmp_path, "docs/b.md", f"## あ\n{WARN} ひとつ\n\n{WARN} ふたつ\n")
    assert list(doc_lint.inspect(tmp_path / "docs/b.md", tmp_path)) == [
        ("D2", "docs/b.md", "あ", 2)
    ]


def test_d2_counts_per_section_not_per_file(tmp_path: pathlib.Path) -> None:
    """総数で縛ると長いファイルほど薄まって通ってしまう。"""
    write(tmp_path, "docs/a.md", f"## あ\n{WARN}\n\n## い\n{WARN}\n\n## う\n{WARN}\n")
    assert list(doc_lint.inspect(tmp_path / "docs/a.md", tmp_path)) == []


def test_d3_forbids_the_key_symbol_outright(tmp_path: pathlib.Path) -> None:
    write(tmp_path, "docs/a.md", f"## あ\n{KEY} ひとつでも駄目\n")
    assert list(doc_lint.inspect(tmp_path / "docs/a.md", tmp_path)) == [
        ("D3", "docs/a.md", "あ", 1)
    ]


@pytest.mark.parametrize(
    ("rel", "n_lines", "flagged"),
    [
        ("README.md", 400, False),
        ("README.md", 401, True),
        ("docs/a.md", 300, False),
        ("docs/a.md", 301, True),
    ],
)
def test_d1_line_limits(tmp_path: pathlib.Path, rel: str, n_lines: int, flagged: bool) -> None:
    """README だけ上限が緩い (入口なので情報が集まる)。"""
    write(tmp_path, rel, "あ\n" * n_lines)
    got = [v for v in doc_lint.inspect(tmp_path / rel, tmp_path) if v[0] == "D1"]
    assert bool(got) is flagged
    if flagged:
        assert got[0][3] == n_lines


def test_documents_covers_the_right_places_and_skips_the_frozen_ones(
    tmp_path: pathlib.Path,
) -> None:
    for rel in (
        "README.md",
        "CLAUDE.md",
        "docs/records/01-a.md",
        "experiments/e/README.md",
        "results/00/README.md",
        "impl/01/README.md",
        "baseline/README.md",
    ):
        write(tmp_path, rel, "あ\n")
    got = [p.relative_to(tmp_path).as_posix() for p in doc_lint.documents(tmp_path)]
    assert got == ["README.md", "CLAUDE.md", "docs/records/01-a.md", "experiments/e/README.md"]


def test_a_missing_always_file_is_skipped(tmp_path: pathlib.Path) -> None:
    write(tmp_path, "README.md", "あ\n")
    assert [p.name for p in doc_lint.documents(tmp_path)] == ["README.md"]


def test_the_baseline_round_trips(tmp_path: pathlib.Path) -> None:
    found = [("D2", "docs/a.md", "あ", 3), ("D3", "docs/a.md", "い", 1)]
    path = tmp_path / "baseline.txt"
    path.write_text(doc_lint.dump(found), encoding="utf-8")
    assert doc_lint.load(path) == {
        ("D2", "docs/a.md", "あ"): 3,
        ("D3", "docs/a.md", "い"): 1,
    }


def test_load_returns_nothing_when_there_is_no_baseline(tmp_path: pathlib.Path) -> None:
    assert doc_lint.load(tmp_path / "無い.txt") == {}


def test_compare_forgives_the_known_and_flags_the_new_and_the_worse() -> None:
    known = {("D2", "a.md", "あ"): 3, ("D2", "a.md", "い"): 2}
    bad, info = doc_lint.compare([("D2", "a.md", "あ", 3), ("D2", "a.md", "う", 2)], known)
    assert [line.split()[1] for line in bad] == ["新規"]
    assert "う" in bad[0]
    assert info and "い" in info[0]

    bad, _ = doc_lint.compare([("D2", "a.md", "あ", 4)], known)
    assert "増えた" in bad[0] and "3 → 4" in bad[0]


def test_compare_does_not_flag_an_improvement() -> None:
    bad, _ = doc_lint.compare([("D2", "a.md", "あ", 1)], {("D2", "a.md", "あ"): 3})
    assert bad == []


def test_main_updates_then_passes_then_fails(tmp_path: pathlib.Path) -> None:
    """既存の債務を固定 → 通る → 1個増やすと落ちる。"""
    write(tmp_path, "docs/a.md", f"## あ\n{WARN}\n{WARN}\n{KEY}\n")
    baseline = tmp_path / "baseline.txt"
    argv = ["--root", str(tmp_path), "--baseline", str(baseline)]
    assert doc_lint.main([*argv, "--update-baseline"]) == 0
    assert doc_lint.main(argv) == 0

    write(tmp_path, "docs/b.md", f"## い\n{WARN}\n{WARN}\n")
    assert doc_lint.main(argv) == 1


def test_main_reports_what_left_the_baseline(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(doc_lint.dump([("D2", "docs/a.md", "あ", 3)]), encoding="utf-8")
    write(tmp_path, "docs/a.md", f"## あ\n{WARN}\n")
    assert doc_lint.main(["--root", str(tmp_path), "--baseline", str(baseline)]) == 0
    assert "解消" in capsys.readouterr().out


def test_the_repository_has_no_new_violations() -> None:
    """実物。make check がこれを回す。"""
    bad, _ = doc_lint.compare(doc_lint.collect(doc_lint.ROOT), doc_lint.load(doc_lint.BASELINE))
    assert bad == [], "doc_lint_baseline.txt を締め直すか、違反を直すこと"
