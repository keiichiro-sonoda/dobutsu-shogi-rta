"""tools/prereg_check.py: 事前登録の節を、回したあとで読み直す道具。

実験 unmove_bench で、見込みが「一致の検査で見たあとの数」(候補が平均 9.8 個) を根拠に
使っていたのを、レビューが時刻の順だけを見て通した。同じ形を小さな git リポジトリで作り、
鳴ること (R1〜R3) と、鳴らないこと (出どころを名指しした数・前から知っていた数) を固定する。
"""

from __future__ import annotations

import functools
import os
import pathlib
import subprocess
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import prereg_check

PRED = "## 見込み（計時の前に書いた）"
RULE = "## 止める条件（回す前に決めた）"


# ---- 本文の読み方 -----------------------------------------------------------


def test_only_registered_h2_sections_are_read() -> None:
    text = "\n".join(
        [
            "# 実験",
            "## 腕",
            "a",
            PRED,
            "見込みの行",
            "### 小見出しは節の中",
            "```",
            "## フェンスの中は見出しではない",
            "```",
            "## 結果（回したあとで書いた）",
            "結果の行",
            RULE,
            "条件の行",
        ]
    )
    got = prereg_check.sections(text)
    assert list(got) == [PRED, RULE]
    assert got[PRED] == [
        "見込みの行",
        "### 小見出しは節の中",
        "```",
        "## フェンスの中は見出しではない",
        "```",
    ]
    assert got[RULE] == ["条件の行"]


def test_line_changes_tell_a_note_from_a_rewrite() -> None:
    old = ["残す", "注記を足す行。", "書き換える 1〜2", "消す行", "最後"]
    new = ["残す", "注記を足す行（※ あとで足した）。", "書き換える 3〜4", "最後", "足した行"]
    got = list(prereg_check.line_changes(old, new))
    assert ("note", "注記を足す行。", "注記を足す行（※ あとで足した）。") in got
    assert ("changed", "書き換える 1〜2", "書き換える 3〜4") in got
    assert ("removed", "消す行", "") in got
    assert all(before != "足した行" and after != "足した行" for _, before, after in got)


def test_a_bare_reference_mark_is_a_note_too() -> None:
    assert list(prereg_check.line_changes(["重い。"], ["重い※。"])) == [
        ("note", "重い。", "重い※。")
    ]


def test_numbers_read_commas_and_decimals() -> None:
    got = list(prereg_check.numbers("候補 2,412,035,001 個、平均 9.8 個、938671869 本"))
    assert got == [
        ("2,412,035,001", Decimal("2412035001")),
        ("9.8", Decimal("9.8")),
        ("938671869", Decimal("938671869")),
    ]


@pytest.mark.parametrize(
    ("word", "want"),
    [("9.8", True), ("0.5", False), ("1.5", True), ("16", False), ("4,096", True), ("0.0", False)],
)
def test_noisy_numbers_are_not_checked(word: str, want: bool) -> None:
    assert prereg_check.worth_checking(word, Decimal(word.replace(",", ""))) is want


@pytest.mark.parametrize(
    ("pred", "log", "want"),
    [("9.8", "9.773", True), ("9.9", "9.85", True), ("9.8", "9.85", False), ("4096", "4096", True)],
)
def test_numbers_are_compared_at_the_prediction_s_precision(
    pred: str, log: str, want: bool
) -> None:
    assert prereg_check.same_number(pred, Decimal(pred), Decimal(log)) is want


def test_a_line_that_names_its_source_is_prior_knowledge() -> None:
    assert prereg_check.cites_elsewhere("F1 は gate_18_opt の −3.75 と同程度", "lever_scan")
    assert prereg_check.cites_elsewhere("#28 の 3.75", "x")
    assert not prereg_check.cites_elsewhere("候補が平均 9.8 個", "unmove_bench")
    assert not prereg_check.cites_elsewhere("unmove_bench の 9.8", "unmove_bench")


def test_seen_numbers_skip_cited_lines_and_coarser_logs() -> None:
    prediction = "候補が平均 9.8 個\ngate_18_opt の 3.75 と同程度\n残りは 3.80 本"
    logs = {"e/logs/v.txt": "9.773 3.747 3.8\n9.773"}
    got = list(prereg_check.seen_numbers(prediction, logs, "e"))
    # 9.8 は 9.773 と同じ (重ねて出さない)。3.75 は出どころを名指し。3.80 にはログの 3.8 が粗すぎる
    assert got == [("9.8", "e/logs/v.txt", 1, "9.773")]


def test_naming_one_source_drops_every_number_on_that_line() -> None:
    """限界を固定する: 名指しは行単位なので、同じ行の見たあとの数も外れる。"""
    logs = {"e/logs/v.txt": "9.773"}
    assert list(prereg_check.seen_numbers("#33 と同じ形で、候補が平均 9.8 個", logs, "e")) == []
    assert list(prereg_check.seen_numbers("候補が平均 9.8 個", logs, "e")) != []


def test_a_number_derived_from_prior_numbers_still_rings() -> None:
    """限界を固定する: 割り算は見ないので、前から知っていた2つの数の比 (3.803) でも鳴る。"""
    logs = {"e/logs/v.txt": "前任 3.803 本 / 局面"}
    assert [w for w, *_ in prereg_check.seen_numbers("残った前任 (平均 3.8)", logs, "e")] == ["3.8"]


def test_run_starts_read_only_the_start_lines() -> None:
    text = "\n".join(
        [
            "=== 開始 r1a_old 2026-10-05T03:04:33+00:00 ===",
            "=== 終了 r1a_old 2026-10-05T03:06:00+00:00 ===",
            "=== 計時 開始 2026-10-05T03:00:00Z ===",
            "開始 (時刻なし)",
        ]
    )
    got = [t.isoformat() for t in prereg_check.run_starts(text)]
    assert got == ["2026-10-05T03:04:33+00:00", "2026-10-05T03:00:00+00:00"]


# ---- git をまたぐところ -------------------------------------------------------


def commit(repo: pathlib.Path, files: dict[str, str], when: str, message: str) -> None:
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(["git", "add", *files], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True, env=env)


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """unmove_bench と同じ形: 見込みと、見たあとのログを同じコミットに入れる。"""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    # 検体を実行時に組み立てる (ソースにメールアドレスの形を置くと publish_lint が鳴る)
    email = "t" + "@" + "example.invalid"
    subprocess.run(["git", "config", "user.email", email], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    commit(
        tmp_path, {"docs/x.md": "辺の総数 938671869 本\n"}, "2026-10-01T00:00:00+00:00", "前から"
    )
    readme = "\n".join(
        [
            "# 実験 e",
            PRED,
            "| `cand` | 150〜400 | 候補が平均 9.8 個 |",
            "辺は 938,671,869 本 (前から知っていた)",
            "gate_18_opt の 3.75 と同程度",
            "消す行",
            RULE,
            "区間の上端が 0 以上なら止める",
            "## 結果（回したあとで書いた）",
            "（あとで書く）",
            "",
        ]
    )
    clean = "\n".join(
        ["# 実験 c", "## 予測（回す前に書いた）", "下がる。区間が 0 をまたがない", ""]
    )
    commit(
        tmp_path,
        {
            "experiments/e/README.md": readme,
            "experiments/e/logs/verify.txt": "候補 9.773 / 辺 938671869 / 3.747\n",
            "experiments/c/README.md": clean,
            "experiments/n/README.md": "# 登録した節の無い実験\n## 結果\nx\n",
        },
        "2026-10-05T03:00:00+00:00",
        "登録",
    )
    later = (
        readme.replace("候補が平均 9.8 個 |", "候補が平均 9.8 個 ※ |")
        .replace("消す行\n", "")
        .replace("0 以上なら止める", "0.2 以上なら止める")
    )
    commit(
        tmp_path,
        {
            "experiments/e/README.md": later.replace("（あとで書く）", "重い側に外れた"),
            "experiments/e/logs/console.log": "=== 計時 開始 2026-10-05T02:50:00+00:00 ===\n",
            "experiments/c/logs/console.log": "=== 計時 開始 2026-10-05T03:10:00+00:00 ===\n",
        },
        "2026-10-05T03:20:00+00:00",
        "結果",
    )
    return tmp_path


def git_in(repo: pathlib.Path) -> prereg_check.Git:
    return functools.partial(prereg_check.run_git, cwd=repo)


def test_the_unmove_bench_shape_is_caught(repo: pathlib.Path) -> None:
    found = prereg_check.check_experiment(git_in(repo), "experiments/e")
    by_rule = {f.rule: [x.message for x in found if x.rule == f.rule] for f in found}
    assert sorted(by_rule) == ["R0", "R1", "R2", "R3"]
    # 見たあとの 9.8 だけが出る。前から知っていた 938,671,869 と、出どころを名指しした 3.75 は出ない
    assert len(by_rule["R2"]) == 1 and "9.8" in by_rule["R2"][0] and "9.773" in by_rule["R2"][0]
    assert any("消した: 消す行" in m for m in by_rule["R1"])
    # 止める条件の節も見る (数の照合は予測の節だけ)
    assert any("書き換えた: 区間の上端が 0 以上なら止める" in m for m in by_rule["R1"])
    assert any("※" in m for m in by_rule["R0"])
    # 時刻のある本は時刻で、時刻の無いログ (一致の検査の verify.txt) は
    # 登録の時点で logs/ に既にあったことで出る
    assert any("02:50:00" in m for m in by_rule["R3"])
    assert any("既にあった: verify.txt" in m for m in by_rule["R3"])


def test_logs_added_before_the_registering_commit_also_ring(tmp_path: pathlib.Path) -> None:
    """R3 は「登録の時点で logs/ にあったか」を見る。同じコミットで足したものに限らない。"""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    email = "t" + "@" + "example.invalid"
    subprocess.run(["git", "config", "user.email", email], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    commit(tmp_path, {"experiments/e/logs/v.txt": "結果\n"}, "2026-10-05T01:00:00+00:00", "ログ")
    readme = "# e\n## 予測（回す前に書いた）\n下がる\n"
    commit(tmp_path, {"experiments/e/README.md": readme}, "2026-10-05T02:00:00+00:00", "予測")
    found = prereg_check.check_experiment(git_in(tmp_path), "experiments/e")
    assert [f.rule for f in found] == ["R3"]
    assert "既にあった: v.txt" in found[0].message


def test_a_clean_experiment_is_quiet(repo: pathlib.Path) -> None:
    assert prereg_check.check_experiment(git_in(repo), "experiments/c") == []


def test_an_experiment_without_registered_sections_is_quiet(repo: pathlib.Path) -> None:
    assert prereg_check.check_experiment(git_in(repo), "experiments/n") == []


def test_main_looks_at_the_experiments_changed_since_the_base(
    repo: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = prereg_check.run_git(["rev-list", "--max-parents=0", "HEAD"], cwd=repo).strip()
    assert prereg_check.main(["--base", base], git=git_in(repo)) == 1
    out = capsys.readouterr().out
    assert "experiments/c: 登録した節に指摘なし" in out
    assert "R2" in out


def test_main_names_an_experiment_and_reports_a_clean_one(
    repo: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert prereg_check.main(["experiments/c/"], git=git_in(repo)) == 0
    assert "指摘なし" in capsys.readouterr().out


def test_main_with_nothing_changed_says_so(
    repo: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert prereg_check.main(["--base", "HEAD"], git=git_in(repo)) == 0
    assert "変更は無い" in capsys.readouterr().out


def test_a_git_failure_is_not_a_clean_result(
    repo: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert prereg_check.main(["experiments/missing"], git=git_in(repo)) == 2
    assert "prereg_check:" in capsys.readouterr().err


def test_a_heading_without_an_adding_commit_is_an_error() -> None:
    with pytest.raises(prereg_check.GitError):
        prereg_check.registration(lambda args: "", "r/README.md", PRED)


def test_a_root_registration_has_no_prior_knowledge() -> None:
    def failing(args: list[str]) -> str:
        raise prereg_check.GitError("no parent")

    assert prereg_check.known_before(failing, "abc", "9.773", "experiments/e") is False


def test_a_report_with_only_notes_is_clean(capsys: pytest.CaptureFixture[str]) -> None:
    only_note = [prereg_check.Finding("R0", "w", "※ を足した")]
    assert prereg_check.report([("experiments/e", only_note)]) == 0
    assert "R0 w: ※ を足した" in capsys.readouterr().out
