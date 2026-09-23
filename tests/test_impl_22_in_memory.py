"""impl/22_in_memory — 中間ファイルをやめ、全探索から後退解析までメモリで受け渡す。

#21 までの全探索は、同じプロセスがあとで読み戻して消すファイルを書いていた。

- `unexplored###.bin` (待ち行列): F5 で書き、次のラウンドの F0 で読んで消していた
  → #22 はメモリの待ち行列 (`queue`)
- `unknown###.bin` (全探索の未知): F2 で末尾を読み直して継ぎ足し、P0 で読んで消していた
  → #22 はメモリの配列 (`uk_all`)
- `win001te_*` / `lose000te_*`: F6 で書き (成果物)、P0 で読み戻していた
  → #22 も F6 はそのまま書く。P0 は読み戻さず、メモリに持っていたものを詰める

C (`.c` / `.h`) と `Makefile` は #21 とバイト同一。変えたのは Python だけ。

⚠️ **待ち行列の区切り方は、展開の順を変えない。** 先に入れたものから取り出すので、
何件ずつ取り出しても、展開の順・未知の並び・終端の並びは同じになる。記録にする前に、
区切り方だけが違う2腕を門番 (`experiments/gate_22_in_memory/`) で比べ、`chunk` を採った
(区切らない `whole` は J ＝ forward_total ＋ P0 が 2.48 秒遅かった)。
- `chunk` (500万件ずつ): この実装そのもの
- `whole` (区切らない): この実装に `patches/whole.patch` を当てたもの (採らなかった腕)

`chunk` は #21 とラウンドの分け方まで同じになるので、小さく打ち切った走行で #21 と
ラウンドごとに突き合わせられる。`whole` は1ラウンドが幅優先の1層になるので、`chunk` と
「展開した順が前方一致する」ことで突き合わせる。

⚠️ **P0 の詰め方 (後退解析の採番順) は変えない。** #21 の P0 は `unknown###.bin` を番号順に
読んで末尾のファイルから詰めていた。そのファイルは U (未知を展開順に並べたもの) を先頭から
`BOARD_NUM_MAX` ちょうどで区切ったものだったので、#22 は U を同じく区切って末尾の塊から詰める。
"""

from __future__ import annotations

import ast
import pathlib
import re
import shutil
import subprocess
import types
from array import array
from collections.abc import Callable
from typing import Any

import pytest
from conftest import ROOT, chdir, impl_library, load_impl

IMPL_DIR = ROOT / "impl" / "22_in_memory"
PREV_DIR = ROOT / "impl" / "21_hugepages"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = PREV_DIR / "animal_shogi.py"
WHOLE_PATCH = ROOT / "experiments" / "gate_22_in_memory" / "patches" / "whole.patch"

# 変えた関数・足した関数・消した関数。これ以外は impl/21 から1バイトも動かさない
CHANGED = {"searchNext", "searchAll", "flushTerminalBoards", "loadForwardResult"}
ADDED = {"forwardInit", "queuePush"}
REMOVED = {"updateUKFile", "buildSeenBoards", "loadAllUnknownBoards", "appendFamily"}

# 塊を小さくして、待ち行列と未知の区切りを何度も起こす。本番は 5,000,000
SMALL_BOARD_NUM_MAX = 2000
# 打ち切るラウンド数。M = 2000 で待ち行列が数十の塊に育つところまで
ROUNDS = 40

# 打ち切った走行1本ぶんの記録 (実装 → 名前 → 値)
Paired = dict[str, dict[str, Any]]

COUNTS = (
    "n_in", "n_win", "n_lose", "n_uk", "n_new_pre", "n_new_uniq", "n_new_post",
    "n_seen", "n_rehash", "n_catch_total", "n_try_total",
)  # fmt: skip


def top_level(path: pathlib.Path, kind: type) -> dict[str, str]:
    """モジュール直下の関数 (または代入) を、名前 → ソースそのもの で返す。"""
    text = path.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for node in ast.parse(text).body:
        if not isinstance(node, kind):
            continue
        names = (
            [node.name]
            if isinstance(node, ast.FunctionDef)
            else [t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)]
        )
        segment = ast.get_source_segment(text, node)
        assert segment is not None
        for name in names:
            out[name] = segment
    return out


def statements(segment: str) -> list[str]:
    """コメントと空行を落とした行の並び。コメントの書き直しを無視して文だけを比べる。"""
    out = []
    for line in segment.splitlines():
        code = line.split("#", 1)[0].rstrip()
        if code.strip():
            out.append(code)
    return out


def patched_source(tmp: pathlib.Path) -> pathlib.Path:
    """impl/22 に `whole.patch` を当てた `animal_shogi.py` を作る (門番の `whole` 腕と同じもの)。"""
    if shutil.which("patch") is None:
        pytest.skip("patch が無い")
    tmp.mkdir(parents=True, exist_ok=True)
    shutil.copy(SOURCE, tmp / "animal_shogi.py")
    with WHOLE_PATCH.open("rb") as f:
        done = subprocess.run(
            ["patch", "--forward", "--fuzz=0", "--no-backup-if-mismatch", "-p1", "-d", str(tmp)],
            stdin=f,
            capture_output=True,
            check=False,
        )
    assert done.returncode == 0, done.stdout.decode() + done.stderr.decode()
    return tmp / "animal_shogi.py"


# --------------------------------------------------------------------------
# 構造
# --------------------------------------------------------------------------


def test_the_c_and_the_build_are_byte_identical_to_impl_21() -> None:
    """★`.c` / `.h` / `Makefile` は impl/21 とバイト同一 (変えたのは Python だけ)。"""
    for name in ("animal_shogi.c", "animal_shogi.h", "Makefile"):
        assert (IMPL_DIR / name).read_bytes() == (PREV_DIR / name).read_bytes(), (
            f"{name} が impl/21 と違う"
        )


def test_no_impl_env_needed() -> None:
    assert not (IMPL_DIR / "impl.env").exists(), "既定のビルド・実行コマンドで走るはず"


def test_only_the_planned_functions_changed() -> None:
    """★変えた関数は決めた集合だけ。後退解析は P0 (`loadForwardResult`) 以外を触らない。"""
    old = top_level(PREV_SOURCE, ast.FunctionDef)
    new = top_level(SOURCE, ast.FunctionDef)
    assert set(new) - set(old) == ADDED
    assert set(old) - set(new) == REMOVED
    changed = {name for name in set(old) & set(new) if old[name] != new[name]}
    assert changed == CHANGED
    assert new["retreatAnalysis"] == old["retreatAnalysis"]


def test_the_profile_columns_and_the_retreat_marks_are_unchanged() -> None:
    """★`forward.tsv` の列と後退解析の境界は過去の記録と揃えたまま (F0・F2・F5・S も残す)。"""
    old = top_level(PREV_SOURCE, ast.Assign)
    new = top_level(SOURCE, ast.Assign)
    for name in (
        "PROFILE_MARKS", "PROFILE_COUNTS", "PROFILE_TIMES", "PROFILE_COLUMNS",
        "RETREAT_MARKS", "RETREAT_SPANS", "BOARD_NUM_MAX", "INITIAL_BOARD",
    ):  # fmt: skip
        assert new[name] == old[name], f"{name} が impl/21 と違う"
    assert "UNEXP_PATH_FORMAT" not in new, "未探索ファイルのパスが残っている"
    assert "seen_boards" not in new, "buildSeenBoards の名残が残っている"


def test_the_expansion_statements_are_unchanged() -> None:
    """★F1 (展開) の文は #21 とバイト同一。`chunk` 腕の F1 を対照にするため。

    `arr = array("Q", unexp_boards)` の写しも残してある (外すのは別のレバー)。
    """

    def f1(path: pathlib.Path) -> list[str]:
        body = top_level(path, ast.FunctionDef)["searchNext"]
        start = body.index('_profMark("F1_begin")')
        end = body.index('_profMark("F1")', start)
        return statements(body[start:end])

    assert f1(SOURCE) == f1(PREV_SOURCE)
    assert any('array("Q", unexp_boards)' in ln for ln in f1(SOURCE))


def test_the_forward_search_touches_no_file() -> None:
    """★全探索は成果物 (F6) 以外のファイルを読み書きしない。P0 も読み戻さない。"""
    funcs = top_level(SOURCE, ast.FunctionDef)
    for name in ("searchNext", "queuePush", "forwardInit", "loadForwardResult"):
        code = "\n".join(statements(funcs[name]))
        for word in ("readBoards", "writeBoards", "os.remove", "os.path.exists", "_PATH_FORMAT"):
            assert word not in code, f"{name} に {word} が残っている"
    code = "\n".join(statements(funcs["searchAll"]))
    for word in ("readBoards", "writeBoards", "os.remove", "_PATH_FORMAT"):
        assert word not in code, f"searchAll に {word} が残っている"


def test_the_whole_patch_changes_only_queue_push(tmp_path: pathlib.Path) -> None:
    """★門番の2腕 (`chunk` / `whole`) の差は `queuePush()` の1関数だけ。"""
    patched = patched_source(tmp_path / "whole")
    chunk = top_level(SOURCE, ast.FunctionDef)
    whole = top_level(patched, ast.FunctionDef)
    assert set(whole) == set(chunk)
    assert {n for n in whole if whole[n] != chunk[n]} == {"queuePush"}
    assert top_level(SOURCE, ast.Assign) == top_level(patched, ast.Assign)
    assert "BOARD_NUM_MAX" in chunk["queuePush"]
    assert "BOARD_NUM_MAX" not in whole["queuePush"]


def test_the_makefile_builds_without_warnings(tmp_path: pathlib.Path) -> None:
    """★`make animal_shogi.so` が通り、警告を1つも出さないこと。"""
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
# 入口
# --------------------------------------------------------------------------


def load22(work: pathlib.Path, source: pathlib.Path | None = None) -> types.ModuleType:
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    return load_impl("22_in_memory", work, impl_library("22_in_memory"), source)


def test_a_non_empty_dat_is_refused(tmp_path: pathlib.Path) -> None:
    """★途中の `dat/` から再開しない。空でなければ入口で止める。"""
    work = tmp_path / "w"
    module = load22(work)
    (work / "dat" / "unexplored000.bin").write_bytes(b"")
    with chdir(work), pytest.raises(RuntimeError, match="空でない"):
        module.forwardInit()
    shutil.rmtree(work / "dat")
    with chdir(work), pytest.raises(RuntimeError, match="作成してください"):
        module.forwardInit()


def test_the_initial_board_is_in_the_seen_table_from_the_start(tmp_path: pathlib.Path) -> None:
    """★初期局面は `forwardInit()` の直後から発見済み表に入っている。

    #21 までは、1ラウンド目のあとで `buildSeenBoards()` が `unknown000.bin` (中身は初期局面1つ)
    を読んで入れるのが唯一の経路だった。入れ忘れると、4手で戻ってきた初期局面を
    「初見」としてもう一度積み、件数がずれる。
    """
    work = tmp_path / "w"
    module = load22(work)
    with chdir(work):
        module.forwardInit()
    assert module.seenCount() == 1
    assert module.seenContains(module.INITIAL_BOARD) == 1
    assert [list(a) for a in module.queue] == [[module.INITIAL_BOARD]]
    assert len(module.uk_all) == len(module.catch_wins) == len(module.try_loses) == 0


def test_p0_cuts_u_at_board_num_max_and_packs_from_the_last_chunk(tmp_path: pathlib.Path) -> None:
    """★P0 は U を `BOARD_NUM_MAX` ちょうどで区切り、**末尾の塊から**詰める。続けて終端の2本。

    末尾の塊が半端 (10 件を 4 件ずつ → 4, 4, 2) でも、区切りは先頭から数える。
    詰め終えた3本は手放す (P1 の索引より前)。
    """
    work = tmp_path / "w"
    module = load22(work)
    vars(module)["BOARD_NUM_MAX"] = 4
    vars(module)["uk_all"] = array("Q", range(10))
    vars(module)["catch_wins"] = array("Q", [100, 101])
    vars(module)["try_loses"] = array("Q", [200])
    with chdir(work):
        packed, n_uk, n_win, n_lose = module.loadForwardResult()
    assert list(packed) == [8, 9, 4, 5, 6, 7, 0, 1, 2, 3, 100, 101, 200]
    assert (n_uk, n_win, n_lose) == (10, 2, 1)
    assert module.uk_all is None
    assert len(module.catch_wins) == len(module.try_loses) == 0
    with chdir(work), pytest.raises(RuntimeError, match="メモリに無い"):
        module.loadForwardResult()


# --------------------------------------------------------------------------
# chunk 腕と #21 を、打ち切った走行で突き合わせる
# --------------------------------------------------------------------------


def snapshot(dat: pathlib.Path, pattern: str) -> list[bytes]:
    return [p.read_bytes() for p in sorted(dat.glob(pattern))]


def limited_run(module: types.ModuleType, work: pathlib.Path) -> dict[str, Any]:
    """`searchAll()` を ROUNDS ラウンドで打ち切り、そのまま `retreatAnalysis()` まで回す。

    ラウンドごとの件数 (`forward.tsv` の件数の列と同じ値) と、P0 の直前の状態
    (`dat/` のファイルとメモリの中身) と、P0 が詰めた `packed` を拾って返す。
    """
    counts: list[dict[str, int]] = []
    got: dict[str, Any] = {"counts": counts, "work": work}
    real_next = module.searchNext
    real_load = module.loadForwardResult

    def limited() -> bool:
        flag = bool(real_next())
        counts.append({k: module._prof.get(k, 0) for k in COUNTS})
        return flag or len(counts) >= ROUNDS

    def load() -> Any:
        dat = work / "dat"
        got["unexplored"] = snapshot(dat, "unexplored*.bin")
        got["unknown"] = snapshot(dat, "unknown*.bin")
        got["win"] = snapshot(dat, "win001te_*.bin")
        got["lose"] = snapshot(dat, "lose000te_*.bin")
        if "queue" in vars(module):
            got["queue"] = [a.tobytes() for a in module.queue]
            got["uk_all"] = array("Q", module.uk_all)
            got["catch_wins"] = module.catch_wins.tobytes()
            got["try_loses"] = module.try_loses.tobytes()
        got["tbn"] = (module.tbn_uk, module.tbn_win, module.tbn_lose)
        out = real_load()
        got["packed"] = out[0].tobytes()
        got["n"] = out[1:]
        return out

    vars(module)["searchNext"] = limited
    vars(module)["loadForwardResult"] = load
    vars(module)["BOARD_NUM_MAX"] = SMALL_BOARD_NUM_MAX
    with chdir(work):
        module.searchAll()
        module.retreatAnalysis()
    got["module"] = module
    return got


@pytest.fixture(scope="module")
def paired(tmp_path_factory: pytest.TempPathFactory) -> Paired:
    """#21 と #22 (chunk 腕) を、同じ ROUNDS で打ち切って後退解析まで回す。

    ⚠️ 実装を読み込むと前の実装の .so は閉じられるので、#21 は全部済ませてから #22 を読む。
    """
    if shutil.which("gcc") is None:
        pytest.skip("gcc が無い")
    out: Paired = {}
    work = tmp_path_factory.mktemp("impl21")
    module = load_impl("21_hugepages", work, impl_library("21_hugepages"))
    out["21"] = limited_run(module, work)
    work = tmp_path_factory.mktemp("chunk")
    out["chunk"] = limited_run(load22(work), work)
    return out


def test_the_chunk_arm_takes_the_same_rounds_as_impl_21(paired: Paired) -> None:
    """★`chunk` 腕はラウンドの分け方まで #21 と同じ (件数の列が全ラウンド一致)。

    門番の止める条件②が本番の74ラウンドで見るのと同じものを、小さく見る。
    """
    a, b = paired["21"]["counts"], paired["chunk"]["counts"]
    assert len(a) == ROUNDS, "打ち切る前に探索が終わった (テストが空振り)"
    assert a == b
    assert max(r["n_in"] for r in a) == SMALL_BOARD_NUM_MAX, "塊の上限に届いていない (空振り)"


def test_the_queue_chunks_are_what_impl_21_had_in_unexplored_files(paired: Paired) -> None:
    """★`chunk` 腕の待ち行列の塊は、#21 の `unexplored###.bin` の並びとバイト一致する。"""
    files = paired["21"]["unexplored"]
    assert len(files) > 2, "未探索ファイルが割れていない (テストが空振り)"
    assert paired["chunk"]["queue"] == files
    assert paired["chunk"]["unexplored"] == [], "chunk 腕が未探索ファイルを書いている"


def test_u_cut_at_board_num_max_is_what_impl_21_had_in_unknown_files(paired: Paired) -> None:
    """★U を `BOARD_NUM_MAX` ちょうどで区切ったものが、#21 の `unknown###.bin` の並びになる。

    #21 の `updateUKFile()` は末尾のファイルを読み直して継ぎ足し、上限を超えたら2つに割っていた。
    1ラウンドの未知が上限以下なので3つ以上の分割は起きず、結果は「先頭から上限ずつ」になる。
    """
    files = paired["21"]["unknown"]
    assert len(files) > 2, "未知ファイルが割れていない (テストが空振り)"
    u = paired["chunk"]["uk_all"]
    m = SMALL_BOARD_NUM_MAX
    assert [u[i : i + m].tobytes() for i in range(0, len(u), m)] == files
    assert paired["chunk"]["unknown"] == [], "chunk 腕が未知ファイルを書いている"


def test_the_terminal_boards_are_kept_and_written_the_same(paired: Paired) -> None:
    """★F6 の成果物は #21 とバイト一致し、P0 まで同じ並びをメモリに持っている。"""
    a, b = paired["21"], paired["chunk"]
    assert a["win"] and a["lose"], "終端のファイルが無い (テストが空振り)"
    assert a["win"] == b["win"]
    assert a["lose"] == b["lose"]
    assert b["catch_wins"] == b"".join(a["win"])
    assert b["try_loses"] == b"".join(a["lose"])
    assert a["tbn"] == b["tbn"]


def test_p0_packs_the_same_bytes_as_impl_21(paired: Paired) -> None:
    """★P0 の `packed` (後退解析の採番順) が #21 とバイト一致する。"""
    a, b = paired["21"], paired["chunk"]
    assert a["n"] == b["n"]
    assert a["packed"] == b["packed"]
    module = b["module"]
    assert module.uk_all is None, "P0 のあとも U を持っている"
    assert len(module.catch_wins) == len(module.try_loses) == 0, "P0 のあとも終端を持っている"


def test_the_artifacts_are_byte_identical_to_impl_21(paired: Paired) -> None:
    """★後退解析まで回した成果物が #21 とバイト一致する (#21 側に残る作業ファイルは除く)。"""
    da, db = paired["21"]["work"] / "dat", paired["chunk"]["work"] / "dat"
    names = sorted(p.name for p in da.iterdir() if not p.name.startswith("unexplored"))
    assert names == sorted(p.name for p in db.iterdir()), "ファイルの顔ぶれが違う"
    assert len(names) > 3, f"成果物が少なすぎる (テストが空振り): {names}"
    differ = [n for n in names if (da / n).read_bytes() != (db / n).read_bytes()]
    assert differ == [], f"バイトが違うファイルがある: {differ[:5]}"


def test_the_logs_agree_with_impl_21(paired: Paired) -> None:
    """★サブログと手数別の行が #21 と一致する。

    サブログで落とすのは、#21 だけが出していたファイル名の行 (「… を探索」) と、`searchAll()` が
    ラウンドごとに出す時刻と経過時間の行だけ。件数も順序も潰さない。
    """
    wa, wb = paired["21"]["work"], paired["chunk"]["work"]
    clock = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$|経過$")

    def sub(work: pathlib.Path) -> list[str]:
        text = (work / "kaiseki_log" / "kaiseki_log7.txt").read_text(encoding="utf-8")
        return [
            ln for ln in text.splitlines() if not ln.endswith(" を探索") and not clock.search(ln)
        ]

    def totals(work: pathlib.Path) -> list[str]:
        text = (work / "kaiseki_log" / "kaizenkaiseki1.txt").read_text(encoding="utf-8")
        return [ln for ln in text.splitlines() if "盤面総数" in ln]

    assert sub(wa) == sub(wb)
    assert totals(wa) == totals(wb)
    assert totals(wb), "手数別の行が出ていない (テストが空振り)"


def test_the_summaries_keep_their_rows(paired: Paired) -> None:
    """★要約ファイルの行は #21 と同じ顔ぶれ (F0・F2・F5・S・release_wl も残す)。"""

    def rows(work: pathlib.Path, name: str) -> dict[str, str]:
        text = (work / "kaiseki_log" / name).read_text(encoding="utf-8")
        return dict(ln.split("\t", 1) for ln in text.splitlines())

    for name in ("forward_summary.tsv", "retreat_summary.tsv"):
        keys = [list(rows(paired[k]["work"], name)) for k in ("21", "chunk")]
        assert keys[0] == keys[1], f"{name} の行が違う"
    assert float(rows(paired["chunk"]["work"], "forward_summary.tsv")["S"]) == 0.0


# --------------------------------------------------------------------------
# whole (採らなかった腕) と chunk (この実装): 区切りは展開の順を変えない
# --------------------------------------------------------------------------

# whole を何層回すか。次の層が SMALL_BOARD_NUM_MAX より大きくなるところで止める
WHOLE_LAYERS = 8


def run_rounds(
    module: types.ModuleType, work: pathlib.Path, until: Callable[[int, int], bool]
) -> list[int]:
    """`forwardInit()` のあと、`until(展開した総数, ラウンド数)` が真になるまで回す。"""
    n_in: list[int] = []
    vars(module)["BOARD_NUM_MAX"] = SMALL_BOARD_NUM_MAX
    with chdir(work):
        module.forwardInit()
        while not until(sum(n_in), len(n_in)):
            assert not module.searchNext(), "探索が終わってしまった"
            n_in.append(module._prof["n_in"])
    return n_in


def state(module: types.ModuleType) -> dict[str, list[int]]:
    queue: list[int] = []
    for chunk in module.queue:
        queue.extend(chunk)
    return {
        "uk": list(module.uk_all),
        "win": list(module.catch_wins),
        "lose": list(module.try_loses),
        "queue": queue,
    }


def test_whole_and_chunk_expand_in_the_same_order(tmp_path_factory: pytest.TempPathFactory) -> None:
    """★`whole` を k 層、`chunk` をそれより少し多く展開したところで止めて、並びが前方一致すること。

    展開した局面の並びは、クラス (未知・1手勝ち・0手負け) ごとの前方一致で見る。
    `chunk` が余分に展開したのは、`whole` の待ち行列の先頭から (展開の順が同じなら) で、
    `chunk` の待ち行列は `whole` の待ち行列の残りから始まる。
    """
    work = tmp_path_factory.mktemp("whole")
    whole = load22(work, patched_source(tmp_path_factory.mktemp("whole_src")))
    layers = run_rounds(whole, work, lambda _e, r: r >= WHOLE_LAYERS)
    w = state(whole)
    e_w = sum(layers)
    assert layers[:2] == [1, 4], f"1層目・2層目が初期局面と4つの後続になっていない: {layers[:3]}"
    assert len(w["queue"]) > SMALL_BOARD_NUM_MAX, "次の層が小さすぎる (テストが空振り)"

    work = tmp_path_factory.mktemp("chunk2")
    chunk = load22(work)
    rounds = run_rounds(chunk, work, lambda e, _r: e >= e_w + 1)
    c = state(chunk)
    e_c = sum(rounds)
    extra = e_c - e_w
    assert 0 < extra <= len(w["queue"]), (e_w, e_c, len(w["queue"]))
    assert max(rounds) == SMALL_BOARD_NUM_MAX, "chunk が区切られていない (テストが空振り)"

    # 展開した局面は、クラスごとに前方一致する
    for key in ("uk", "win", "lose"):
        assert c[key][: len(w[key])] == w[key], f"{key} が前方一致しない"
    # chunk が余分に展開したのは whole の待ち行列の先頭 extra 件で、クラスごとの並びも同じ
    ahead = w["queue"][:extra]
    added = {key: c[key][len(w[key]) :] for key in ("uk", "win", "lose")}
    assert sum(len(v) for v in added.values()) == extra
    for key, got in added.items():
        members = set(got)
        assert [b for b in ahead if b in members] == got, f"{key} の余分の並びが違う"
    # chunk の待ち行列は whole の待ち行列の残りから始まる
    rest = w["queue"][extra:]
    assert c["queue"][: len(rest)] == rest
    # 発見済み表は4つ (未知・終端2本・待ち行列) の和で、互いに素 (whole の .so はもう閉じている)
    union: set[int] = set()
    for key in ("uk", "win", "lose", "queue"):
        part = set(c[key])
        assert len(part) == len(c[key]) and not (union & part), f"{key} が重なっている"
        union |= part
    assert chunk.seenCount() == len(union)
    missing = [b for b in union if not chunk.seenContains(b)]
    assert missing == [], f"表に入っていない盤面がある: {missing[:3]}"


def test_whole_takes_one_breadth_first_layer_per_round(tmp_path: pathlib.Path) -> None:
    """★`whole` の待ち行列は常に1本で、1ラウンドが前のラウンドの初見の後続の全部になる。"""
    work = tmp_path / "w"
    module = load22(work, patched_source(tmp_path / "whole_src"))
    news: list[int] = []
    vars(module)["BOARD_NUM_MAX"] = SMALL_BOARD_NUM_MAX
    with chdir(work):
        module.forwardInit()
        for _ in range(6):
            module.searchNext()
            assert len(module.queue) == 1
            news.append(module._prof["n_new_post"])
            assert len(module.queue[0]) == news[-1]
    assert max(news) > SMALL_BOARD_NUM_MAX, "層が塊の上限を超えていない (テストが空振り)"
