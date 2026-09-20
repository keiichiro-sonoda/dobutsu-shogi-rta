#!/usr/bin/env python3
"""push で取り消せないものだけを止める。

公開リポジトリでは、一度出したものは引っ込められない。参照を消しても SHA を知って
いれば取れることがあり、fork・キャッシュ・アーカイブにも渡る。鍵は消すのではなく
失効させるしかなく、計測機の同定情報には取り消す手段そのものが無い。

一方で、説明の誤り・表の数字の取り残し・命名は、あとから足せる。このリポジトリには
「訂正は末尾に足す」「不具合は CLAUDE.md の『次の実装で必ず直すもの』に積む」という
追記型の回復手段が既にある。

なので、この門番が見るのは**追記で回復できない種類だけ**にする。

| ID | 内容 | 見る範囲 |
|----|------|----------|
| P1 | 鍵・トークンらしき文字列 | 各コミットの追加行とメッセージ |
| P2 | 計測機と個人の同定情報 | 各コミットの追加行とメッセージ |
| P3 | 既存の凍結物の変更・削除・改名 | base との差 |
| P4 | 記録の証拠の欠損、記録表との食い違い | HEAD の中身 |
| P5 | コミットメッセージの会話ログへのポインタ | 各コミットのメッセージ |

`Co-Authored-By:` は残す (CLAUDE.md の取り決め)。`Claude-Session:` の URL は
他人が開けないうえ恒久的に残るので P5 で落とす。

⚠️ 説明の正しさ・命名・設計は**わざと見ない**。直せるものを門番に足すと、鳴っても
   push を止めない癖がつく。そちらは人と `/code-review` が読む。

範囲の取り方が P1・P2 と P3・P4 で違うのは、止めたいものが違うため。

- P1・P2 は**履歴に入ること**が問題。足して次のコミットで消しても blob は残り、
  SHA を知っていれば取れる。だから最終差分ではなく**コミットを1つずつ**見る
- P3・P4 は**公開後の状態**が問題。範囲の中で足して直したものは、まだ公開されて
  いないので凍結を破っていない。だから base との差と、HEAD の中身を見る

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
from collections.abc import Callable, Iterable, Iterator

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (パス, 新しい側の行番号, 行の中身)
Added = tuple[str, int, str]
# (ルール, 場所, 何が)
Finding = tuple[str, str, str]
# 公開される側の中身を読む
Reader = Callable[[str], str]

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
USER_PATH = ("ユーザ名を含む絶対パス", re.compile(r"/(?:home|Users|root)/[A-Za-z0-9._-]+"))
EMAIL = ("メールアドレス", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"))
IPV4 = ("IP アドレスらしき文字列", re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])"))
# ファイルには3つとも当てる。メッセージでは attribution の trailer 行だけメールを
# 通す。`Co-Authored-By:` は付ける約束で (CLAUDE.md)、履歴のメール 55 件は全部これ。
# ⚠️ メッセージ全体で素通りにはしない。他人のアドレスを本文に引用する経路が残る
FILE_IDENTITY = (USER_PATH, EMAIL, IPV4)
MESSAGE_IDENTITY = (USER_PATH, IPV4)
TRAILER = re.compile(r"^[A-Za-z][A-Za-z-]*-[Bb]y:\s")
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
FROZEN = ("baseline/", "oracle/")
# ⚠️ `results/` を丸ごと凍結しない。凍結は記録ごとのディレクトリで、直下の
#    `results/README.md` は証拠の置き方を説明する文書 (計装が増えるたび更新してきた)。
#    鳴らしても止めないものを門番に積むと、鳴っても止めない癖がつく
RECORD_DIR = re.compile(r"^results/[^/]+/")
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
ENV_PATH = re.compile(r"^results/[^/]+/env\.txt$")

# --------------------------------------------------------------------------
# P5 コミットメッセージ
# --------------------------------------------------------------------------
# ⚠️ 使用と言及を分ける。規約そのものを説明した行 (CLAUDE.md や、この修正の
#    コミットメッセージ) まで鳴ると、門番のことを書けなくなる。
#    落とすのは URL か、UUID のような不透明な値が続くときだけ
SESSION_LINE = re.compile(
    r"^\s*Claude-Session:\s*(?:\S+://|[0-9A-Fa-f][0-9A-Fa-f-]{15,})", re.MULTILINE
)


class GitError(RuntimeError):
    """git が答えを返さなかった。

    ⚠️ 「見つからなかった」と混ぜない。混ぜると、差分を取れなかったときに
    「指摘なし」と出てしまう。黙っているのと合格しているのを区別できないのが
    門番としていちばん悪い壊れ方になる。
    """


def git(root: pathlib.Path, *args: str) -> str:
    """git を呼んで標準出力を返す。失敗したら GitError。

    `core.quotepath=false` はパスを quote させないため (日本語のパスをそのまま扱う)。
    """
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr.strip() or proc.stdout.strip()).splitlines()
        raise GitError(f"git {' '.join(args)} が終了コード {proc.returncode}: {detail[:1]}")
    return proc.stdout


def has_commit(root: pathlib.Path, ref: str) -> bool:
    """比較先が見えるか。ここだけは git の失敗を答えとして扱う。"""
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


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
    """`--unified=0` の出力から追加行だけを拾う。同じ行は1回だけ返す。

    マージを `-m` で見ると親の数だけ同じ追加行が並ぶので、ここで潰す。
    """
    out: list[Added] = []
    path = ""
    lineno = 0
    for line in text.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            path = "" if target == "/dev/null" else target.removeprefix("b/")
        elif line.startswith("@@"):
            m = re.match(r"@@+ -\S+ \+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++") and path:
            out.append((path, lineno, line[1:]))
            lineno += 1
    return list(dict.fromkeys(out))


def identity_matches(text: str, rules: Iterable[tuple[str, re.Pattern[str]]]) -> Iterator[str]:
    for name, pattern in rules:
        if m := pattern.search(text):
            yield f"{name} ({m.group(0)})"


def secret_findings(added: Iterable[Added], where: str = "") -> Iterator[Finding]:
    """P1。鍵とトークンは、出てしまったら消すのではなく失効させるしかない。"""
    for path, lineno, text in added:
        for name, pattern in SECRETS:
            if pattern.search(text):
                yield ("P1", f"{where}{path}:{lineno}", f"{name}らしき文字列")


def identity_findings(added: Iterable[Added], where: str = "") -> Iterator[Finding]:
    """P2。計測機と人の同定情報。取り消す手段が無いので、出す前に止める。"""
    for path, lineno, text in added:
        at = f"{where}{path}:{lineno}"
        rules = [r for r in FILE_IDENTITY if not (r is IPV4 and path.endswith(GENERATED))]
        for what in identity_matches(text, rules):
            yield ("P2", at, what)
        if path.endswith(".sh") and HOST_CMD.search(text):
            yield ("P2", at, "ホスト名を取得している (同一性は cpu / cores / mem_total で足りる)")
        if path.endswith("env.txt") and HOST_FIELD.match(text):
            yield ("P2", at, "記録の証拠にホスト名が入っている")


def message_findings(messages: Iterable[tuple[str, str]]) -> Iterator[Finding]:
    """P1・P2・P5 をコミットメッセージにも当てる。

    ⚠️ メッセージも履歴に残る。本文に貼った鍵は、ファイルに貼った鍵と同じだけ
    取り消せない。
    """
    for sha, body in messages:
        for lineno, line in enumerate(body.splitlines(), 1):
            at = f"{sha} のメッセージ:{lineno}"
            for name, pattern in SECRETS:
                if pattern.search(line):
                    yield ("P1", at, f"{name}らしき文字列")
            rules = MESSAGE_IDENTITY if TRAILER.match(line) else (*MESSAGE_IDENTITY, EMAIL)
            for what in identity_matches(line, rules):
                yield ("P2", at, what)
        if SESSION_LINE.search(body):
            yield ("P5", sha, "コミットメッセージに Claude-Session: の行がある")


def recorded_impls(files: Iterable[str], read: Reader) -> set[str]:
    """`results/*/env.txt` が指している実装ディレクトリ。

    ここに挙がったものは記録済み＝凍結。`env.txt` の `impl_sha256` と `git_commit` が
    指しているので、1文字でも直すと指し先が嘘になる。
    """
    out: set[str] = set()
    for path in sorted(p for p in files if ENV_PATH.match(p)):
        text = read(path)
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
        if hit is None and (m := RECORD_DIR.match(path)):
            hit = m.group(0)
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


def evidence_findings(files: Iterable[str], read: Reader, dirs: Iterable[str]) -> Iterator[Finding]:
    """P4。記録は証拠で立っている。揃わないまま公開すると、あとから足せない。

    ⚠️ 作業ディレクトリではなく**公開される側**を見る。手元にあるだけでコミット
    していない `verify.txt` は、push したあと誰にも見えない。
    """
    present = set(files)
    table = record_times(read("README.md")) if "README.md" in present else {}
    for rel in dirs:
        missing = [name for name in EVIDENCE if f"{rel}{name}" not in present]
        if missing:
            yield ("P4", rel, f"証拠がコミットされていない ({' / '.join(missing)})")
            continue

        env = read(f"{rel}env.txt")
        for field in ENV_REQUIRED:
            if not has_field(env, field):
                yield ("P4", f"{rel}env.txt", f"{field} が無い")
        name, digest = ENV_PAIR
        if has_field(env, name) and not has_field(env, digest):
            yield ("P4", f"{rel}env.txt", f"{name} を指しているのに {digest} が無い")

        if "PASS" not in read(f"{rel}verify.txt"):
            yield ("P4", f"{rel}verify.txt", "オラクル検証が PASS していない")

        yield from time_findings(read(f"{rel}time.txt"), rel, table)


def time_findings(time_txt: str, rel: str, table: dict[int, int]) -> Iterator[Finding]:
    """`time.txt` の実測と記録表のタイムを突き合わせる。

    同じ数字を2か所に持っているので、片方だけ直すと食い違う。記録は凍結物なので、
    公開してしまうと訂正を足すことしかできない。
    """
    m = ELAPSED.search(time_txt)
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


def head_reader(root: pathlib.Path, ref: str = "HEAD") -> Reader:
    """`ref` の中身を読む。作業ディレクトリは見ない。"""

    def read(path: str) -> str:
        return git(root, "show", f"{ref}:{path}")

    return read


def files_at(root: pathlib.Path, ref: str = "HEAD") -> list[str]:
    """`ref` が持っているファイル。未追跡のものは入らない。"""
    return git(root, "ls-tree", "-r", "--name-only", ref).splitlines()


def commit_messages(root: pathlib.Path, shas: Iterable[str]) -> list[tuple[str, str]]:
    return [(sha[:7], git(root, "log", "-1", "--format=%B", sha)) for sha in shas]


def collect(root: pathlib.Path, base: str) -> tuple[list[Finding], int, int]:
    """(指摘, 見たコミット数, 見たファイル数)。git が答えないときは GitError。"""
    shas = git(root, "rev-list", "--reverse", f"{base}..HEAD").split()
    changes = parse_name_status(git(root, "diff", "--name-status", f"{base}..HEAD"))

    found: list[Finding] = []
    # ⚠️ コミットを1つずつ見る。最終差分だけだと「足して次のコミットで消した鍵」が
    #    素通りする (blob は履歴に残り、SHA を知っていれば取れる)
    for sha in shas:
        added = parse_added_lines(git(root, "show", "--format=", "--unified=0", "-m", sha))
        where = f"{sha[:7]} "
        found += secret_findings(added, where)
        found += identity_findings(added, where)
    found += message_findings(commit_messages(root, shas))

    files = files_at(root)
    read = head_reader(root)
    found += frozen_findings(changes, recorded_impls(files, read))
    found += evidence_findings(files, read, new_result_dirs(changes))
    return found, len(shas), len(changes)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="push で取り消せないものを検査する")
    parser.add_argument("--base", default="origin/main", help="比較先 (既定: origin/main)")
    parser.add_argument("--root", type=pathlib.Path, default=ROOT, help="検査するリポジトリ")
    args = parser.parse_args(argv)

    if not has_commit(args.root, args.base):
        print(f"publish_lint: {args.base} が見えない。git fetch してから回すこと")
        return 2

    try:
        found, n_commits, n_files = collect(args.root, args.base)
    except GitError as exc:
        # ⚠️ ここで 0 を返さない。検査できなかったことを合格と区別する
        print(f"publish_lint: 検査できなかった (終了コード 2)。{exc}")
        return 2

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
