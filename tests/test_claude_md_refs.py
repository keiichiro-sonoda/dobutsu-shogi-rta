"""CLAUDE.md の言い回しを引いた箇所が、いまの CLAUDE.md で見つかること。

凍結した `impl/` のコメントや記録ノートは「CLAUDE.md の「途中で落ちたら再走」」のように
CLAUDE.md の文言を引いている。凍結物は直せないので、CLAUDE.md を畳むとき (経緯を
`docs/lessons.md` に、手順をスキルに移すとき) に、引かれている言い回しを消すと指し先が無くなる。
ここで、リポジトリの中の「CLAUDE.md「…」」「CLAUDE.md の「…」」がすべて CLAUDE.md の本文に
あることを見る。強調・バッククォート・空白は無視して比べる。
"""

from __future__ import annotations

import re
import subprocess

from conftest import ROOT

QUOTE = re.compile(r"CLAUDE\.md ?(?:の)?「([^」\n]+)」")

# 引用元が凍結物か生ログで直せず、しかも最初から言い換えだったもの (引用 → CLAUDE.md の言い回し)
PARAPHRASES = {
    # experiments/numa_bind/logs/n1b_fingerprint.txt (コミット済みの生ログ)
    "生ログを入れてコミットする": "生ログを `experiments/<名前>/logs/` に入れてコミットする",
}


def normalize(text: str) -> str:
    return re.sub(r"[`*\s]", "", text)


def quoted_phrases() -> dict[str, list[str]]:
    """リポジトリで追跡しているファイルから、CLAUDE.md を引いた言い回しを集める。"""
    pattern = r"CLAUDE\.md ?(の)?「[^」]+」"
    out = subprocess.run(
        ["git", "grep", "-nE", pattern, "--", ".", ":!CLAUDE.md", ":!tests/test_claude_md_refs.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    found: dict[str, list[str]] = {}
    for line in out.splitlines():
        where, _, rest = line.partition(":")
        for phrase in QUOTE.findall(rest):
            found.setdefault(phrase, []).append(where)
    return found


def test_there_are_quotes_to_check() -> None:
    """空振りしていないこと (git grep が何も返さなければ、このテストは何も守っていない)。"""
    assert len(quoted_phrases()) >= 10


def test_every_quoted_phrase_is_still_in_claude_md() -> None:
    """★引かれている言い回しは、CLAUDE.md の本文 (見出しを含む) にそのまま残っている。"""
    body = normalize((ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
    missing = {
        phrase: where
        for phrase, where in quoted_phrases().items()
        if normalize(PARAPHRASES.get(phrase, phrase)) not in body
    }
    assert missing == {}, (
        f"CLAUDE.md から消えた言い回しがある: {missing}。凍結物が引いているなら CLAUDE.md に残す"
    )


def test_the_paraphrases_are_still_quoted() -> None:
    """言い換えの表が空振りしていないこと (引用元が消えたら表からも外す)。"""
    quoted = quoted_phrases()
    for phrase in PARAPHRASES:
        assert phrase in quoted, f"「{phrase}」はもう引かれていない。PARAPHRASES から外すこと"
