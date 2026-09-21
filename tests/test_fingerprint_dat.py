"""tools/fingerprint_dat.py の検査。

このツールは「数は合っているが中身が違う」壊れ方を捕まえるためにある。
指紋がチャンクの分かれ方に依存しないことと、1局面ずれたら落ちることを固定する。
"""

from __future__ import annotations

import pathlib
import pickle
import sys
from array import array

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


def write_raw_dat(root: pathlib.Path, layout: dict[str, list[Board]]) -> pathlib.Path:
    """記録 #16 の形式。8 バイト整数を並べるだけで、ヘッダは無い。"""
    dat = root / "dat"
    dat.mkdir(parents=True, exist_ok=True)
    for name, boards in layout.items():
        (dat / name).write_bytes(array("Q", set(boards)).tobytes())
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


# --------------------------------------------------------------------------
# 指紋を値として固定する側 (oracle/fingerprint.tsv と --against)
#
# dat/ は 2.2 GB で git に入らない。2つの dat/ を両方ディスクに置いておかないと
# 照合できない、という状態を解くために値のほうを固定する。保存形式を変える記録で
# バイト比較の鎖が切れるので、その前に入れておく必要がある。
# --------------------------------------------------------------------------

# 2^64 の境目。総和は mod 2^64 なので、ここが10進で往復することを見る
NEAR_MASK64 = (1 << 64) - 1


def test_dump_and_load_tsv_round_trip() -> None:
    """★辞書 → TSV → 辞書 が元に戻ること。引き分けの `-` と 64 ビット境界を含む。"""
    fp: dict[fingerprint_dat.Key, fingerprint_dat.Print] = {
        (1, "win"): (9118571, NEAR_MASK64, 0),
        (0, "lose"): (7018985, 0, NEAR_MASK64),
        (174, "lose"): (0, 0, 0),
        (None, "draw"): (2682700, 12345678901234567890, 42),
    }
    assert fingerprint_dat.load_tsv(fingerprint_dat.dump(fp)) == fp


def test_dump_writes_the_draw_depth_as_a_dash() -> None:
    """★引き分けは深さを持たない。`-` で書き、`render()` の桁区切りは混ぜない。"""
    text = fingerprint_dat.dump({(None, "draw"): (2682700, 7, 7)})
    body = [line for line in text.splitlines() if not line.startswith("#")]
    assert body == ["-\tdraw\t2682700\t7\t7"], text
    assert "," not in text, "桁区切りが入っている (render を .tsv に使っていないか)"


def test_the_registered_formats_are_pickle_and_raw() -> None:
    """★形式の実装は pickle (#15 まで) と生バイナリ (#16 以降) の2つ。

    ⚠️ **さらに形式を増やす記録でここが落ちる。それが目印。**
    そのときは Format をもう1つ書いて FORMATS に足し、この行を更新する。
    """
    assert [f.name for f in fingerprint_dat.FORMATS] == ["pickle", "raw"]
    assert [f.suffix for f in fingerprint_dat.FORMATS] == [".pickle", ".bin"]


def test_the_pickle_patterns_did_not_move_when_they_were_generated() -> None:
    """★_names() が組み立てる pickle の3つの規則が、手で書いていた頃と同一であること。

    ⚠️ **oracle/fingerprint.tsv は #15 の dat/ をこの規則で走査して作った値。**
    規則が1文字でも変われば、数えた対象が変わっていたことになり、
    あの値と過去の results/*/fingerprint.txt を比べてよい根拠が崩れる。
    """
    assert fingerprint_dat.PICKLE.win.pattern == r"^win(\d+)te_(\d+)\.pickle$"
    assert fingerprint_dat.PICKLE.lose.pattern == r"^lose(\d+)te_(\d+)\.pickle$"
    assert fingerprint_dat.PICKLE.unknown.pattern == r"^unknown(\d+)\.pickle$"
    assert fingerprint_dat.PICKLE.skip == ("_next", "_next_win")


def test_the_raw_format_reads_little_endian_eight_byte_integers() -> None:
    """★ヘッダ無しで、8 バイト整数がそのまま並んでいること。"""
    assert array("Q").itemsize == 8
    raw = array("Q", [1, 1 << 63]).tobytes()
    assert len(raw) == 16
    assert raw[:8] == b"\x01\x00\x00\x00\x00\x00\x00\x00", "リトルエンディアンでない"
    assert len(raw) // 8 == 2, "件数はバイト数 // 8 で出る"


def test_the_two_formats_give_the_same_fingerprint(tmp_path: pathlib.Path) -> None:
    """★同じ盤面なら、pickle でも生バイナリでも指紋が一致すること。

    記録 #16 で dat/ のバイト比較が使えなくなるので、**形式をまたいで
    比べられること自体がこの先の主検査**になる。
    """
    layout = {"win001te_000": [1, 2, 3], "lose000te_000": [9], "unknown000": [7, 8]}
    a = write_dat(tmp_path / "a", {f"{k}.pickle": v for k, v in layout.items()})
    b = write_raw_dat(tmp_path / "b", {f"{k}.bin": v for k, v in layout.items()})
    fa = fingerprint_dat.fingerprint(a, fingerprint_dat.PICKLE)
    fb = fingerprint_dat.fingerprint(b, fingerprint_dat.RAW)
    assert fa == fb
    assert fingerprint_dat.compare(fa, fb) == []


def test_the_format_is_detected_from_the_directory(tmp_path: pathlib.Path) -> None:
    """★拡張子を指定しなくても、dat/ の中身から形式が決まること。"""
    a = write_dat(tmp_path / "a", {"win001te_000.pickle": [1]})
    b = write_raw_dat(tmp_path / "b", {"win001te_000.bin": [1]})
    assert fingerprint_dat.detect(a) is fingerprint_dat.PICKLE
    assert fingerprint_dat.detect(b) is fingerprint_dat.RAW


def test_a_mixed_directory_is_refused(tmp_path: pathlib.Path) -> None:
    """★途中まで変換した dat/ を、片方だけ数えて通さないこと。

    ⚠️ 黙って片方だけ数えると、件数が足りないまま指紋が通る経路ができる。
    """
    dat = write_dat(tmp_path, {"win001te_000.pickle": [1]})
    (dat / "win003te_000.bin").write_bytes(array("Q", [3]).tobytes())
    with pytest.raises(ValueError, match="2つの形式が混ざっている"):
        fingerprint_dat.detect(dat)


def test_a_directory_without_answers_is_refused(tmp_path: pathlib.Path) -> None:
    dat = tmp_path / "dat"
    dat.mkdir()
    (dat / "notes.txt").write_text("メモ", encoding="utf-8")
    with pytest.raises(ValueError, match="答えのファイルが1つも無い"):
        fingerprint_dat.detect(dat)


def test_the_cli_reads_a_raw_dat(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """★生バイナリの dat/ を、形式を渡さずに --against で照合できること。

    oracle/fingerprint.tsv は #15 の pickle から作った値。それが #16 の .bin に
    そのまま使えることが、記録 #16 の主検査そのもの。
    """
    pick = write_dat(tmp_path / "a", {"win001te_000.pickle": [4, 5, 6], "unknown000.pickle": [7]})
    ref = tmp_path / "fingerprint.tsv"
    ref.write_text(fingerprint_dat.dump(fingerprint_dat.fingerprint(pick)), encoding="utf-8")
    raw = write_raw_dat(tmp_path / "b", {"win001te_000.bin": [6, 4, 5], "unknown000.bin": [7]})
    assert fingerprint_dat.main(["fingerprint_dat.py", str(raw), "--against", str(ref)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_a_mixed_dat_returns_2_from_the_cli(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dat = write_dat(tmp_path, {"win001te_000.pickle": [1]})
    (dat / "unknown000.bin").write_bytes(array("Q", [2]).tobytes())
    assert fingerprint_dat.main(["fingerprint_dat.py", str(dat)]) == 2
    assert "混ざっている" in capsys.readouterr().err


def test_against_a_matching_tsv_passes(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """★dat/ から書いた TSV が、その dat/ と照合して通ること。"""
    dat = write_dat(tmp_path, {"win001te_000.pickle": [1, 2, 3], "unknown000.pickle": [9]})
    ref = tmp_path / "fingerprint.tsv"
    ref.write_text(fingerprint_dat.dump(fingerprint_dat.fingerprint(dat)), encoding="utf-8")
    assert fingerprint_dat.main(["fingerprint_dat.py", str(dat), "--against", str(ref)]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and str(ref) in out
    assert "集合の完全一致を証明するものではない" in out


@pytest.mark.parametrize(
    ("column", "word"),
    [(2, "件数"), (3, "総和"), (4, "XOR")],
)
def test_against_a_broken_tsv_fails(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], column: int, word: str
) -> None:
    """★件数・総和・XOR を1つずつ崩すと落ち、どの深さのどれが違うか出ること。

    3つとも独立に見ていないと、片方だけ壊れた TSV を見逃す。
    """
    dat = write_dat(tmp_path, {"win003te_000.pickle": [4, 5, 6]})
    rows = fingerprint_dat.dump(fingerprint_dat.fingerprint(dat)).splitlines()
    body = [r for r in rows if not r.startswith("#")]
    cells = body[0].split("\t")
    cells[column] = str(int(cells[column]) + 1)
    ref = tmp_path / "fingerprint.tsv"
    ref.write_text("\n".join([rows[0], "\t".join(cells)]) + "\n", encoding="utf-8")

    assert fingerprint_dat.main(["fingerprint_dat.py", str(dat), "--against", str(ref)]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "depth=  3" in out and word in out


def test_tsv_output_can_be_fed_back_in(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """★`--tsv` で出したものが、そのまま `--against` の相手になること。"""
    dat = write_dat(tmp_path, {"lose002te_000.pickle": [11, 13]})
    assert fingerprint_dat.main(["fingerprint_dat.py", str(dat), "--tsv"]) == 0
    ref = tmp_path / "fingerprint.tsv"
    ref.write_text(capsys.readouterr().out, encoding="utf-8")
    assert fingerprint_dat.main(["fingerprint_dat.py", str(dat), "--against", str(ref)]) == 0
    capsys.readouterr()


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("1\twin\t2\t3\n", "5 列でない"),
        ("1\twin\t2\t3\tx\n", "数として読めない"),
        ("1\twin\t2\t3\t4\n1\twin\t9\t9\t9\n", "2度出てくる"),
        ("# 見出しだけ\n\n", "1行も無い"),
    ],
)
def test_a_broken_tsv_is_refused(text: str, match: str) -> None:
    """★読めない TSV は黙って空にせず、どこが悪いか言って落ちること。"""
    with pytest.raises(ValueError, match=match):
        fingerprint_dat.load_tsv(text)


def test_a_broken_tsv_file_returns_2(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dat = write_dat(tmp_path, {"win001te_000.pickle": [1]})
    ref = tmp_path / "fingerprint.tsv"
    ref.write_text("1\twin\t2\n", encoding="utf-8")
    assert fingerprint_dat.main(["fingerprint_dat.py", str(dat), "--against", str(ref)]) == 2
    assert "5 列でない" in capsys.readouterr().err


def test_a_missing_tsv_returns_2(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dat = write_dat(tmp_path, {"win001te_000.pickle": [1]})
    nope = str(tmp_path / "nope.tsv")
    assert fingerprint_dat.main(["fingerprint_dat.py", str(dat), "--against", nope]) == 2
    assert "指紋のファイルが無い" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("extra", "match"),
    [
        (["--against"], "--against に値が無い"),
        (["--tsv", "--against", "x.tsv"], "同時に使えない"),
    ],
)
def test_option_misuse_returns_2(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], extra: list[str], match: str
) -> None:
    dat = write_dat(tmp_path, {"win001te_000.pickle": [1]})
    assert fingerprint_dat.main(["fingerprint_dat.py", str(dat), *extra]) == 2
    assert match in capsys.readouterr().err


def test_tsv_with_two_directories_returns_2(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """★`--tsv` は dat/ 1つ。2つ渡されたら黙って片方を無視しない。"""
    a = write_dat(tmp_path / "a", {"win001te_000.pickle": [1]})
    b = write_dat(tmp_path / "b", {"win001te_000.pickle": [1]})
    assert fingerprint_dat.main(["fingerprint_dat.py", str(a), str(b), "--tsv"]) == 2
    capsys.readouterr()
