#!/usr/bin/env python3
"""push で取り消せないものだけを止める。

公開リポジトリでは、一度出したものは引っ込められない。参照を消しても SHA を知って
いれば取れることがあり、fork・キャッシュ・アーカイブにも渡る。鍵は消すのではなく
失効させるしかなく、計測機の同定情報には取り消す手段そのものが無い。

一方で、説明の誤り・表の数字の取り残し・命名は、あとから足せる。このリポジトリには
「訂正は末尾に足す」「不具合は CLAUDE.md の『次の実装で必ず直すもの』に積む」という
追記型の回復手段が既にある。

なので、この門番が見るのは**追記で回復できない種類だけ**にする。

| ID | 内容 |
|----|------|
| P1 | 鍵・トークンらしき文字列 |
| P2 | 計測機と個人の同定情報 (ホスト名の収集、ユーザ名入りの絶対パス、メール、IP) |
| P3 | 既存の凍結物の変更・削除・改名 |
| P4 | 新しい記録の証拠が欠けている、または記録表と食い違う |
| P5 | コミットメッセージに会話ログへのポインタ |

⚠️ 説明の正しさ・命名・設計は**わざと見ない**。直せるものを門番に足すと、鳴っても
   push を止めない癖がつく。そちらは人と `/code-review` が読む。

見るのは push しようとしている範囲の**追加行だけ**。base 側は既に公開済みなので、
そこを鳴らしても止めようがない。

使い方:

    python3 tools/publish_lint.py                  # origin/main..HEAD を見る
    python3 tools/publish_lint.py --base <ref>     # 比較先を変える
"""

from __future__ import annotations

import argparse
import math
import pathlib
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (パス, 新しい側の行番号, 行の中身)
Added = tuple[str, int, str]
# (ルール, 場所, 何が)
Finding = tuple[str, str, str]

# --------------------------------------------------------------------------
# P1 鍵・トークン
#
# ⚠️ 検体を literal で書かない。長さを要求する形にしてあるので、この表そのものは
#    検体にならない (テスト側も実行時に組み立てる)。
# --------------------------------------------------------------------------
SECRETS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PEM 秘密鍵", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub トークン", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{36}\b")),
    ("GitHub PAT", re.compile(r"\bgithub_pat_[0-9A-Za-z_]{22,}")),
    ("AWS アクセスキー", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("`sk-` で始まる API キー", re.compile(r"\bsk-[0-9A-Za-z_-]{20,}")),
    ("Slack トークン", re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}")),
    ("Authorization ヘッダ", re.compile(r"[Aa]uthorization:\s*(?:Bearer|Basic)\s+\S")),
)

# --------------------------------------------------------------------------
# P2 同定情報
# --------------------------------------------------------------------------
USER_PATH = re.compile(r"/(?:home|Users|root)/[A-Za-z0-9._-]+")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
# ホスト名を取りに行くコマンド。シェルスクリプトにだけ当てる
# (Python やテストには「ホスト名を記録しない」と書いた行がありうる)
HOST_CMD = re.compile(r"\bhostname\b|\buname\s+-n\b|gethostname")
# env.txt に書き出された側
HOST_FIELD = re.compile(r"^host(?:name)?:")
# 生成物なので中身を選べない。4連の版番号 (0.11.0.x の形) が IPV4 と衝突する。
# ⚠️ ここに実例を literal で書くとこの行自身が P2 で鳴る (言及と使用の区別)
GENERATED = ("uv.lock",)

# --------------------------------------------------------------------------
# P3 凍結物
# --------------------------------------------------------------------------
FROZEN = ("baseline/", "oracle/", "results/")
ADDED_OK = "A"  # 追加だけは通す。記録は results/ に「足す」もの

# --------------------------------------------------------------------------
# P4 記録の証拠
# --------------------------------------------------------------------------
EVIDENCE = ("env.txt", "verify.txt", "time.txt")
# ⚠️ `impl_sha256` を一律に必須にしない。記録 #0 (baseline) は `tools/run.sh` が
#    この項目を持つ前の記録で、`results/` は凍結なのであとから足せない。
#    実装を指している記録だけ、指し先を固定する組として揃っているかを見る。
ENV_REQUIRED = ("git_commit",)
ENV_PAIR = ("impl", "impl_sha256")
ELAPSED = re.compile(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\):\s*([\d:.]+)")
# 記録表の4列目: | 13 | `impl/13_c_expand/` | 1スレッド | **0:24:27** | ...
RECORD_ROW = re.compile(r"^\|\s*(\d+)\s*\|[^|]*\|[^|]*\|\s*\*\*([\d:.]+)\*\*")
RESULT_DIR = re.compile(r"^results/(\d+)_[^/]*/")

# --------------------------------------------------------------------------
# P5 コミットメッセージ
# --------------------------------------------------------------------------
SESSION_LINE = re.compile(r"^\s*Claude-Session:", re.MULTILINE)


def git(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    """パスを quote させずに git を呼ぶ (日本語のパスをそのまま受け取るため)。"""
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def parse_name_status(text: str) -> list[tuple[str, str]]:
    """`--name-status` を (状態, パス) にする。

    改名は `R100<TAB>旧<TAB>新` で来る。凍結物としては**旧のほうが消える**のが
    問題なので、旧を改名として報告する。
    """
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0][:1]
        if status in ("R", "C") and len(parts) == 3:
            out.append((status, parts[1]))
            out.append((ADDED_OK, parts[2]))
        elif len(parts) >= 2:
            out.append((status, parts[1]))
    return out


def parse_added_lines(text: str) -> list[Added]:
    """`git diff --unified=0` から追加行だけを拾う。"""
    out: list[Added] = []
    path = ""
    lineno = 0
    for line in text.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            path = "" if target == "/dev/null" else target.removeprefix("b/")
        elif line.startswith("@@"):
            m = re.match(r"@@ -\S+ \+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++") and path:
            out.append((path, lineno, line[1:]))
            lineno += 1
    return out


def secret_findings(added: Iterable[Added]) -> Iterator[Finding]:
    """P1。鍵とトークンは、出てしまったら消すのではなく失効させるしかない。"""
    for path, lineno, text in added:
        for name, pattern in SECRETS:
            if pattern.search(text):
                yield ("P1", f"{path}:{lineno}", f"{name}らしき文字列")


def identity_findings(added: Iterable[Added]) -> Iterator[Finding]:
    """P2。計測機と人の同定情報。取り消す手段が無いので、出す前に止める。"""
    for path, lineno, text in added:
        where = f"{path}:{lineno}"
        if m := USER_PATH.search(text):
            yield ("P2", where, f"ユーザ名を含む絶対パス ({m.group(0)})")
        if m := EMAIL.search(text):
            yield ("P2", where, f"メールアドレス ({m.group(0)})")
        if not path.endswith(GENERATED) and (m := IPV4.search(text)):
            yield ("P2", where, f"IP アドレスらしき文字列 ({m.group(0)})")
        if path.endswith(".sh") and HOST_CMD.search(text):
            yield (
                "P2",
                where,
                "ホスト名を取得している (同一性は cpu / cores / mem_total で足りる)",
            )
        if path.endswith("env.txt") and HOST_FIELD.match(text):
            yield ("P2", where, "記録の証拠にホスト名が入っている")


def recorded_impls(root: pathlib.Path) -> set[str]:
    """`results/*/env.txt` が指している実装ディレクトリ。

    ここに挙がったものは記録済み＝凍結。`env.txt` の `impl_sha256` と `git_commit` が
    指しているので、1文字でも直すと指し先が嘘になる。
    """
    out: set[str] = set()
    for env in sorted((root / "results").glob("*/env.txt")):
        text = env.read_text(encoding="utf-8")
        for field in ("impl", "label"):
            if m := re.search(rf"^{field}:\s*(\S+)\s*$", text, re.MULTILINE):
                name = m.group(1)
                out.add("baseline/" if name == "baseline" else f"impl/{name}/")
                break
    return out


def frozen_findings(changes: Iterable[tuple[str, str]], recorded: set[str]) -> Iterator[Finding]:
    """P3。過去の記録の指し先を動かすと、記録表そのものが嘘になる。"""
    prefixes = tuple(FROZEN) + tuple(sorted(recorded))
    for status, path in changes:
        if status == ADDED_OK:
            continue
        hit = next((p for p in prefixes if path.startswith(p)), None)
        if hit is not None:
            verb = {"M": "変更", "D": "削除", "R": "改名", "C": "複製元", "T": "種別変更"}
            yield ("P3", path, f"凍結物 ({hit}) の{verb.get(status, status)}")


def new_result_dirs(changes: Iterable[tuple[str, str]]) -> list[str]:
    """この範囲で新しく増えた `results/<番号>_<名前>/`。"""
    out: list[str] = []
    for status, path in changes:
        m = RESULT_DIR.match(path)
        if status == ADDED_OK and m and m.group(0) not in out:
            out.append(m.group(0))
    return out


def to_seconds(text: str) -> int | None:
    """`8:55:31` と `24:27.10` の両方を秒にする。秒未満は切り捨てる。

    記録表は `main.log` と同じく切り捨てで書く (35:25.94 が 0:35:25)。
    """
    parts = text.split(":")
    if not 2 <= len(parts) <= 3:
        return None
    try:
        values = [float(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 2:
        values.insert(0, 0.0)
    return math.floor(values[0] * 3600 + values[1] * 60 + values[2])


def record_times(readme: str) -> dict[int, int]:
    """記録表の (番号 → 秒)。"""
    out: dict[int, int] = {}
    for line in readme.splitlines():
        m = RECORD_ROW.match(line)
        if m and (seconds := to_seconds(m.group(2))) is not None:
            out.setdefault(int(m.group(1)), seconds)
    return out


def has_field(env: str, name: str) -> bool:
    return re.search(rf"^{name}:\s*\S", env, re.MULTILINE) is not None


def evidence_findings(root: pathlib.Path, dirs: Iterable[str]) -> Iterator[Finding]:
    """P4。記録は証拠で立っている。揃わないまま公開すると、あとから足せない。"""
    table = record_times((root / "README.md").read_text(encoding="utf-8"))
    for rel in dirs:
        directory = root / rel
        missing = [name for name in EVIDENCE if not (directory / name).is_file()]
        if missing:
            yield ("P4", rel, f"証拠が足りない ({' / '.join(missing)})")
            continue

        env = (directory / "env.txt").read_text(encoding="utf-8")
        for field in ENV_REQUIRED:
            if not has_field(env, field):
                yield ("P4", f"{rel}env.txt", f"{field} が無い")
        name, digest = ENV_PAIR
        if has_field(env, name) and not has_field(env, digest):
            yield ("P4", f"{rel}env.txt", f"{name} を指しているのに {digest} が無い")

        if "PASS" not in (directory / "verify.txt").read_text(encoding="utf-8"):
            yield ("P4", f"{rel}verify.txt", "オラクル検証が PASS していない")

        yield from time_findings(root, rel, table)


def time_findings(root: pathlib.Path, rel: str, table: dict[int, int]) -> Iterator[Finding]:
    """`time.txt` の実測と記録表のタイムを突き合わせる。

    同じ数字を2か所に持っているので、片方だけ直すと食い違う。記録は凍結物なので、
    公開してしまうと訂正を足すことしかできない。
    """
    m = ELAPSED.search((root / rel / "time.txt").read_text(encoding="utf-8"))
    measured = to_seconds(m.group(1)) if m else None
    if measured is None:
        yield ("P4", f"{rel}time.txt", "Elapsed (wall clock) time を読めない")
        return
    number = int(RESULT_DIR.match(rel).group(1))  # type: ignore[union-attr]
    listed = table.get(number)
    if listed is None:
        yield ("P4", rel, f"README の記録表に記録 #{number} の行が無い")
    elif listed != measured:
        yield (
            "P4",
            rel,
            f"記録表のタイムと time.txt が違う (表 {listed} 秒 / 実測 {measured} 秒)",
        )


def session_findings(messages: Iterable[tuple[str, str]]) -> Iterator[Finding]:
    """P5。公開リポジトリのコミットログに会話ログへの恒久的なポインタを残さない。"""
    for sha, body in messages:
        if SESSION_LINE.search(body):
            yield ("P5", sha, "コミットメッセージに Claude-Session: の行がある")


def commit_messages(text: str) -> list[tuple[str, str]]:
    """`git log --format=%H%n%B%x00` を (sha, 本文) にする。"""
    out: list[tuple[str, str]] = []
    for chunk in text.split("\0"):
        if chunk.strip():
            sha, _, body = chunk.strip().partition("\n")
            out.append((sha[:7], body))
    return out


def collect(root: pathlib.Path, base: str) -> tuple[list[Finding], int, int]:
    """(指摘, 見たコミット数, 見たファイル数)。"""
    rng = f"{base}..HEAD"
    changes = parse_name_status(git(root, "diff", "--name-status", rng).stdout)
    added = parse_added_lines(git(root, "diff", "--unified=0", rng).stdout)
    commits = commit_messages(git(root, "log", "--format=%H%n%B%x00", rng).stdout)

    found: list[Finding] = []
    found += secret_findings(added)
    found += identity_findings(added)
    found += frozen_findings(changes, recorded_impls(root))
    found += evidence_findings(root, new_result_dirs(changes))
    found += session_findings(commits)
    return found, len(commits), len(changes)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="push で取り消せないものを検査する")
    parser.add_argument("--base", default="origin/main", help="比較先 (既定: origin/main)")
    parser.add_argument("--root", type=pathlib.Path, default=ROOT, help="検査するリポジトリ")
    args = parser.parse_args(argv)

    if git(args.root, "rev-parse", "--verify", f"{args.base}^{{commit}}").returncode != 0:
        print(f"publish_lint: {args.base} が見えない。git fetch してから回すこと")
        return 2

    found, n_commits, n_files = collect(args.root, args.base)
    if found:
        print(f"publish_lint: 公開すると取り消せない指摘が {len(found)} 件\n")
        for rule, where, what in found:
            print(f"  {rule} {where}: {what}")
        print(
            "\n⚠️ push は point of no return。参照を消しても SHA から取れることがあり、"
            "鍵は失効、同定情報は取り消す手段が無い"
        )
        return 1
    print(
        f"publish_lint: 取り消せない指摘なし "
        f"({n_commits} コミット / {n_files} ファイルを {args.base} と比べた)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
