"""impl/23_loop_prefetch — 174段ループ (`retreatStep()`) に2段の先読みを入れる。

変数は1つ。C の `retreatStep()` のループ頭に、`experiments/lever_scan_2/patches/pf2.patch` の
2段の先読みを入れた（コードはパッチのまま、コメントだけを記録の実装として書き直した）。
32 個先の q で `pred_off[q]` を、16 個先の q で `pred[pred_off[q]]` を取り寄せる。
距離は記録 #20 の `predScatter` と同じで、調整していない。

⚠️ 先読みはヒントで、書く値を変えない。小さいフィクスチャで impl/22 と成果物がバイト一致する
ことまで見る。
`.py` / `.h` / `Makefile` は impl/22 とバイト同一。
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
from typing import Any

import pytest
from conftest import ROOT, impl_library, load_impl
from test_impl_22_in_memory import limited_run

IMPL_DIR = ROOT / "impl" / "23_loop_prefetch"
PREV_DIR = ROOT / "impl" / "22_in_memory"
PATCH = ROOT / "experiments" / "lever_scan_2" / "patches" / "pf2.patch"
SIGNATURE = "int retreatStep("


def c_code(text: str) -> str:
    """C からコメントを落とす。規約を説明した文が、その規約の語を含むため。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(ln.split("//", 1)[0] for ln in text.splitlines())


def code_only(text: str) -> list[str]:
    """コメントを落とし、空行と行末の空白を除いた行の並び。コメントの書き直しを無視して比べる。"""
    return [ln.rstrip() for ln in c_code(text).splitlines() if ln.strip()]


def function_body(csrc: str, signature: str) -> str:
    """関数の定義から、行頭の `}` (関数の終わり) までを返す。"""
    start = csrc.index(signature)
    end = csrc.index("\n}\n", start)
    return csrc[start : end + 2]


def c_source(directory: pathlib.Path) -> str:
    return (directory / "animal_shogi.c").read_text(encoding="utf-8")


def test_everything_but_the_c_is_byte_identical_to_impl_22() -> None:
    """★`.py` / `.h` / `Makefile` は impl/22 とバイト同一 (`-O2` のまま。Python も触らない)。"""
    for name in ("animal_shogi.py", "animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), (
            f"{name} が impl/22 と違う"
        )


def test_no_impl_env_needed() -> None:
    assert not (IMPL_DIR / "impl.env").exists(), "既定のビルド・実行コマンドで走るはず"


def test_the_c_is_impl_22_plus_the_pf2_patch(tmp_path: pathlib.Path) -> None:
    """★C のコード (コメントを除く) が「impl/22 ＋ `pf2.patch`」と一致すること。"""
    if shutil.which("patch") is None:
        pytest.skip("patch が無い")
    shutil.copy(PREV_DIR / "animal_shogi.c", tmp_path / "animal_shogi.c")
    with PATCH.open("rb") as f:
        done = subprocess.run(
            [
                "patch",
                "--forward",
                "--fuzz=0",
                "--no-backup-if-mismatch",
                "-p1",
                "-d",
                str(tmp_path),
            ],
            stdin=f,
            capture_output=True,
            check=False,
        )
    assert done.returncode == 0, f"pf2.patch が impl/22 に当たらない:\n{done.stdout!r}"
    expected = code_only((tmp_path / "animal_shogi.c").read_text(encoding="utf-8"))
    assert code_only(c_source(IMPL_DIR)) == expected


def test_only_retreat_step_changed() -> None:
    """★変わった C の関数は `retreatStep()` だけ (ほかの関数はコメントまでバイト同一)。"""
    new, old = c_source(IMPL_DIR), c_source(PREV_DIR)
    new_body, old_body = function_body(new, SIGNATURE), function_body(old, SIGNATURE)
    assert new_body != old_body
    assert new.replace(new_body, "") == old.replace(old_body, "")


def test_the_two_prefetches_check_the_range_before_reading() -> None:
    """★先読みは2つ。本当に読む値 (`frontier[i + k]`・`pred_off[q16]`) は、範囲を確かめて読む。"""
    body = "\n".join(code_only(function_body(c_source(IMPL_DIR), SIGNATURE)))
    assert body.count("__builtin_prefetch") == 2
    guard32 = body.index("if (i + 32 < hi)")
    assert guard32 < body.index("frontier[i + 32]") < body.index("&pred_off[q32]")
    assert body.index("if (q32 < n_all)") < body.index("&pred_off[q32]")
    guard16 = body.index("if (pred && i + 16 < hi)")
    assert guard16 < body.index("frontier[i + 16]")
    assert body.index("if (q16 < n_all)") < body.index("&pred[pred_off[q16]]")
    # 先読みは読むだけ (第2引数 0)。dtm / cnt / found は本処理だけが書く
    assert "__builtin_prefetch(&pred_off[q32], 0, 3)" in body
    assert "__builtin_prefetch(&pred[pred_off[q16]], 0, 3)" in body


@pytest.mark.parametrize("extra", [[], ["-Wextra"]])
def test_the_c_builds_without_warnings(tmp_path: pathlib.Path, extra: list[str]) -> None:
    """★`make animal_shogi.so` (`-Wall`) が通り、`-Wextra` を足しても警告を1つも出さないこと。"""
    if shutil.which("gcc") is None or shutil.which("make") is None:
        pytest.skip("gcc か make が無い")
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        shutil.copy(IMPL_DIR / name, tmp_path / name)
    if extra:
        cmd = ["gcc", "-O2", "-Wall", *extra, "-fPIC", "-shared", "animal_shogi.c", "-o", "x.so"]
    else:
        cmd = ["make", "animal_shogi.so"]
    done = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert done.returncode == 0, f"ビルドが失敗した:\n{done.stdout}\n{done.stderr}"
    assert "warning" not in done.stderr.lower(), f"警告が出ている:\n{done.stderr}"


# --------------------------------------------------------------------------
# 走らせて impl/22 と突き合わせる
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def paired(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    """impl/22 と impl/23 を、同じ上限・同じラウンド数で打ち切って後退解析まで回す。

    ⚠️ 実装を読み込むと前の実装の .so は閉じられるので、1つずつ最後まで回す。
    """
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    out: dict[str, dict[str, Any]] = {}
    for impl in ("22_in_memory", "23_loop_prefetch"):
        work = tmp_path_factory.mktemp(impl)
        out[impl] = limited_run(load_impl(impl, work, impl_library(impl)), work)
    return out


def test_the_artifacts_are_byte_identical_to_impl_22(paired: dict[str, dict[str, Any]]) -> None:
    """★後退解析まで回した成果物が impl/22 とバイト一致する (先読みは書く値を変えない)。"""
    da, db = paired["22_in_memory"]["work"] / "dat", paired["23_loop_prefetch"]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir())
    assert names == sorted(p.name for p in db.iterdir()), "ファイルの顔ぶれが違う"
    assert len(names) > 3, f"成果物が少なすぎる (テストが空振り): {names}"
    differ = [n for n in names if (da / n).read_bytes() != (db / n).read_bytes()]
    assert differ == [], f"バイトが違うファイルがある: {differ[:5]}"


def test_the_retreat_totals_agree_with_impl_22(paired: dict[str, dict[str, Any]]) -> None:
    """★手数別の行 (オラクル検証が見る行) が impl/22 と一致する。"""

    def totals(work: pathlib.Path) -> list[str]:
        text = (work / "kaiseki_log" / "kaizenkaiseki1.txt").read_text(encoding="utf-8")
        return [ln for ln in text.splitlines() if "盤面総数" in ln]

    a = totals(paired["22_in_memory"]["work"])
    assert a, "手数別の行が出ていない (テストが空振り)"
    assert a == totals(paired["23_loop_prefetch"]["work"])
    assert len(a) > 2, f"深さが1段しか進んでいない: {a}"
