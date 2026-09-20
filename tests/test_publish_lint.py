"""`tools/publish_lint.py` の検査。

⚠️ **検体を literal で書かない。** この門番は追加行とコミットメッセージを見るので、
テストに本物の形をそのまま書くと、このファイルを公開するときに自分自身で鳴る。
実行時に組み立てれば、ソースの上では連続した形にならないので鳴らない。
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
VERSION = "0.11" + ".0.1"
PASSWORD = "password = " + '"Tr0ub4dor&3xKcd"'
APIKEY = "api_key: " + "8f3b91c4d05e47aa"
URL_CRED = "http://admin:" + "PASS@host:5984/vault"


def added(text: str, path: str = "docs/a.md", lineno: int = 1) -> list[publish_lint.Added]:
    return [(path, lineno, text)]


def rules(found: list[publish_lint.Finding]) -> list[str]:
    return [rule for rule, _, _ in found]


def write(root: pathlib.Path, rel: str, text: str) -> pathlib.Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def fs_view(root: pathlib.Path) -> tuple[list[str], publish_lint.Reader]:
    """作業ディレクトリを「公開される側」の代わりに見せる (HEAD 読みの単体用)。"""
    files = [p.relative_to(root).as_posix() for p in sorted(root.rglob("*")) if p.is_file()]
    return files, lambda rel: (root / rel).read_text(encoding="utf-8")


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


def test_a_coloured_diff_is_an_error_not_an_empty_result() -> None:
    """3重の最後。色を止め損ねても、黙って合格にせず落ちる。"""
    diff = "+++ b/a.md\n@@ -0,0 +1 @@\n\x1b[32m+なかみ\x1b[m\n"
    with pytest.raises(publish_lint.GitError, match="色"):
        publish_lint.parse_added_lines(diff)


def test_a_combined_diff_counts_only_lines_added_against_every_parent() -> None:
    """マージは `--cc` で見る。片方の親から来た行は、その親の側で既に履歴にある。

    ⚠️ ここを緩めると、`main` を取り込んだだけで base 側の公開済みの内容が
    新規として鳴る。逆に締めすぎると、解決のときに書いた行を見逃す。
    """
    diff = (
        "+++ b/a.md\n@@@ -1,1 -1,1 +1,3 @@@\n +main から来た\n++マージで書いた\n- 片方から消えた\n"
    )
    assert publish_lint.parse_added_lines(diff) == [("a.md", 2, "マージで書いた")]


# --------------------------------------------------------------------------
# P1 鍵・トークン
# --------------------------------------------------------------------------


@pytest.mark.parametrize("sample", [TOKEN, PEM, AWS, SK, SLACK, AUTH, "github_pat_" + "d" * 30])
def test_a_secret_is_caught(sample: str) -> None:
    assert rules(list(publish_lint.secret_findings(added(f"key = {sample}")))) == ["P1"]


def test_a_finding_says_which_commit_it_came_from() -> None:
    found = list(publish_lint.secret_findings(added(f"key = {TOKEN}"), "abc1234 "))
    assert found[0][1] == "abc1234 docs/a.md:1"


@pytest.mark.parametrize(
    ("line", "want"),
    [
        (PASSWORD, "秘密らしき代入"),
        (APIKEY, "秘密らしき代入"),
        (URL_CRED, "認証情報つきの URL"),
    ],
)
def test_a_secret_that_is_not_a_known_token_shape_is_caught(line: str, want: str) -> None:
    assert [what for _, _, what in publish_lint.secret_findings(added(line))] == [want]


def test_a_url_with_credentials_is_not_called_an_email_address() -> None:
    """`user:pass@host` は P1 が名指しする。メールとして鳴ると理由が嘘になるうえ、
    `@` のあとがホスト名でなければ落ちる。"""
    assert list(publish_lint.identity_findings(added(URL_CRED))) == []


@pytest.mark.parametrize("line", ["token = {TOKEN}", "TOKEN = 'gh' + 'p_'", "secret: あいうえお"])
def test_talking_about_a_secret_is_not_a_secret(line: str) -> None:
    """値に英字と数字の両方を要求する。これが無いと、この検査のテスト自体が鳴る。"""
    assert list(publish_lint.secret_findings(added(line))) == []


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
    line = f'version = "{VERSION}"'
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
# コミットメッセージ (P1 / P2 / P5)
# --------------------------------------------------------------------------


def test_a_secret_in_a_commit_message_is_caught() -> None:
    """メッセージも履歴に残る。ファイルに貼った鍵と同じだけ取り消せない。"""
    found = list(publish_lint.message_findings([("abc1234", f"手順\n\ntoken = {TOKEN}\n")]))
    assert rules(found) == ["P1"] and found[0][1] == "abc1234 のメッセージ:3"


def test_a_user_path_in_a_commit_message_is_caught() -> None:
    found = list(publish_lint.message_findings([("abc1234", f"走らせた: {USER_PATH}")]))
    assert rules(found) == ["P2"]


@pytest.mark.parametrize("trailer", ["Co-Authored-By", "Signed-off-by", "Reported-by"])
def test_an_attribution_trailer_is_not_reported_as_an_email(trailer: str) -> None:
    """⚠️ Co-Authored-By は付ける約束 (CLAUDE.md)。履歴のメール 55 件は全部これ。

    Claude Code と協働したことを残す行なので、門番が鳴ってはいけない。
    """
    body = f"記録 #13\n\n{trailer}: Claude <noreply@" + "anthropic.example>\n"
    assert list(publish_lint.message_findings([("abc1234", body)])) == []


def test_an_email_in_the_body_of_a_message_is_still_caught() -> None:
    """trailer だけを通す。本文に他人のアドレスを引用する経路は残っている。"""
    body = f"ログを貼る\n\n  connect failed for {EMAIL}\n"
    assert rules(list(publish_lint.message_findings([("abc1234", body)]))) == ["P2"]


@pytest.mark.parametrize(
    "value", ["https://example.invalid/x", "1f2e3d4c-5b6a-7980-9a8b-7c6d5e4f3a2b"]
)
def test_a_session_pointer_in_a_commit_message_is_caught(value: str) -> None:
    body = f"記録 #13\n\nClaude-Session: {value}\n"
    assert rules(list(publish_lint.message_findings([("abc1234", body)]))) == ["P5"]


def test_writing_about_the_rule_is_not_a_session_pointer() -> None:
    """⚠️ 使用と言及を分ける。規約を説明した行まで鳴ると、門番のことを書けない。

    実際この修正のコミットメッセージで鳴った (doc_lint の「言及」と同じ問題が、
    今度はコミットメッセージ側で出た)。
    """
    body = "取り決め\n\nClaude-Session: の URL 行は付けない。公開リポジトリなので。\n"
    assert list(publish_lint.message_findings([("abc1234", body)])) == []


# --------------------------------------------------------------------------
# P6 中身を検査できないもの
# --------------------------------------------------------------------------


def test_a_binary_file_is_reported_as_uninspectable() -> None:
    """⚠️ `git diff` はバイナリに `+` 行を出さない。黙って通すと、この門番が
    いちばん止めたいもの (PEM 秘密鍵) が入った blob が合格する。

    `GitError` と同じ理由で、検査できなかったことを合格と区別する。
    """
    numstat = "3\t0\tdocs/a.md\n-\t-\tblob.bin\n"
    assert list(publish_lint.binary_findings(numstat, "abc1234 ")) == [
        ("P6", "abc1234 blob.bin", "バイナリなので中身を検査できない")
    ]


def test_a_text_file_is_not_reported_as_binary() -> None:
    assert list(publish_lint.binary_findings("3\t0\tdocs/a.md\n\n")) == []


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


def test_the_readme_in_results_is_not_frozen(recorded: set[str]) -> None:
    """⚠️ 凍結は記録ごとのディレクトリ。`results/README.md` は証拠の置き方の説明で、
    計装が増えるたびに更新してきた (履歴で6回)。ここで鳴ると門番が信用されなくなる。
    """
    assert list(publish_lint.frozen_findings([("M", "results/README.md")], recorded)) == []


def test_a_finding_names_the_record_directory(recorded: set[str]) -> None:
    found = list(publish_lint.frozen_findings([("M", "results/12_x/env.txt")], recorded))
    assert found[0][2] == "凍結物 (results/12_x/) の変更"


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
    files, read = fs_view(tmp_path)
    assert publish_lint.recorded_impls(files, read) == {"baseline/", "impl/13_c_expand/"}


# --------------------------------------------------------------------------
# P4 記録の証拠
# --------------------------------------------------------------------------


def make_record(root: pathlib.Path, *, elapsed: str = "24:27.10", listed: str = "0:24:27") -> None:
    write(root, "results/13_x/env.txt", "impl_sha256: abc\ngit_commit: def\nimpl: 13_x\n")
    write(root, "results/13_x/verify.txt", "PASS: 174 行すべて一致\n")
    write(
        root,
        "results/13_x/time.txt",
        f"\tElapsed (wall clock) time (h:mm:ss or m:ss): {elapsed}\n",
    )
    write(root, "README.md", f"| 13 | `impl/13_x/` | 1スレッド | **{listed}** | **21.90×** |\n")


def evidence(root: pathlib.Path) -> list[publish_lint.Finding]:
    files, read = fs_view(root)
    return list(publish_lint.evidence_findings(files, read, ["results/13_x/"]))


def test_a_complete_record_is_quiet(tmp_path: pathlib.Path) -> None:
    make_record(tmp_path)
    assert evidence(tmp_path) == []


def test_missing_evidence_is_caught(tmp_path: pathlib.Path) -> None:
    make_record(tmp_path)
    (tmp_path / "results/13_x/verify.txt").unlink()
    found = evidence(tmp_path)
    assert rules(found) == ["P4"] and "verify.txt" in found[0][2]


def test_a_missing_env_field_is_caught(tmp_path: pathlib.Path) -> None:
    make_record(tmp_path)
    write(tmp_path, "results/13_x/env.txt", "impl: 13_x\n")
    assert [what for _, _, what in evidence(tmp_path)] == [
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
    assert evidence(tmp_path) == []


def test_a_failed_oracle_check_is_caught(tmp_path: pathlib.Path) -> None:
    make_record(tmp_path)
    write(tmp_path, "results/13_x/verify.txt", "FAIL: 3 行が違う\n")
    found = evidence(tmp_path)
    assert rules(found) == ["P4"] and "PASS" in found[0][2]


def test_a_time_that_disagrees_with_the_table_is_caught(tmp_path: pathlib.Path) -> None:
    """同じ数字を2か所に持っているので、片方だけ直すと食い違う。"""
    make_record(tmp_path, listed="0:24:28")
    found = evidence(tmp_path)
    assert rules(found) == ["P4"] and "1468 秒" in found[0][2]


def test_a_record_missing_from_the_table_is_caught(tmp_path: pathlib.Path) -> None:
    make_record(tmp_path)
    write(tmp_path, "README.md", "記録表がまだ無い\n")
    found = evidence(tmp_path)
    assert rules(found) == ["P4"] and "記録 #13" in found[0][2]


def test_a_missing_readme_leaves_the_table_empty(tmp_path: pathlib.Path) -> None:
    make_record(tmp_path)
    (tmp_path / "README.md").unlink()
    found = evidence(tmp_path)
    assert rules(found) == ["P4"] and "記録 #13" in found[0][2]


def test_an_unreadable_time_file_is_caught(tmp_path: pathlib.Path) -> None:
    make_record(tmp_path)
    write(tmp_path, "results/13_x/time.txt", "途中で落ちた\n")
    found = evidence(tmp_path)
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
# git が答えなかったとき
# --------------------------------------------------------------------------


def test_git_raises_instead_of_returning_nothing(tmp_path: pathlib.Path) -> None:
    """⚠️ 「取れなかった」を「何も無かった」にしない。ここを混ぜると門番が黙る。"""
    git(tmp_path, "init", "-q", "-b", "main")
    with pytest.raises(publish_lint.GitError, match="終了コード"):
        publish_lint.git(tmp_path, "cat-file", "-p", "deadbeef" * 5)


def test_main_reports_an_error_when_git_cannot_answer(
    repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """差分を取れなかったら合格にしない。終了コードは 1 でも 0 でもなく 2。"""

    def boom(*args: object, **kwargs: object) -> str:
        raise publish_lint.GitError("git diff が終了コード 128")

    monkeypatch.setattr(publish_lint, "collect", boom)
    assert publish_lint.main(["--root", str(repo), "--base", "base"]) == 2
    assert "検査できなかった" in capsys.readouterr().out


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
    write(tmp_path, "README.md", "# 記録\n\n| 14 | `impl/14_x/` | 1スレッド | **0:24:27** | |\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "branch", "base")
    return tmp_path


def run(repo: pathlib.Path) -> int:
    return publish_lint.main(["--root", str(repo), "--base", "base"])


def test_main_passes_on_a_harmless_commit(
    repo: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "docs/a.md", "ふつうの文書\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "文書を足す")
    assert run(repo) == 0
    assert "取り消せない指摘なし" in capsys.readouterr().out


def test_main_stops_on_a_secret(repo: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, "deploy.md", f"token = {TOKEN}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "鍵を貼ってしまった")
    assert run(repo) == 1
    out = capsys.readouterr().out
    assert "P1" in out and "point of no return" in out


def test_a_secret_removed_in_a_later_commit_is_still_caught(
    repo: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """⚠️ 最終差分では消えていても、blob は履歴に残って SHA から取れる。

    「うっかり足して次のコミットで消した」は、公開前チェックがいちばん
    捕まえないといけない形。
    """
    write(repo, "leak.md", f"token = {TOKEN}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "うっかり貼った")
    (repo / "leak.md").unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "消した")
    assert run(repo) == 1
    assert "leak.md" in capsys.readouterr().out


def test_a_secret_in_a_pushed_commit_message_is_caught(
    repo: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "a.md", "ふつう\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"デプロイ手順\n\ntoken = {TOKEN}")
    assert run(repo) == 1
    assert "のメッセージ" in capsys.readouterr().out


def test_evidence_that_was_never_committed_does_not_count(
    repo: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """⚠️ 手元にあるだけの verify.txt は、push したあと誰にも見えない。"""
    write(repo, "results/14_x/env.txt", "impl: 14_x\nimpl_sha256: abc\ngit_commit: def\n")
    git(repo, "add", "results/14_x/env.txt")
    git(repo, "commit", "-qm", "記録を足す")
    write(repo, "results/14_x/verify.txt", "PASS\n")
    write(
        repo, "results/14_x/time.txt", "\tElapsed (wall clock) time (h:mm:ss or m:ss): 24:27.10\n"
    )
    assert run(repo) == 1
    out = capsys.readouterr().out
    assert "コミットされていない" in out and "verify.txt" in out


def test_a_fully_committed_record_passes(repo: pathlib.Path) -> None:
    write(repo, "results/14_x/env.txt", "impl: 14_x\nimpl_sha256: abc\ngit_commit: def\n")
    write(repo, "results/14_x/verify.txt", "PASS\n")
    write(
        repo, "results/14_x/time.txt", "\tElapsed (wall clock) time (h:mm:ss or m:ss): 24:27.10\n"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "記録を足す")
    assert run(repo) == 0


@pytest.mark.parametrize("key", ["color.ui", "color.diff"])
def test_a_secret_is_caught_even_when_color_output_is_forced(repo: pathlib.Path, key: str) -> None:
    """色が付くと行頭が `+` で始まらず、追加行ゼロ件＝合格に見える。

    ⚠️ `color.ui` だけ塞いでも足りない。より細かい `color.diff` が勝つので、
    片方だけ試して直ったことにしない。
    """
    git(repo, "config", key, "always")
    write(repo, "leak.md", f"token = {TOKEN}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "鍵入り")
    assert run(repo) == 1


def test_merging_the_base_branch_does_not_report_its_content(repo: pathlib.Path) -> None:
    """⚠️ base 側は既に公開済み。取り込んだだけで鳴ると main を merge するたびに止まる。"""
    git(repo, "checkout", "-qb", "feature")
    write(repo, "a.md", "無害な変更\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "無害な変更")
    git(repo, "checkout", "-q", "main")
    write(repo, "public.md", f"report from {EMAIL}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "公開済みの内容")
    git(repo, "branch", "-f", "base", "main")
    git(repo, "checkout", "-q", "feature")
    git(repo, "merge", "-q", "--no-edit", "main")
    assert run(repo) == 0


def test_a_secret_written_while_resolving_a_merge_is_caught(repo: pathlib.Path) -> None:
    """誤検知を消したぶんで見逃しを作っていないこと。"""
    write(repo, "c.md", "もと\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "もと")
    git(repo, "branch", "-f", "base", "HEAD")
    git(repo, "checkout", "-qb", "ours")
    write(repo, "c.md", "ours\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "ours")
    git(repo, "checkout", "-q", "main")
    write(repo, "c.md", "theirs\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "theirs")
    git(repo, "checkout", "-q", "ours")
    subprocess.run(["git", "merge", "main"], cwd=repo, check=False, capture_output=True)
    write(repo, "c.md", f"key = {TOKEN}\n")  # 解決のときに書いてしまった
    git(repo, "add", "c.md")
    git(repo, "commit", "-qm", "競合を解決")
    assert run(repo) == 1


def test_a_binary_blob_stops_the_push(
    repo: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """検体は PEM 秘密鍵入りの blob。追加行が1つも出ないので、黙ると素通りする。"""
    (repo / "blob.bin").write_bytes(b"\x00\x01" + PEM.encode() + b"\n\x00")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "バイナリを足す")
    assert run(repo) == 1
    assert "検査できない" in capsys.readouterr().out


def test_japanese_output_is_decoded_as_utf8(repo: pathlib.Path) -> None:
    """⚠️ ロケールで復号すると cp932 の環境で落ちる。utf-8 を明示してあること。

    この検査は UTF-8 の環境では退行を捕まえられない (そこでは text=True でも通る)。
    ここで固定しているのは「日本語がそのまま読めること」まで。
    """
    write(repo, "a.md", "なかみ\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "記録 #13 の訂正")
    assert "記録 #13 の訂正" in publish_lint.git(repo, "log", "-1", "--format=%B")


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
    files, _ = fs_view(ROOT / "results")
    paths = [f"results/{p}" for p in files]
    dirs = sorted({p.rsplit("/", 1)[0] + "/" for p in paths if p.endswith("/env.txt")})
    assert dirs, "results/ に記録が1つも無い"
    full_files = [*paths, "README.md"]
    found = list(
        publish_lint.evidence_findings(
            full_files,
            lambda rel: (ROOT / rel).read_text(encoding="utf-8"),
            dirs,
        )
    )
    assert found == []
