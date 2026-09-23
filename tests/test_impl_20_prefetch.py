"""impl/20_prefetch — 先読み (prefetch) 4か所と `moves = NULL;`。

`experiments/lever_scan/` (記録ではない) で、先読みが後退解析 −48.07 秒・全探索 −13.47 秒と
いちばん大きく効いた。この記録はその `pf.patch` の**コードをそのまま**入れ、コメントだけを
記録の実装として書き直したもの。距離 (16、`predScatter` は 16 / 32) も変えていない。

| 場所 | 段 | 形 |
|---|---|---|
| `indexBuild()` | P1 | 16 個先のキーのスロットを先読みしながら挿入 |
| `nextBoardIndexNormal()` | P2 | 全後続のスロットを先読みしてから探査 |
| `nextBoardSeenNormal()` | F1 | 全後続のスロットを先読みしてから挿入 |
| `predScatter()` | P4_scatter | 2段。32 本先で `pred_off`、16 本先で `pred` の書き込み先 |

同乗させた `moves = NULL;` は CLAUDE.md「次の実装で必ず直すもの」の1件。#19 は、C に足した行
(`gatherPacked` / `gatherDraws`) が全探索では実行されないことを予測⑤の前提にしていたので見送った。
#20 の先読みは C の F1 経路 (`nextBoardSeenNormal`) にも入るので、見送る理由がない。

⚠️ **先読みはヒントで、書く値は変わらない。** ここでは小さいフィクスチャで impl/19 と成果物が
**バイト一致**することまで見る (本走の検査も `results/20_prefetch/bytecompare.txt` で同じ形)。
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest
from conftest import ROOT, impl_library, load_impl, run_forward, run_retreat

IMPL_DIR = ROOT / "impl" / "20_prefetch"
PREV_DIR = ROOT / "impl" / "19_c_gather"
PATCH = ROOT / "experiments" / "lever_scan" / "patches" / "pf.patch"

DECL_19 = "int i, j, dst, own_num, own_p, *moves, moves_num, src_mod16, dst_mod16;"
DECL_20 = "int i, j, dst, own_num, own_p, *moves = NULL, moves_num, src_mod16, dst_mod16;"

SMALL_BOARD_NUM_MAX = 2000
FORWARD_ROUNDS = 7


def c_code(text: str) -> str:
    """C からコメントを落とす。規約を説明した文が、その規約の語を含むため。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(ln.split("//", 1)[0] for ln in text.splitlines())


def code_only(text: str) -> list[str]:
    """コメントを落とし、空行と行末の空白を除いた行の並び。コメントの書き直しを無視して比べる。"""
    return [ln.rstrip() for ln in c_code(text).splitlines() if ln.strip()]


def function_body(csrc: str, signature: str) -> str:
    """関数の定義から、行頭の `}` (関数の終わり) までを返す。

    ⚠️ 空行で切らない。コメントを落とすとコメント行が空行になるので、関数の途中で切れる。
    """
    start = csrc.index(signature)
    end = csrc.index("\n}\n", start)
    return csrc[start : end + 2]


# --------------------------------------------------------------------------
# 構造
# --------------------------------------------------------------------------


def test_everything_but_the_c_is_byte_identical_to_impl_19() -> None:
    """★`.py`・`.h`・`Makefile` は impl/19 とバイト同一 (`-O2` のまま)。"""
    for name in ("animal_shogi.py", "animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), (
            f"{name} が impl/19 と違う。この記録で動かすのは C の先読みと moves だけ"
        )


def test_no_impl_env_needed() -> None:
    assert not (IMPL_DIR / "impl.env").exists(), "既定のビルド・実行コマンドで走るはず"


def test_the_c_is_impl_19_plus_the_prefetch_patch_and_moves(tmp_path: pathlib.Path) -> None:
    """★C のコードが「impl/19 ＋ `pf.patch` ＋ `moves` の初期化」と一致すること。

    コメントは記録の実装として書き直したので比べない。コードの行だけを並べて比べると,
    ①先読み4か所と `moves = NULL;` 以外を動かしていないことと,
    ②lever_scan で測ったのと同じコードであることを, 1本で固定できる。
    """
    if shutil.which("patch") is None:
        pytest.skip("patch が無い")
    work = tmp_path / "ref"
    work.mkdir()
    for name in ("animal_shogi.c", "animal_shogi.h"):
        shutil.copy(PREV_DIR / name, work / name)
    with PATCH.open("rb") as f:
        done = subprocess.run(
            ["patch", "--forward", "--fuzz=0", "-p1", "-d", str(work)],
            stdin=f,
            capture_output=True,
            check=False,
        )
    assert done.returncode == 0, f"pf.patch が impl/19 に当たらない:\n{done.stdout!r}"
    ref = (work / "animal_shogi.c").read_text(encoding="utf-8")
    assert ref.count(DECL_19) == 1, "impl/19 の moves の宣言が見つからない (テストが空振り)"
    ref = ref.replace(DECL_19, DECL_20)
    cur = (IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8")
    assert code_only(cur) == code_only(ref), "先読み4か所と moves 以外のコードが動いている"


def test_there_are_five_prefetches() -> None:
    """★先読みは4か所・5個 (`predScatter` だけ2段)。場所を減らしも増やしもしない。"""
    csrc = c_code((IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8"))
    assert csrc.count("__builtin_prefetch(") == 5
    for sig, n in (
        ("int indexBuild(", 1),
        ("int nextBoardIndexNormal(", 1),
        ("int nextBoardSeenNormal(", 1),
        ("int predScatter(", 2),
    ):
        assert function_body(csrc, sig).count("__builtin_prefetch(") == n, (
            f"{sig} の先読みが {n} 個でない"
        )


def test_moves_is_initialized() -> None:
    """★`moves` が宣言で NULL に初期化されていること。

    `tests/test_impl_19_c_gather.py` の「まだ残っている」固定の裏返し
    (あちらは凍結した impl/19 を見ているので、そのまま通り続ける)。
    """
    csrc = c_code((IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8"))
    assert DECL_20 in csrc, "moves が宣言で初期化されていない"
    assert DECL_19 not in csrc


def test_the_scatter_prefetch_checks_the_range_before_reading() -> None:
    """★`predScatter` の 16 本先の `pred_off[q16]` は先読みではなく本当に読む。

    範囲外を読まないよう `q16 < n_all` を確かめてから読むこと。`succ[e + 16]` / `succ[e + 32]` も
    本当に読むので、`n_edges` を越えない検査が要る。
    """
    body = function_body(
        c_code((IMPL_DIR / "animal_shogi.c").read_text(encoding="utf-8")), "int predScatter("
    )
    assert "if (q16 < n_all)" in body, "pred_off[q16] を範囲の検査なしに読んでいる"
    assert "if (e + 16 < n_edges)" in body and "if (e + 32 < n_edges)" in body, (
        "succ の先を n_edges の検査なしに読んでいる"
    )


def test_the_makefile_builds_without_warnings(tmp_path: pathlib.Path) -> None:
    """★`make animal_shogi.so` が通り、警告を1つも出さないこと。

    等価性検査は `conftest.build_library()` の自前の gcc 行 (`-O0`) でビルドするので、
    `Makefile` の `-O2` を通らない。`-O2` で初めて出る警告がないことはここで見る。
    """
    if shutil.which("gcc") is None or shutil.which("make") is None:
        pytest.skip("gcc か make が無い")
    work = tmp_path / "build"
    work.mkdir()
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        shutil.copy(IMPL_DIR / name, work / name)
    done = subprocess.run(
        ["make", "animal_shogi.so"], cwd=work, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, f"make が失敗した:\n{done.stdout}\n{done.stderr}"
    assert "warning" not in done.stderr.lower(), f"警告が出ている:\n{done.stderr}"


# --------------------------------------------------------------------------
# 走らせて impl/19 と突き合わせる
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def retreat_pair(tmp_path_factory: pytest.TempPathFactory) -> dict[str, pathlib.Path]:
    """同じ打ち切り `dat/` を両方に配って、後退解析を最後まで回す。

    ⚠️ 実装ごとに全探索を回してはいけない (打ち切った時点の集合が変わる)。
    入力を1つに固定するのは `tests/test_retreat_analysis_equivalence.py` と同じ。
    """
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    src = tmp_path_factory.mktemp("fixture20")
    module = load_impl("19_c_gather", src, impl_library("19_c_gather"))
    run_forward(module, src, FORWARD_ROUNDS, SMALL_BOARD_NUM_MAX)

    out: dict[str, pathlib.Path] = {}
    for impl in ("19_c_gather", "20_prefetch"):
        work = tmp_path_factory.mktemp(impl)
        module = load_impl(impl, work, impl_library(impl))
        for path in sorted((src / "dat").iterdir()):
            shutil.copy(path, work / "dat" / path.name)
        vars(module)["BOARD_NUM_MAX"] = SMALL_BOARD_NUM_MAX
        run_retreat(module, work)
        out[impl] = work
    return out


def test_the_artifacts_are_byte_identical_to_impl_19(
    retreat_pair: dict[str, pathlib.Path],
) -> None:
    """★成果物が impl/19 と**バイト一致**すること。先読みは書く値も順序も変えない。"""
    a, b = retreat_pair["19_c_gather"] / "dat", retreat_pair["20_prefetch"] / "dat"
    names = sorted(p.name for p in a.iterdir())
    assert names == sorted(p.name for p in b.iterdir()), "ファイルの顔ぶれが違う"
    assert len(names) > 3, f"成果物が少なすぎる (テストが空振り): {names}"
    differ = [n for n in names if (a / n).read_bytes() != (b / n).read_bytes()]
    assert differ == [], f"バイトが違うファイルがある: {differ[:5]}"
