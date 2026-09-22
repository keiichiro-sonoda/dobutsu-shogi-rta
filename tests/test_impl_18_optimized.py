"""impl/18_optimized — `-O0` をやめる（梯子1段目）。

記録 #17 までの `Makefile` は `gcc animal_shogi.c -o animal_shogi.so -Wall -fPIC -shared`
で、**`-O` が1つも付いていない＝`-O0`**。18記録ぶん、ローカル変数を毎回スタックに
書き戻すビルドで走ってきた。完走 435 秒のうち C が 375.8 秒（86.4%）。

⚠️ **このリポジトリで `Makefile` が前の版と違う最初の実装。** `baseline/` と
`impl/01`〜`17` の18個は全部同じハッシュで、既存テスト7本が「`Makefile` は
バイト同一」を固定している。うち5本（`test_impl_08/11/12/13/14/15`）は
「`-O2` は別の試行で1変数として測る」と、この記録を名指しで予告していた。

ここが見るのは「1変数になっていること」——`.c` / `.h` / `.py` が `#17` と
バイト同一で、`Makefile` の差が `-O<段>` 1つだけであること——と、
**その `Makefile` が実際に通ること**。等価性検査（`tests/test_*_equivalence.py`）は
`conftest.build_library()` が自前の `gcc -Wall -fPIC -shared`（＝`-O0`）で
ビルドするので、**`Makefile` を1行も通らない**。ここが唯一の砦になる。
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest
from conftest import ROOT

IMPL_DIR = ROOT / "impl" / "18_optimized"
PREV_DIR = ROOT / "impl" / "17_no_set"

# 門番 gate_18_opt で測った段。ここに無いフラグが入ったら、測っていないものを
# 記録に入れたことになる。-Ofast は浮動小数点が1つも無いので得るものがゼロ、
# -march=native は別のレバー（README の残りレバー表）。
MEASURED_FLAGS = ("-O1", "-O2", "-O3")


def makefile(path: pathlib.Path) -> str:
    return (path / "Makefile").read_text(encoding="utf-8")


def gcc_line(path: pathlib.Path) -> str:
    for line in makefile(path).splitlines():
        if "gcc" in line:
            return line.strip()
    raise AssertionError(f"{path}/Makefile に gcc の行が無い")


# --------------------------------------------------------------------------
# 1変数であること
# --------------------------------------------------------------------------


def test_everything_but_the_makefile_is_byte_identical_to_impl_17() -> None:
    """★C も .h も Python も #17 とバイト同一。動くのはビルドのフラグだけ。"""
    for name in ("animal_shogi.c", "animal_shogi.h", "animal_shogi.py"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), (
            f"{name} が #17 と違う。この記録のレバーは Makefile の1行だけ"
        )


def test_the_makefile_differs_by_exactly_one_optimization_flag() -> None:
    """★`Makefile` の差が `-O<段>` の1トークンだけであること。

    ⚠️ 行を足す・別のフラグを混ぜる・`-o` の出力先を変える、のどれも通さない。
    混ぜると次の記録との差分が2つになって帰属が取れない。
    """
    prev = makefile(PREV_DIR).splitlines()
    cur = makefile(IMPL_DIR).splitlines()
    assert len(prev) == len(cur), f"行数が変わっている: {len(prev)} → {len(cur)}"

    diff = [(a, b) for a, b in zip(prev, cur, strict=True) if a != b]
    assert len(diff) == 1, f"違う行が1つでない: {diff}"

    before, after = (d.split() for d in diff[0])
    added = [tok for tok in after if tok not in before]
    removed = [tok for tok in before if tok not in after]
    assert removed == [], f"消えたフラグがある: {removed}"
    assert len(added) == 1, f"足したフラグが1つでない: {added}"
    assert added[0] in MEASURED_FLAGS, (
        f"門番で測っていないフラグが入っている: {added[0]}（測ったのは {MEASURED_FLAGS}）"
    )
    # トークンの並びまで揃っていること（-O は単に1つ増えただけ）
    assert [tok for tok in after if tok != added[0]] == before


def test_no_impl_env_needed() -> None:
    """★既定のビルド・実行コマンドで走ること。

    ⚠️ `impl.env` で `BUILD_CMD` を差し替える手もあるが、`tools/run.sh` の
    `impl_sha256` は `find . -type f ! -name impl.env` なので、それだと
    #17 と #18 の `impl_sha256` が同じ値になる。記録の指し先が壊れる。
    """
    assert not (IMPL_DIR / "impl.env").exists(), "既定のビルド・実行コマンドで走るはず"


# --------------------------------------------------------------------------
# その Makefile が実際に通ること
# --------------------------------------------------------------------------


def test_the_makefile_builds_without_warnings(tmp_path: pathlib.Path) -> None:
    """★`make animal_shogi.so` が通り、警告を1つも出さないこと。

    ⚠️ 等価性検査は `conftest.build_library()` の自前の gcc 行（`-O0`）で
    ビルドするので、`Makefile` を1行も通らない。**この記録のレバーを
    実際に走らせているのはここだけ。**

    最適化を有効にすると `-O0` では出ない警告（`-Wmaybe-uninitialized` など）が
    出ることがある。18記録ぶん `-O0` だったので初めて露出する可能性があった。
    門番の [`logs/warnings.txt`](../experiments/gate_18_opt/logs/warnings.txt) では
    5腕とも `-Wall -Wextra` で警告ゼロだった。
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
    assert (work / "animal_shogi.so").exists(), ".so ができていない"
    assert "warning" not in done.stderr.lower(), f"警告が出ている:\n{done.stderr}"


def test_the_optimized_build_differs_from_the_o0_build(tmp_path: pathlib.Path) -> None:
    """★`-O` が本当に効いていること（`#17` のビルドとバイトが違う）。

    フラグを足したつもりで `Makefile` の書き方を間違えても `make` は通る。
    生成物が `-O0` のままでないことを直に見る。
    """
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    out = {}
    for name, path in (("o0", PREV_DIR), ("opt", IMPL_DIR)):
        work = tmp_path / name
        work.mkdir()
        for f in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
            shutil.copy(path / f, work / f)
        done = subprocess.run(
            ["make", "animal_shogi.so"], cwd=work, capture_output=True, text=True, check=False
        )
        assert done.returncode == 0, f"{name} の make が失敗した:\n{done.stderr}"
        out[name] = (work / "animal_shogi.so").read_bytes()
    assert out["o0"] != out["opt"], "最適化ありのビルドが #17 と同一。-O が効いていない"


def test_the_gcc_line_keeps_the_rest_of_the_flags() -> None:
    """★`-Wall -fPIC -shared` が残っていること。

    `-Wall` を落とすと警告が見えなくなり、`-fPIC -shared` を落とすと
    そもそも `.so` にならない。
    """
    line = gcc_line(IMPL_DIR)
    for flag in ("-Wall", "-fPIC", "-shared"):
        assert re.search(rf"(?<!\S){re.escape(flag)}(?!\S)", line), f"{flag} が消えている"
    assert "-march" not in line, "-march=native は別のレバー（README の残りレバー表）"
    assert "-Ofast" not in line, "-Ofast は浮動小数点が1つも無いので得るものがゼロ"
    assert "-Wextra" not in line, "-Wextra は門番で見るだけ。入れると差分が2つになる"
