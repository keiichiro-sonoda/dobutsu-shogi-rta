"""`tools/publish_lint.py` の検査。

⚠️ **検体を literal で書かない。** この門番は「追加行」を見るので、テストに本物の形を
そのまま書くと、このファイルを公開するときに自分自身で鳴る。実行時に組み立てれば、
ソースの上では連続した形にならないので鳴らない（`"gh" "p_..."` のように切る）。
publish_lint 側の表も同じ理由で長さを要求する形にしてある。
"""

from __future__ import annotations

import pathlib
import subprocess

import publish_lint
import pytest
from conftest import ROOT

# 検体。どれも実行時に連結する (上の ⚠️ を参照)
TOKEN = "gh" + "p_" + "a" * 36
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"
AWS = "AK" + "IA" + "B" * 16
SK = "sk" + "-" + "c" * 24
SLACK = "xo" + "xb-" + "1" * 14
AUTH = "Authorization: " + "Bearer tok"
USER_PATH = "/" + "home/alice/work"
EMAIL = "alice@" + "example.invalid"
IP = "203.0" + ".113.7"


def added(text: str, path: str = "docs/a.md", lineno: int = 1) -> list[publish_lint.Added]:
    return [(path, lineno, text)]


def rules(found: list[publish_lint.Finding]) -> list[str]:
    return [rule for rule, _, _ in found]


# --------------------------------------------------------------------------
# diff の読み取り
# --------------------------------------------------------------------------


def test_name_status_keeps_the_status_and_the_path() -> None:
    text = "A\tresults/13_x/env.txt\nM\tREADME.md\nD\ttools/old.py\n"
    assert publish_lint.parse_name_status(text) == [
        ("A", "results/13_x/env.txt"),
        ("M", "README.md"),
        ("D", "tools/old.py"),
    ]


def test_a_rename_is_reported_on_the_old_path() -> None:
    """凍結物としては「旧が消える」ほうが問題。新しい側は追加として通す。"""
    text = "R100\tresults/13_x/env.txt\tresults/13_y/env.txt\n"
    assert publish_lint.parse_name_status(text) == [
        ("R", "results/13_x/env.txt"),
        ("A", "results/13_y/env.txt"),
    ]


def test_blank_and_malformed_name_status_lines_are_skipped() -> None:
    assert publish_lint.parse_name_status("\n  \nM\n") == []


def test_added_lines_carry_the_new_side_line_numbers() -> None:
    diff = (
        "diff --git a/docs/a.md b/docs/a.md\n"
        "--- a/docs/a.md\n"
        "+++ b/docs/a.md\n"
        "@@ -0,0 +7,2 @@\n"
        "+ひとつめ\n"
        "+ふたつめ\n"
        "-消えた行は見ない\n"
    )
    assert publish_lint.parse_added_lines(diff) == [
        ("docs/a.md", 7, "ひとつめ"),
        ("docs/a.md", 8, "ふたつめ"),
    ]


def test_a_deleted_file_has_no_added_lines() -> None:
    """`+++ /dev/null` のあとの行を前のファイルのものにしない。"""
    diff = "--- a/gone.md\n+++ /dev/null\n@@ -1 +0,0 @@\n-なかみ\n"
    assert publish_lint.parse_added_lines(diff) == []


def test_a_malformed_hunk_header_resets_the_line_number() -> None:
    diff = "+++ b/a.md\n@@ こわれた @@\n+なかみ\n"
    assert publish_lint.parse_added_lines(diff) == [("a.md", 0, "なかみ")]


# --------------------------------------------------------------------------
# P1 鍵・トークン
# --------------------------------------------------------------------------


@pytest.mark.parametrize("sample", [TOKEN, PEM, AWS, SK, SLACK, AUTH, "github_pat_" + "d" * 30])
def test_a_secret_is_caught(sample: str) -> None:
    assert rules(list(publish_lint.secret_findings(added(f"key = {sample}")))) == ["P1"]


def test_a_sha256_in_the_evidence_is_not_a_secret() -> None:
    """`env.txt` の `impl_sha256` は毎回入る。ここで鳴ったら門番が使い物にならない。"""
    line = "impl_sha256: 1efe2123663c839775fa288a2d3f85a2cc1a0d3c2f8a4e7b296f4aebd987ce9a"
    assert list(publish_lint.secret_findings(added(line, "results/13_x/env.txt"))) == []


# --------------------------------------------------------------------------
# P2 同定情報
# --------------------------------------------------------------------------


@pytest.mark.parametrize("sample", [USER_PATH, EMAIL, IP])
def test_identity_information_is_caught(sample: str) -> None:
    assert rules(list(publish_lint.identity_findings(added(f"走らせた: {sample}")))) == ["P2"]


def test_a_version_string_in_a_lock_file_is_not_an_ip() -> None:
    """`uv.lock` は生成物で中身を選べない。4連の版番号が IP と同じ形になる。"""
    line = 'version = "' + "0.11" + '.0.1"'  # 検体なので連結する
    assert list(publish_lint.identity_findings(added(line, "uv.lock"))) == []
    assert rules(list(publish_lint.identity_findings(added(line, "tools/x.py")))) == ["P2"]


def test_collecting_the_hostname_is_caught_in_shell_scripts_only() -> None:
    """Python 側には「ホスト名は記録しない」と書いた行がありうるので当てない。"""
    line = 'echo "host: $(hostname)" >> env.txt'
    assert rules(list(publish_lint.identity_findings(added(line, "tools/run.sh")))) == ["P2"]
    assert list(publish_lint.identity_findings(added(line, "tests/test_x.py"))) == []


def test_a_hostname_written_into_the_evidence_is_caught() -> None:
    found = list(publish_lint.identity_findings(added("host: kaisekiki", "results/13_x/env.txt")))
    assert rules(found) == ["P2"]


def test_an_ordinary_line_is_quiet() -> None:
    line = "全探索 972.74 -> 695.62 (-277.12)"
    assert list(publish_lint.identity_findings(added(line))) == []
    assert list(publish_lint.secret_findings(added(line))) == []


# --------------------------------------------------------------------------
# P3 凍結物
# --------------------------------------------------------------------------


@pytest.fixture
def recorded() -> set[str]:
    return {"baseline/", "impl/13_c_expand/"}


@pytest.mark.parametrize(
    ("status", "path"),
    [
        ("M", "results/12_c_predecessors/env.txt"),
        ("D", "oracle/distribution.tsv"),
        ("M", "baseline/animal_shogi.py"),
        ("M", "impl/13_c_expand/animal_shogi.c"),
        ("R", "results/12_c_predecessors/time.txt"),
    ],
)
def test_touching_something_frozen_is_caught(status: str, path: str, recorded: set[str]) -> None:
    assert rules(list(publish_lint.frozen_findings([(status, path)], recorded))) == ["P3"]


def test_adding_a_new_record_is_allowed(recorded: set[str]) -> None:
    """記録は results/ に「足す」もの。追加まで止めたら何も公開できない。"""
    changes = [("A", "results/14_x/env.txt"), ("A", "impl/14_x/animal_shogi.c")]
    assert list(publish_lint.frozen_findings(changes, recorded)) == []


def test_editing_an_implementation_without_a_record_is_allowed(recorded: set[str]) -> None:
    """まだ記録を取っていない実装は凍結されていない。"""
    assert list(publish_lint.frozen_findings([("M", "impl/14_draft/x.c")], recorded)) == []


def test_an_unknown_status_is_still_reported(recorded: set[str]) -> None:
    found = list(publish_lint.frozen_findings([("T", "oracle/x.tsv")], recorded))
    assert found and "種別変更" in found[0][2]


def test_recorded_implementations_come_from_the_evidence(tmp_path: pathlib.Path) -> None:
    write(tmp_path, "results/00_baseline/env.txt", "label: baseline\n")
    write(tmp_path, "results/13_c_expand/env.txt", "impl: 13_c_expand\ngit_commit: abc\n")
    write(tmp_path, "results/99_broken/env.txt", "git_commit: abc\n")
    assert publish_lint.recorded_impls(tmp_path) == {"baseline/", "impl/13_c_expand/"}


# --------------------------------------------------------------------------
# P4 記録の証拠
# --------------------------------------------------------------------------


def write(root: pathlib.Path, rel: str, text: str) -> pathlib.Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_record(root: pathlib.Path, *, elapsed: str = "24:27.10", listed: str = "0:24:27") -> None:
    write(root, "results/13_x/env.txt", "impl_sha256: abc\ngit_commit: def\nimpl: 13_x\n")
    write(root, "results/13_x/verify.txt", "PASS: 174 行すべて一致\n")
    write(
        root,
        "results/13_x/time.txt",
        f"\tElapsed (wall clock) time (h:mm:ss or m:ss): {elapsed}\n",
    )
    write(root, "README.md", f"| 13 | `impl/13_x/` | 1スレッド | **{listed}** | **21.90×** |\n")


def test_a_complete_record_is_quiet(tmp_path: pathlib.Path) -> None:
    make_record(tmp_path)
    assert list(publish_lint.evidence_findings(tmp_path, ["results/13_x/"])) == []


def test_missing_evidence_is_caught(tmp_path: pathlib.Path) -> None:
    make_record(tmp_path)
    (tmp_path / "results/13_x/verify.txt").unlink()
    found = list(publish_lint.evidence_findings(tmp_path, ["results/13_x/"]))
    assert rules(found) == ["P4"] and "verify.txt" in found[0][2]


def test_a_missing_env_field_is_caught(tmp_path: pathlib.Path) -> None:
    make_record(tmp_path)
    write(tmp_path, "results/13_x/env.txt", "impl: 13_x\n")
    found = list(publish_lint.evidence_findings(tmp_path, ["results/13_x/"]))
    assert [what for _, _, what in found] == [
        "git_commit が無い",
        "impl を指しているのに impl_sha256 が無い",
    ]


def test_the_baseline_record_does_not_need_an_impl_hash(tmp_path: pathlib.Path) -> None:
    """記録 #0 は `tools/run.sh` が `impl_sha256` を持つ前の記録。

    ⚠️ `results/` は凍結なのであとから足せない。実装を指していない記録に
    その項目を要求すると、この門番は初日から嘘の指摘を出し続けることになる。
    """
    make_record(tmp_path)
    write(tmp_path, "results/13_x/env.txt", "label: baseline\ngit_commit: d5001f5\n")
    assert list(publish_lint.evidence_findings(tmp_path, ["results/13_x/"])) == []


def test_a_failed_oracle_check_is_caught(tmp_path: pathlib.Path) -> None:
    make_record(tmp_path)
    write(tmp_path, "results/13_x/verify.txt", "FAIL: 3 行が違う\n")
    found = list(publish_lint.evidence_findings(tmp_path, ["results/13_x/"]))
    assert rules(found) == ["P4"] and "PASS" in found[0][2]


def test_a_time_that_disagrees_with_the_table_is_caught(tmp_path: pathlib.Path) -> None:
    """同じ数字を2か所に持っているので、片方だけ直すと食い違う。"""
    make_record(tmp_path, listed="0:24:28")
    found = list(publish_lint.evidence_findings(tmp_path, ["results/13_x/"]))
    assert rules(found) == ["P4"] and "1468 秒" in found[0][2]


def test_a_record_missing_from_the_table_is_caught(tmp_path: pathlib.Path) -> None:
    make_record(tmp_path)
    write(tmp_path, "README.md", "記録表がまだ無い\n")
    found = list(publish_lint.evidence_findings(tmp_path, ["results/13_x/"]))
    assert rules(found) == ["P4"] and "記録 #13" in found[0][2]


def test_an_unreadable_time_file_is_caught(tmp_path: pathlib.Path) -> None:
    make_record(tmp_path)
    write(tmp_path, "results/13_x/time.txt", "途中で落ちた\n")
    found = list(publish_lint.evidence_findings(tmp_path, ["results/13_x/"]))
    assert rules(found) == ["P4"] and "Elapsed" in found[0][2]


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("8:55:31", 32131),
        ("24:27.10", 1467),  # 秒未満は切り捨て (記録表と同じ)
        ("35:25.94", 2125),
        ("1", None),
        ("1:2:3:4", None),
        ("あ:い", None),
    ],
)
def test_to_seconds(text: str, want: int | None) -> None:
    assert publish_lint.to_seconds(text) == want


def test_the_table_keeps_the_first_row_for_a_number() -> None:
    """番号の重複は tests/test_docs_links.py が落とす。ここでは前の行を採る。"""
    readme = (
        "| 0 | `baseline/` (2021-11) | 1スレッド | **8:55:31** | 1.00× |\n"
        "| 13 | `impl/13_x/` | 1スレッド | **0:24:27** | **21.90×** |\n"
        "| 13 | `impl/13_x/` | 1スレッド | **9:99:99** | **21.90×** |\n"
        "| 14 | `impl/14_x/` | 1スレッド | **こわれた** | |\n"
        "本文は拾わない\n"
    )
    assert publish_lint.record_times(readme) == {0: 32131, 13: 1467}


def test_new_result_dirs_are_listed_once() -> None:
    changes = [
        ("A", "results/13_x/env.txt"),
        ("A", "results/13_x/time.txt"),
        ("M", "results/12_y/env.txt"),
        ("A", "docs/records/13-x.md"),
    ]
    assert publish_lint.new_result_dirs(changes) == ["results/13_x/"]


# --------------------------------------------------------------------------
# P5 コミットメッセージ
# --------------------------------------------------------------------------


def test_a_session_pointer_in_a_commit_message_is_caught() -> None:
    body = "記録 #13\n\nClaude-Session: https://example.invalid/x\n"
    assert rules(list(publish_lint.session_findings([("abc1234", body)]))) == ["P5"]


def test_a_co_authored_by_line_is_allowed() -> None:
    body = "記録 #13\n\nCo-Authored-By: Claude <noreply@" + "anthropic.example>\n"
    assert list(publish_lint.session_findings([("abc1234", body)])) == []


def test_commit_messages_are_split_on_nul() -> None:
    text = "aaaaaaabbb\n本文1\n\0cccccccddd\n本文2\n\0\n"
    assert publish_lint.commit_messages(text) == [
        ("aaaaaaa", "本文1"),
        ("ccccccc", "本文2"),
    ]


# --------------------------------------------------------------------------
# 本物の git を通す
# --------------------------------------------------------------------------

# ⚠️ literal のメールを書かない (自分の P2 に引っかかる)
GIT_EMAIL = "t@" + "example.invalid"


def git(root: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """base コミットを1本持つだけのリポジトリ。"""
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.name", "t")
    git(tmp_path, "config", "user.email", GIT_EMAIL)
    write(tmp_path, "README.md", "# 記録\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "branch", "base")
    return tmp_path


def test_main_passes_on_a_harmless_commit(
    repo: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "docs/a.md", "ふつうの文書\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "文書を足す")
    assert publish_lint.main(["--root", str(repo), "--base", "base"]) == 0
    assert "取り消せない指摘なし" in capsys.readouterr().out


def test_main_stops_on_a_secret(repo: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, "deploy.md", f"token = {TOKEN}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "鍵を貼ってしまった")
    assert publish_lint.main(["--root", str(repo), "--base", "base"]) == 1
    out = capsys.readouterr().out
    assert "P1" in out and "point of no return" in out


def test_main_reports_a_missing_base(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert publish_lint.main(["--root", str(tmp_path), "--base", "origin/main"]) == 2
    assert "git fetch" in capsys.readouterr().out


def test_collect_counts_what_it_looked_at(repo: pathlib.Path) -> None:
    write(repo, "docs/a.md", "ふつうの文書\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "文書を足す")
    found, n_commits, n_files = publish_lint.collect(repo, "base")
    assert (found, n_commits, n_files) == ([], 1, 1)


# --------------------------------------------------------------------------
# 実物
# --------------------------------------------------------------------------


def test_every_recorded_run_agrees_with_the_record_table() -> None:
    """実物。記録表・`time.txt`・`verify.txt` は同じ記録を3か所から書いている。

    ⚠️ 公開したあとで食い違いが見つかっても、記録は凍結物なので訂正を足すことしか
    できない。`make check` で毎回見る。
    """
    dirs = sorted(
        f"{p.parent.relative_to(ROOT).as_posix()}/" for p in ROOT.glob("results/*/env.txt")
    )
    assert dirs, "results/ に記録が1つも無い"
    assert list(publish_lint.evidence_findings(ROOT, dirs)) == []
