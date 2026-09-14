"""tools/fingerprint_dat.py の検査。

このツールは「数は合っているが中身が違う」壊れ方を捕まえるためにある。
指紋がチャンクの分かれ方に依存しないことと、1局面ずれたら落ちることを固定する。
"""

from __future__ import annotations

import pathlib
import pickle
import sys

import fingerprint_dat
import pytest

Board = int


def write_dat(root: pathlib.Path, layout: dict[str, list[Board]]) -> pathlib.Path:
    dat = root / "dat"
    dat.mkdir(parents=True, exist_ok=True)
    for name, boards in layout.items():
        with (dat / name).open("wb") as f:
            pickle.dump(set(boards), f)
    return dat


def test_fingerprint_counts_sums_and_xors(tmp_path: pathlib.Path) -> None:
    dat = write_dat(tmp_path, {"win001te_000.pickle": [1, 2, 4]})
    fp = fingerprint_dat.fingerprint(dat)
    assert fp[(1, "win")] == (3, 1 + 2 + 4, 1 ^ 2 ^ 4)


def test_chunk_split_does_not_change_the_fingerprint(tmp_path: pathlib.Path) -> None:
    """同じ答えでもチャンクの分かれ方は集合の pop 順で変わる。指紋はそこに依存しない。"""
    one = write_dat(tmp_path / "one", {"win001te_000.pickle": [10, 20, 30, 40]})
    many = write_dat(
        tmp_path / "many",
        {
            "win001te_000.pickle": [40, 10],
            "win001te_001.pickle": [30],
            "win001te_002.pickle": [20],
        },
    )
    assert fingerprint_dat.fingerprint(one) == fingerprint_dat.fingerprint(many)
    assert (
        fingerprint_dat.compare(fingerprint_dat.fingerprint(one), fingerprint_dat.fingerprint(many))
        == []
    )


def test_depths_and_results_are_separated(tmp_path: pathlib.Path) -> None:
    dat = write_dat(
        tmp_path,
        {
            "win001te_000.pickle": [1],
            "win003te_000.pickle": [3],
            "lose000te_000.pickle": [7],
            "lose002te_000.pickle": [9],
            "unknown000.pickle": [5],
        },
    )
    fp = fingerprint_dat.fingerprint(dat)
    assert set(fp) == {(1, "win"), (3, "win"), (0, "lose"), (2, "lose"), (None, "draw")}
    assert fp[(None, "draw")] == (1, 5, 5)


def test_intermediate_files_are_ignored(tmp_path: pathlib.Path) -> None:
    """_next / _next_win は答えではない。片方の実装にしか無くても照合は通る。"""
    dat = write_dat(
        tmp_path,
        {
            "unknown000.pickle": [5],
            "unknown000_next.pickle": [11, 12],
            "unknown000_next_win.pickle": [11],
        },
    )
    fp = fingerprint_dat.fingerprint(dat)
    assert set(fp) == {(None, "draw")}


def test_one_moved_board_is_caught(tmp_path: pathlib.Path) -> None:
    """件数が同じでも、1局面が別の深さへ移れば落ちる。"""
    a = write_dat(
        tmp_path / "a",
        {"win001te_000.pickle": [1, 2], "win003te_000.pickle": [3, 4]},
    )
    b = write_dat(
        tmp_path / "b",
        {"win001te_000.pickle": [1, 3], "win003te_000.pickle": [2, 4]},
    )
    bad = fingerprint_dat.compare(fingerprint_dat.fingerprint(a), fingerprint_dat.fingerprint(b))
    assert len(bad) == 2
    assert all("depth=" in line for line in bad)


def test_identical_dats_compare_equal(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    layout = {"win001te_000.pickle": [1, 2, 3], "lose000te_000.pickle": [9]}
    a = write_dat(tmp_path / "a", layout)
    b = write_dat(tmp_path / "b", layout)
    monkeypatch.setattr(sys, "argv", ["fingerprint_dat.py", str(a), str(b)])
    assert fingerprint_dat.main(sys.argv) == 0
    assert "PASS" in capsys.readouterr().out


def test_differing_dats_exit_nonzero(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    a = write_dat(tmp_path / "a", {"win001te_000.pickle": [1, 2]})
    b = write_dat(tmp_path / "b", {"win001te_000.pickle": [1, 2, 3]})
    monkeypatch.setattr(sys, "argv", ["fingerprint_dat.py", str(a), str(b)])
    assert fingerprint_dat.main(sys.argv) == 1
    assert "FAIL" in capsys.readouterr().out


def test_single_argument_renders_a_table(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dat = write_dat(tmp_path, {"win001te_000.pickle": [1, 2], "unknown000.pickle": [8]})
    monkeypatch.setattr(sys, "argv", ["fingerprint_dat.py", str(dat)])
    assert fingerprint_dat.main(sys.argv) == 0
    out = capsys.readouterr().out
    assert "win" in out and "draw" in out
    assert "3" in out  # 合計


def test_missing_directory_returns_2(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["fingerprint_dat.py", str(tmp_path / "nope")])
    assert fingerprint_dat.main(sys.argv) == 2
    capsys.readouterr()


def test_wrong_argument_count_returns_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["fingerprint_dat.py"])
    assert fingerprint_dat.main(sys.argv) == 2
    capsys.readouterr()


def test_unrecognized_files_are_skipped(tmp_path: pathlib.Path) -> None:
    """dat/ にはログやバックアップが混ざりうる。答えのファイルだけを見る。"""
    dat = write_dat(tmp_path, {"win001te_000.pickle": [1]})
    (dat / "unexplored000.pickle").write_bytes(pickle.dumps({99}))
    (dat / "win001te_000_backup.pickle").write_bytes(pickle.dumps({1234}))
    (dat / "notes.txt").write_text("メモ", encoding="utf-8")
    assert fingerprint_dat.fingerprint(dat) == {(1, "win"): (1, 1, 1)}


def test_same_count_different_boards_is_caught(tmp_path: pathlib.Path) -> None:
    """件数が同じでも中身が違えば総和と XOR が動く。オラクルでは見えない壊れ方。"""
    a = write_dat(tmp_path / "a", {"win001te_000.pickle": [1, 2, 3]})
    b = write_dat(tmp_path / "b", {"win001te_000.pickle": [1, 2, 4]})
    bad = fingerprint_dat.compare(fingerprint_dat.fingerprint(a), fingerprint_dat.fingerprint(b))
    assert len(bad) == 1
    assert "総和" in bad[0] and "XOR" in bad[0]
    assert "件数" not in bad[0]


def test_missing_depth_on_either_side_is_caught(tmp_path: pathlib.Path) -> None:
    a = write_dat(tmp_path / "a", {"win001te_000.pickle": [1], "win003te_000.pickle": [3]})
    b = write_dat(tmp_path / "b", {"win001te_000.pickle": [1], "lose002te_000.pickle": [2]})
    bad = fingerprint_dat.compare(fingerprint_dat.fingerprint(a), fingerprint_dat.fingerprint(b))
    assert len(bad) == 2
    assert any("(1つ目) に無い" in line for line in bad)
    assert any("(2つ目) に無い" in line for line in bad)


def test_missing_second_directory_returns_2(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    a = write_dat(tmp_path / "a", {"win001te_000.pickle": [1]})
    monkeypatch.setattr(sys, "argv", ["fingerprint_dat.py", str(a), str(tmp_path / "nope")])
    assert fingerprint_dat.main(sys.argv) == 2
    capsys.readouterr()


@pytest.mark.parametrize("empty_side", ["first", "second", "both", "single", "empty_set"])
def test_empty_artifacts_are_not_successful(tmp_path: pathlib.Path, empty_side: str) -> None:
    layout = {"win001te_000.pickle": [1]}
    a = write_dat(tmp_path / "a", layout if empty_side == "second" else {})
    b = write_dat(tmp_path / "b", layout if empty_side == "first" else {})
    if empty_side == "empty_set":
        a = write_dat(tmp_path / "a", {"win001te_000.pickle": []})
    args = ["fingerprint_dat.py", str(a)]
    if empty_side != "single":
        args.append(str(b))
    assert fingerprint_dat.main(args) == 2


def test_colliding_fingerprints_do_not_claim_exact_equality(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = write_dat(tmp_path / "a", {"win001te_000.pickle": [1, 6]})
    b = write_dat(tmp_path / "b", {"win001te_000.pickle": [2, 5]})
    assert fingerprint_dat.main(["fingerprint_dat.py", str(a), str(b)]) == 0
    assert "集合の完全一致を証明するものではない" in capsys.readouterr().out
