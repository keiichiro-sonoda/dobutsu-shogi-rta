#!/usr/bin/env python3
"""完全解析の成果物 (dat/) の指紋を取り、同じ答えが出たかを照合する。

    python3 tools/fingerprint_dat.py <dat>                     指紋を表で出力
    python3 tools/fingerprint_dat.py <dat> --tsv               指紋を機械可読で出力
    python3 tools/fingerprint_dat.py <dat> <dat2>              2つの dat/ を照合
    python3 tools/fingerprint_dat.py <dat> --against <tsv>     固定した指紋と照合

`tools/verify_log.py` は手数別の「局面数」しか見ない。実装を書き換えたとき、
数が合っていて中身が違う、という壊れ方は検出できない。ここでは
深さごとの局面集合の指紋を比較し、そのような不一致の検出を補助する。

指紋は深さごとの (件数, 総和 mod 2^64, XOR)。3つとも要素の順序に依存しないので、
チャンクの分かれ方が違っても同じ値になる。同じ答えでも win003te_000 と _001 の
分割は集合の pop 順で変わるため、バイト比較や件数比較では足りない。
異なる集合でも同じ指紋になりうるため、PASS は集合の完全一致を証明しない。
完走とオラクル一致を別途確認した、自分で生成したデータに使う。

⚠️ `--against` の相手 (oracle/fingerprint.tsv) は**オラクルではない**。
2021年の原典ではなく #15 の成果物から取った値で、由来が違う。
`dat/` は 2.2 GB あって git に入らないので、照合のたびに2本ぶん
ディスクに置いておく代わりに、値のほうを固定してある。

形式の知識は Format にまとめてある。いまは #15 までの pickle と、
記録 #16 で入った生バイナリ (.bin) の2つ。どちらの dat/ かは中身から見分けるので、
コマンドの打ち方は形式が変わっても同じ。さらに形式が増えるときは
Format をもう1つ書いて FORMATS に足す。
"""

from __future__ import annotations

import dataclasses
import pathlib
import pickle
import re
import sys
from array import array
from collections.abc import Callable, Iterable

MASK64 = (1 << 64) - 1

# (深さ, 勝敗) -> (件数, 総和, XOR)。引き分けは深さを持たないので None を使う
Key = tuple[int | None, str]
Print = tuple[int, int, int]


@dataclasses.dataclass(frozen=True)
class Format:
    """dat/ の保存形式。ファイル名の読み方と中身の読み方をひとまとめにする。"""

    name: str
    suffix: str
    win: re.Pattern[str]
    lose: re.Pattern[str]
    unknown: re.Pattern[str]
    # 中間ファイルの語幹。答えではないので数えない
    skip: tuple[str, ...]
    load: Callable[[pathlib.Path], Iterable[int]]


def _names(suffix: str) -> dict[str, re.Pattern[str]]:
    """拡張子からファイル名の3つの規則を組み立てる。

    形式が増えても命名規則は同じ (深さとチャンク番号の並べ方は変えない) ので、
    ここで作る。形式ごとに手で書くと、片方だけ直して食い違う。
    """
    esc = re.escape(suffix)
    return {
        "win": re.compile(rf"^win(\d+)te_(\d+){esc}$"),
        "lose": re.compile(rf"^lose(\d+)te_(\d+){esc}$"),
        "unknown": re.compile(rf"^unknown(\d+){esc}$"),
    }


def _load_pickle(path: pathlib.Path) -> set[int]:
    with path.open("rb") as f:
        obj = pickle.load(f)
    return set(obj)


def _load_raw(path: pathlib.Path) -> array[int]:
    """8 バイトのリトルエンディアン符号なし整数を並べただけのファイル。

    ヘッダが無いので件数は os.path.getsize(path) // 8 で開かずに分かる。
    pickle と違って要素ごとの PyLong を作らない (memcpy 1回) ので、
    大きい dat/ ではここが桁で速い。
    """
    a = array("Q")
    a.frombytes(path.read_bytes())
    return a


PICKLE = Format(
    name="pickle",
    suffix=".pickle",
    **_names(".pickle"),
    skip=("_next", "_next_win"),
    load=_load_pickle,
)

RAW = Format(
    name="raw",
    suffix=".bin",
    **_names(".bin"),
    skip=("_next", "_next_win"),
    load=_load_raw,
)

# 記録 #16 で pickle から生バイナリへ移った。#15 までの dat/ も読めるよう両方残す
FORMATS: tuple[Format, ...] = (PICKLE, RAW)


def detect(dat: pathlib.Path) -> Format:
    """dat/ に並んでいるファイル名から形式を見分ける。

    ⚠️ 2つの形式が混ざっていたら**落とす**。途中まで変換した dat/ を
    黙って片方だけ数えると、件数が合わないまま PASS しかねない。
    """
    names = [p.name for p in dat.iterdir() if p.is_file()]
    hit = [
        f
        for f in FORMATS
        if any(f.win.match(n) or f.lose.match(n) or f.unknown.match(n) for n in names)
    ]
    if len(hit) == 1:
        return hit[0]
    if not hit:
        raise ValueError(f"答えのファイルが1つも無い: {dat}")
    raise ValueError(f"2つの形式が混ざっている ({'/'.join(f.name for f in hit)}): {dat}")


def fingerprint(dat: pathlib.Path, fmt: Format = PICKLE) -> dict[Key, Print]:
    """dat/ を走査して深さごとの指紋を返す。

    中間ファイル (_next / _next_win) は答えではないので無視する。
    最後まで確定しなかった unknown が引き分け局面。
    """
    acc: dict[Key, list[int]] = {}
    skip = tuple(stem + fmt.suffix for stem in fmt.skip)

    for path in sorted(dat.iterdir()):
        name = path.name
        if name.endswith(skip):
            continue

        if m := fmt.win.match(name):
            key: Key = (int(m.group(1)), "win")
        elif m := fmt.lose.match(name):
            key = (int(m.group(1)), "lose")
        elif fmt.unknown.match(name):
            key = (None, "draw")
        else:
            continue

        cell = acc.setdefault(key, [0, 0, 0])
        for v in fmt.load(path):
            cell[0] += 1
            cell[1] = (cell[1] + v) & MASK64
            cell[2] ^= v

    return {k: (c, s, x) for k, (c, s, x) in acc.items()}


def _sort_key(key: Key) -> tuple[int, int, str]:
    depth, result = key
    # 引き分けは最後に置く
    return (1, 0, result) if depth is None else (0, depth, result)


def render(fp: dict[Key, Print]) -> str:
    """人が読む表。⚠️ 桁区切りと幅揃えが入るので .tsv には使わない (dump を使う)。"""
    lines = [f"{'depth':>6} {'result':<6} {'count':>12} {'sum(mod 2^64)':>18} {'xor':>18}"]
    total = 0
    for key in sorted(fp, key=_sort_key):
        depth, result = key
        count, s, x = fp[key]
        total += count
        d = "-" if depth is None else str(depth)
        lines.append(f"{d:>6} {result:<6} {count:>12,} {s:>#18x} {x:>#18x}")
    lines.append(f"{'':>6} {'合計':<6} {total:>12,}")
    return "\n".join(lines)


TSV_HEADER = "# depth\tresult\tcount\tsum\txor"


def dump(fp: dict[Key, Print]) -> str:
    """機械可読の TSV。引き分けの深さは `-`。

    総和と XOR は10進で書く。oracle/distribution.tsv と totals.tsv が10進で、
    tests/conftest.py の読み手も int() をそのまま当てている。
    """
    lines = [TSV_HEADER]
    for key in sorted(fp, key=_sort_key):
        depth, result = key
        count, s, x = fp[key]
        d = "-" if depth is None else str(depth)
        lines.append(f"{d}\t{result}\t{count}\t{s}\t{x}")
    return "\n".join(lines) + "\n"


def load_tsv(text: str) -> dict[Key, Print]:
    """dump() の逆。`#` で始まる行と空行は読み飛ばす。"""
    out: dict[Key, Print] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 5:
            raise ValueError(f"{lineno} 行目: 5 列でない: {line!r}")
        d, result, count, s, x = parts
        try:
            depth = None if d == "-" else int(d)
            key: Key = (depth, result)
            value: Print = (int(count), int(s), int(x))
        except ValueError as e:
            raise ValueError(f"{lineno} 行目: 数として読めない: {line!r}") from e
        if key in out:
            raise ValueError(f"{lineno} 行目: depth={d} {result} が2度出てくる")
        out[key] = value
    if not out:
        raise ValueError("指紋が1行も無い")
    return out


def compare(a: dict[Key, Print], b: dict[Key, Print]) -> list[str]:
    """不一致の説明を返す。空なら一致。"""
    bad = []
    for key in sorted(set(a) | set(b), key=_sort_key):
        depth, result = key
        d = "-" if depth is None else str(depth)
        if key not in a:
            bad.append(f"  depth={d:>3} {result:<5} 片方 (1つ目) に無い")
        elif key not in b:
            bad.append(f"  depth={d:>3} {result:<5} 片方 (2つ目) に無い")
        elif a[key] != b[key]:
            ca, sa, xa = a[key]
            cb, sb, xb = b[key]
            diff = []
            if ca != cb:
                diff.append(f"件数 {ca:,} != {cb:,}")
            if sa != sb:
                diff.append(f"総和 {sa:#x} != {sb:#x}")
            if xa != xb:
                diff.append(f"XOR {xa:#x} != {xb:#x}")
            bad.append(f"  depth={d:>3} {result:<5} " + " / ".join(diff))
    return bad


def _take_option(args: list[str], name: str) -> tuple[list[str], str | None]:
    """`--name <値>` を取り出して、残りの引数と値を返す。"""
    if name not in args:
        return args, None
    i = args.index(name)
    if i + 1 >= len(args):
        raise ValueError(f"{name} に値が無い")
    return args[:i] + args[i + 2 :], args[i + 1]


def _read_dat(path: pathlib.Path, which: str) -> dict[Key, Print] | None:
    """dat/ の指紋。読めないか空なら None (呼び手が終了コード 2 にする)。

    形式は中身から見分ける。#15 までの .pickle と #16 以降の .bin を
    同じコマンドで扱えるようにするため。
    """
    if not path.is_dir():
        print(f"ディレクトリが無い: {path}", file=sys.stderr)
        return None
    try:
        fmt = detect(path)
    except ValueError as e:
        print(f"{e} ({which})", file=sys.stderr)
        return None
    fp = fingerprint(path, fmt)
    if not any(count for count, _, _ in fp.values()):
        print(f"照合対象の局面が無い ({which})", file=sys.stderr)
        return None
    return fp


def _report(fp_a: dict[Key, Print], fp_b: dict[Key, Print], against: str | None) -> int:
    bad = compare(fp_a, fp_b)
    if bad:
        print(f"FAIL: {len(bad)} 項目が不一致")
        print("\n".join(bad))
        return 1
    total = sum(c for c, _, _ in fp_a.values())
    what = f" ({against} と照合)" if against else ""
    print(f"PASS: {len(fp_a)} 項目の指紋が一致{what} (集合の完全一致を証明するものではない)")
    print(f"  照合した局面数の合計: {total:,}")
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    try:
        args, against = _take_option(args, "--against")
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    tsv = "--tsv" in args
    args = [a for a in args if a != "--tsv"]
    if tsv and against is not None:
        print("--tsv と --against は同時に使えない", file=sys.stderr)
        return 2

    # <dat> --tsv と <dat> --against <tsv> は dat が1つ、位置引数だけなら1つか2つ
    ok = len(args) == 1 if (tsv or against is not None) else 1 <= len(args) <= 2
    if not ok:
        print(__doc__, file=sys.stderr)
        return 2

    fp_a = _read_dat(pathlib.Path(args[0]), "1つ目")
    if fp_a is None:
        return 2

    if against is not None:
        ref = pathlib.Path(against)
        if not ref.is_file():
            print(f"指紋のファイルが無い: {ref}", file=sys.stderr)
            return 2
        try:
            fp_b = load_tsv(ref.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"{ref}: {e}", file=sys.stderr)
            return 2
        return _report(fp_a, fp_b, against)

    if len(args) == 1:
        if tsv:
            print(dump(fp_a), end="")
        else:
            print(render(fp_a))
        return 0

    fp_second = _read_dat(pathlib.Path(args[1]), "2つ目")
    if fp_second is None:
        return 2
    return _report(fp_a, fp_second, None)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
