"""tools/rebuild_forward_fixture.py — 完走した dat/ から全探索直後の状態を組み直す。

記録 #6 の門番 G1 で使う。全規模の後退解析だけを走らせたいが、その入力
(全探索が終わった直後の dat/) は後退解析自身が消してしまっている。

小さいフィクスチャで「完走 → 組み直し → 3群が元通り」までを通しで確かめる。
実物では 40分の全探索を1本回す代わりになるので、ここが間違っていると
門番が別物を検査することになる。
"""

from __future__ import annotations

import pathlib
import pickle
from array import array

import pytest
import rebuild_forward_fixture as rff
from conftest import chdir, load_impl, run_forward, run_retreat

FORWARD_ROUNDS = 9
SMALL_BOARD_NUM_MAX = 400
IMPL = "05_batch_wl_write"

# 組み直しの書き出し形式 (記録 #16 以降の実装が読む形)
OUT = ".bin"


def load_all(dat: pathlib.Path, pattern: str) -> list[int]:
    """拡張子で読み方を選ぶ。入力は #15 までの .pickle、出力は #16 以降の .bin。"""
    out: list[int] = []
    for path in sorted(dat.glob(pattern)):
        if path.suffix == OUT:
            a = array("Q")
            a.frombytes(path.read_bytes())
            out += list(a)
        else:
            with path.open("rb") as f:
                out += list(pickle.load(f))
    return out


@pytest.fixture(scope="module")
def finished_run(
    shared_library: pathlib.Path, tmp_path_factory: pytest.TempPathFactory
) -> pathlib.Path:
    """全探索を打ち切ってから後退解析まで完走させた作業ディレクトリ。"""
    work = tmp_path_factory.mktemp("finished")
    module = load_impl(IMPL, work, shared_library)
    run_forward(module, work, FORWARD_ROUNDS, SMALL_BOARD_NUM_MAX)
    with chdir(work):
        forward_totals = (module.tbn_uk, module.tbn_win, module.tbn_lose)
    # 全探索が完了時に書く行を作る (打ち切っているので実装は書かない)
    log = work / "kaiseki_log" / "kaizenkaiseki1.txt"
    with log.open("a", encoding="utf-8") as f:
        print(
            "総未知盤面数：{:d}, 総勝ち盤面数：{:d}, 総負け盤面数：{:d}".format(*forward_totals),
            file=f,
        )
    # ⚠️ 後退解析が散らす前に、全探索が書いた未知盤面の「並び」を控える。
    # これが P0 の採番順そのもので、組み直しでは戻らない (下の検査で固定する)
    with (work / "forward_unknown_order.pickle").open("wb") as f:
        pickle.dump(load_all(work / "dat", "unknown*.pickle"), f)
    run_retreat(module, work)
    return work


def test_the_rebuilt_fixture_has_the_three_families_back(
    finished_run: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """組み直した dat/ が、全探索の直後と同じ3群になっていること。"""
    log = finished_run / "kaiseki_log" / "kaizenkaiseki1.txt"
    n_uk, n_catch, n_lose = rff.read_forward_totals(log)
    assert n_uk > 100, "フィクスチャが小さすぎて検査にならない"

    dst = tmp_path / "dat"
    rff.rebuild(finished_run / "dat", log, dst)

    unknown = load_all(dst, "unknown*" + OUT)
    catch = load_all(dst, "win001te_*" + OUT)
    lose = load_all(dst, "lose000te_*" + OUT)
    assert len(unknown) == n_uk, "未知の件数が全探索時と違う"
    assert len(catch) == n_catch, "キャッチの件数が全探索時と違う"
    assert len(lose) == n_lose, "トライ負けの件数が全探索時と違う"

    # 3群は互いに素で、合わせて到達可能な全局面になる
    su, sc, sl = set(unknown), set(catch), set(lose)
    assert len(su) == len(unknown) and len(sc) == len(catch) and len(sl) == len(lose)
    assert not (su & sc) and not (su & sl) and not (sc & sl), "3群が重なっている"

    # 元の dat/ にあった局面がそのまま残っていること
    # unexplored* は全探索の作業途中のファイルで、3群には含まれない
    # (打ち切ったフィクスチャなので中身が残っている。完走した dat/ では空になる)
    before = set()
    for path in (finished_run / "dat").iterdir():
        if path.name.startswith("unexplored"):
            continue
        with path.open("rb") as f:
            before |= set(pickle.load(f))
    assert su | sc | sl == before, "組み直しで局面が増減した"


def test_the_rebuilt_fixture_does_not_restore_the_numbering_order(
    finished_run: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """⚠️ 戻るのは集合だけ。採番順 (P0 が読む並び) は戻らない。

    後退解析は未知盤面を手数別のファイルへ散らすので、組み直しは「手数の順」に
    詰め直すことになり、全探索の発見順には戻らない。

    ⚠️ **門番でフェーズ単独の効果量を測るとき、これを「本走と同じ条件」と書けない。**
    P4 (前任リストの乱書き) は採番順に反応する段で、記録 #12 の門番は実際に
    本走より旧新どちらも 4〜6% 遅かった。impl/11 の実データで確かめると、
    集合は一致したまま **2,925 件中 2,903 件 (99.2%) の位置が変わった**。
    旧新を同じ入力で交互に比べるぶんには影響しない。
    """
    with (finished_run / "forward_unknown_order.pickle").open("rb") as f:
        before: list[int] = pickle.load(f)
    assert len(before) > 100, "フィクスチャが小さすぎて検査にならない"

    dst = tmp_path / "dat"
    rff.rebuild(finished_run / "dat", finished_run / "kaiseki_log" / "kaizenkaiseki1.txt", dst)
    after = load_all(dst, "unknown*" + OUT)

    assert set(before) == set(after), "集合が戻っていない (組み直しの不具合)"
    moved = sum(1 for x, y in zip(before, after, strict=True) if x != y)
    assert moved > 0, (
        "採番順まで戻っている。門番の効果量の扱いを見直すこと "
        "(experiments/gate_12_c_predecessors/README.md の「本走の P4 とは一致していない」)"
    )


def test_the_rebuilt_fixture_only_has_what_the_retreat_reads(
    finished_run: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """後退解析が読むのは3系統だけ。深さ2以上のファイルを残さない。"""
    dst = tmp_path / "dat"
    rff.rebuild(finished_run / "dat", finished_run / "kaiseki_log" / "kaizenkaiseki1.txt", dst)
    names = sorted(p.name for p in dst.iterdir())
    for name in names:
        assert (
            name.startswith("unknown")
            or name.startswith("win001te_")
            or name.startswith("lose000te_")
        ), f"{name} が残っている。後退解析が中間状態と誤認する"
    # 副番号は 0 から連番 (実装が「最初に見つからない番号で break」する)
    for prefix in ("unknown", "win001te_", "lose000te_"):
        subs = sorted(
            int(n.removeprefix(prefix).removesuffix(OUT)) for n in names if n.startswith(prefix)
        )
        assert subs == list(range(len(subs))), f"{prefix} の副番号が飛んでいる"


def test_it_refuses_to_write_into_a_used_directory(
    finished_run: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """既にファイルがあるところへ書くと、古い残骸と混ざる。"""
    dst = tmp_path / "dat"
    dst.mkdir()
    (dst / ("unknown000" + OUT)).write_bytes(b"")
    with pytest.raises(SystemExit):
        rff.rebuild(finished_run / "dat", finished_run / "kaiseki_log" / "kaizenkaiseki1.txt", dst)


def test_it_refuses_when_the_catch_boundary_is_not_on_a_file_edge(
    finished_run: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """キャッチの件数がファイルの切れ目に乗らなければ止まる。

    全探索は末尾に詰めて書き、後退解析は空き副番号から新しく書くので、
    本来ここは必ず切れ目に来る。来ないなら前提が崩れているので進めない。
    """
    log = tmp_path / "bogus.log"
    log.write_text("総未知盤面数：1, 総勝ち盤面数：1, 総負け盤面数：1\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        rff.rebuild(finished_run / "dat", log, tmp_path / "dat")


def test_it_needs_the_forward_totals_line(tmp_path: pathlib.Path) -> None:
    """件数は推測しない。無ければ止まる。"""
    log = tmp_path / "empty.log"
    log.write_text("なにも書いていない\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        rff.read_forward_totals(log)


def test_the_cli_reports_usage_without_three_arguments() -> None:
    assert rff.main(["rebuild_forward_fixture.py"]) == 2


def bogus_log(tmp_path: pathlib.Path, n_uk: int, n_catch: int, n_lose: int) -> pathlib.Path:
    log = tmp_path / "bogus.log"
    log.write_text(
        f"総未知盤面数：{n_uk}, 総勝ち盤面数：{n_catch}, 総負け盤面数：{n_lose}\n",
        encoding="utf-8",
    )
    return log


def real_totals(finished_run: pathlib.Path) -> tuple[int, int, int]:
    return rff.read_forward_totals(finished_run / "kaiseki_log" / "kaizenkaiseki1.txt")


def test_it_splits_the_unknown_boards_into_chunks(
    finished_run: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未知盤面は BOARD_NUM_MAX ごとに分ける。実物では 20 チャンクになる。"""
    n_uk, _, _ = real_totals(finished_run)
    monkeypatch.setattr(rff, "BOARD_NUM_MAX", max(1, n_uk // 3))
    dst = tmp_path / "dat"
    rff.rebuild(finished_run / "dat", finished_run / "kaiseki_log" / "kaizenkaiseki1.txt", dst)
    chunks = sorted(dst.glob("unknown*" + OUT))
    assert len(chunks) >= 3, "分割されていない"
    assert sum(len(load_all(dst, c.name)) for c in chunks) == n_uk


def test_it_refuses_when_the_catch_count_is_larger_than_what_is_there(
    finished_run: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """キャッチが全部読んでも足りないなら、前提が崩れている。"""
    n_uk, n_catch, n_lose = real_totals(finished_run)
    log = bogus_log(
        tmp_path, n_uk, n_catch + len(load_all(finished_run / "dat", "win*.pickle")), n_lose
    )
    with pytest.raises(SystemExit):
        rff.rebuild(finished_run / "dat", log, tmp_path / "dat")


def test_it_refuses_when_the_lose_count_disagrees(
    finished_run: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    n_uk, n_catch, n_lose = real_totals(finished_run)
    with pytest.raises(SystemExit):
        rff.rebuild(
            finished_run / "dat", bogus_log(tmp_path, n_uk, n_catch, n_lose + 1), tmp_path / "dat"
        )


def test_it_refuses_when_the_unknown_count_disagrees(
    finished_run: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    n_uk, n_catch, n_lose = real_totals(finished_run)
    with pytest.raises(SystemExit):
        rff.rebuild(
            finished_run / "dat", bogus_log(tmp_path, n_uk + 1, n_catch, n_lose), tmp_path / "dat"
        )


def test_it_refuses_when_the_contents_change(
    finished_run: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """詰め替えの前後で中身が変われば止まる (件数だけでは気づけない取り違え)。"""
    original = rff.write_unknown

    def dropping(boards: list[int], dst: pathlib.Path, sub: int, digest: rff.Digest) -> int:
        # 1件だけ別の値にすり替える (件数は変わらない)
        if boards:
            boards = [boards[0] ^ 1, *boards[1:]]
        return original(boards, dst, sub, digest)

    monkeypatch.setattr(rff, "write_unknown", dropping)
    with pytest.raises(SystemExit):
        rff.rebuild(
            finished_run / "dat",
            finished_run / "kaiseki_log" / "kaizenkaiseki1.txt",
            tmp_path / "dat",
        )


def test_the_cli_rebuilds_end_to_end(finished_run: pathlib.Path, tmp_path: pathlib.Path) -> None:
    dst = tmp_path / "dat"
    rc = rff.main(
        [
            "rebuild_forward_fixture.py",
            str(finished_run / "dat"),
            str(finished_run / "kaiseki_log" / "kaizenkaiseki1.txt"),
            str(dst),
        ]
    )
    assert rc == 0
    assert (dst / ("unknown000" + OUT)).exists()


def test_it_rebuilds_from_a_raw_source_too(
    finished_run: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """★完走した dat/ が新形式でも組み直せること。

    ⚠️ **記録 #16 以降の門番はここだけに懸かっている。** 本走が .bin を吐くように
    なると、組み直しの入力も .bin になる。読めなければ #17 以降の門番が
    一切回せない (全規模の後退解析だけを走らせる入力が作れない)。
    """
    log = finished_run / "kaiseki_log" / "kaizenkaiseki1.txt"

    # 完走した dat/ を丸ごと新形式に写して、#16 の本走の出力に見立てる
    raw_src = tmp_path / "raw_src"
    raw_src.mkdir()
    for path in sorted((finished_run / "dat").iterdir()):
        if path.suffix != ".pickle":
            continue
        with path.open("rb") as f:
            boards = pickle.load(f)
        (raw_src / (path.stem + OUT)).write_bytes(array("Q", boards).tobytes())

    from_pickle = tmp_path / "from_pickle"
    from_raw = tmp_path / "from_raw"
    rff.rebuild(finished_run / "dat", log, from_pickle)
    rff.rebuild(raw_src, log, from_raw)

    assert sorted(p.name for p in from_raw.iterdir()) == sorted(
        p.name for p in from_pickle.iterdir()
    ), "ファイルの顔ぶれが元の形式で変わっている"
    for family in ("unknown*", "win001te_*", "lose000te_*"):
        a = load_all(from_pickle, family + OUT)
        b = load_all(from_raw, family + OUT)
        assert set(a) == set(b), f"{family} の集合が元の形式で変わっている"
