"""impl/11_c_seen — 全探索の発見済み集合をC側へ移した版。

記録 #10 の計装では、全探索 1,875 秒のうち F3 集合化 311 秒 + F4 重複排除 498 秒
(43.1%) が Python の `set` に消えていた。「見たことがある局面」をC側の平坦な表に持たせ、
**後続を生成しているその場で登録と重複判定まで済ませる**と、その2段は構造上なくなる
(仕事が消えるのではなくCへ移る。F1 は増える)。

⚠️ **FFI の回数を増やしてはいけない。** 呼び出し1回が約 1.5 µs なので、辺ごとや
「生成」と「登録」に分けて2回呼ぶ設計にすると、それだけで 246,803,167 回 × 1.5 µs の
追加になる。登録は既存の1回の呼び出し (`nextBoardSeenNormal`) の中で完結させる。

⚠️ **衝突処理と詰め直し (リハッシュ) のバグは静かに間違った答えを出す。**
「初見」と誤判定すれば同じ局面を二度探索し、「既出」と誤判定すれば局面を取りこぼす。
構造テストでは見つからないので、ここでCの表を実際に動かして Python の `set` と突き合わせる。
"""

from __future__ import annotations

import ast
import difflib
import pathlib
import random
from ctypes import CDLL, c_int32, c_uint64

from conftest import ROOT, impl_library

IMPL_DIR = ROOT / "impl" / "11_c_seen"
PREV_DIR = ROOT / "impl" / "10_setdiff"
SOURCE = IMPL_DIR / "animal_shogi.py"
PREV_SOURCE = PREV_DIR / "animal_shogi.py"

CHANGED = {"searchNext", "searchAll", "buildSeenBoards"}
ADDED = {"nextBoardSeenNormalWrap"}
REMOVED = {"nextBoardInvNormalWrap"}

INITIAL_BOARD = 0x000A003C914B002

# C 側の初期スロット数 (2^20)。これを超えるまで入れれば詰め直しが起きる
SEEN_MIN_SLOTS = 1 << 20


def top_level_functions(path: pathlib.Path) -> dict[str, str]:
    """モジュール直下の関数を、名前 → ソースそのもの で返す。"""
    text = path.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef):
            segment = ast.get_source_segment(text, node)
            assert segment is not None, f"{path} の {node.name} のソースを取れない"
            out[node.name] = segment
    return out


def code_lines(body: str) -> str:
    """コメント行を除いたコード。罠を警告するコメントに引っかからないため。"""
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))


def hot_loop(body: str) -> str:
    """searchNext() の展開ループ本体 (while から後続を積むところまで)。"""
    start = body.index("    while unexp_boards:")
    end = body.index("new_unexp_boards += nbl", start) + len("new_unexp_boards += nbl")
    return body[start:end]


def test_the_c_only_gains_lines() -> None:
    """C とヘッダは impl/10 に対して純粋な追加。既存の1行も動かさない。

    後退解析の索引 (indexBuild) と指し手生成 (nextBoardInvNormal) はそのまま。
    """
    for name in ("animal_shogi.c", "animal_shogi.h"):
        prev = (PREV_DIR / name).read_text(encoding="utf-8").splitlines()
        cur = (IMPL_DIR / name).read_text(encoding="utf-8").splitlines()
        removed = [
            ln[2:]
            for ln in difflib.unified_diff(prev, cur, n=0, lineterm="")
            if ln.startswith("-") and not ln.startswith("---")
        ]
        assert removed == [], f"{name} で impl/10 の行が消えている: {removed[:3]}"
        assert len(cur) > len(prev), f"{name} に発見済み表が入っていない"


def test_the_build_is_untouched() -> None:
    """Makefile は impl/10 とバイト単位で同一 (＝ -O0 のまま)。"""
    assert (IMPL_DIR / "Makefile").read_bytes() == (PREV_DIR / "Makefile").read_bytes(), (
        "impl/11_c_seen/Makefile が impl/10 と違う。-O2 は次の試行で1変数として測る"
    )


def test_only_the_forward_dedup_changed() -> None:
    """変わるのは全探索の重複排除まわりの3関数と、ラッパーの差し替えだけ。"""
    prev = top_level_functions(PREV_SOURCE)
    cur = top_level_functions(SOURCE)
    changed = {n for n in prev if n in cur and cur[n] != prev[n]}
    assert changed == CHANGED, f"想定外の関数が変わっている: {changed ^ CHANGED}"
    added = set(cur) - set(prev)
    assert added == ADDED, f"想定外の関数が増えている: {added ^ ADDED}"
    removed = set(prev) - set(cur)
    assert removed == REMOVED, f"想定外の関数が消えている: {removed ^ REMOVED}"
    # 後退解析は今回の対照群
    for name in ("retreatAnalysis", "buildIndex", "buildSuccessors", "buildPredecessors"):
        assert cur[name] == prev[name], f"{name} が impl/10 から変わっている"


def test_the_ffi_is_called_once_per_board() -> None:
    """★展開ループの中のC呼び出しは1局面1回のまま。

    呼び出し1回が約 1.5 µs。生成と登録を分けて2回呼んだら、
    246,803,167 回 × 1.5 µs ＝ 370 秒の追加でこの改善は消える。
    """
    loop = hot_loop(top_level_functions(SOURCE)["searchNext"])
    tree = ast.parse(loop.strip().replace("while unexp_boards:", "if True:"))
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert calls.count("nextBoardSeenNormalWrap") == 1, "C の呼び出しが1か所でない"
    assert "seenInsert" not in loop, "ループの中から登録を呼んでいる (FFI が増える)"
    assert "nextBoardInvNormalWrap" not in loop, "まだ古いラッパーを呼んでいる"


def test_the_python_set_is_gone() -> None:
    """★F3 (集合化) と F4 (重複排除) の本体が消えていること。"""
    body = code_lines(top_level_functions(SOURCE)["searchNext"])
    assert "set(new_unexp_boards)" not in body, "まだ Python 側で集合化している"
    assert "- seen_boards" not in body, "まだ Python 側で差集合を取っている"
    assert "seen_boards |=" not in body, "まだ Python 側で合併している"
    assert "seenCount()" in body, "件数をC側から取っていない"


def test_the_clock_is_not_inside_the_hot_loop() -> None:
    """★展開ループの中に時計を置かない (246,803,167 回まわる)。"""
    loop = hot_loop(top_level_functions(SOURCE)["searchNext"])
    assert "_profMark" not in loop, "ホットループの内側に時計がある"
    assert "seenProbes()" not in loop, "ループの中で計数器を読んでいる (FFI が増える)"


def test_the_generated_count_still_reaches_the_sub_log() -> None:
    """★サブログの「重複排除前」は今までどおり *生成した総数*。

    Python 側はもう持っていないので、C の計数器の差から取る。
    ここを len(new_unexp_boards) にすると、値が変わって
    tests/test_forward_search_equivalence.py のサブログ比較が壊れる。
    """
    body = top_level_functions(SOURCE)["searchNext"]
    assert '新状態数 (重複排除前)：{:d}".format(_prof["n_new_pre"])' in body
    assert '_prof["n_new_pre"] = seenProbes() - _gen0' in body, "生成総数を計数器から取っていない"


def test_the_table_is_freed_before_the_retreat_analysis() -> None:
    """★表を手放す位置。後退解析が索引 (8.59 GB) を作る前でなければならない。"""
    body = top_level_functions(SOURCE)["searchAll"]
    assert "seenFree()" in body, "表を解放していない"
    assert "seenInit()" in body, "表を空から始めていない"
    assert body.index("seenInit()") < body.index("seenFree()")


def test_the_restart_caveat_is_written_down() -> None:
    """⚠️ 再開時の危険が現状より増えることを、黙って変えない。

    初回ラウンドの登録 (F1) が buildSeenBoards より先に走るので、途中の dat/ から
    再開すると既出を初見と誤る。レギュレーションは再開を禁じている (再走する)。
    """
    text = SOURCE.read_text(encoding="utf-8")
    head = text[: text.index("def buildSeenBoards(")]
    assert "既出を初見と誤る" in head.split("# ---")[-1], "再開時の注意が書かれていない"
    assert "insertAll" in top_level_functions(SOURCE)["buildSeenBoards"], "C の表に入れ直していない"


def test_the_allocation_failure_is_a_known_defect() -> None:
    """⚠️ **既知の不具合を固定する。** 直すのは次の実装。

    `nextBoardSeenNormalWrap` は C の `-3` (表を確保できない) を検査していないので、
    `-1` でも `-2` でもない値が `searchNext()` の `else` に落ちて
    「未知・初見0件」として扱われる。その局面の後続は探索キューに入らないまま、
    例外も出ずに先へ進む (`-3` を注入して再現した)。

    ⚠️ impl/11_c_seen は記録済みなので直さない (凍結規約)。
    **次の実装では `-3` を受けたら RuntimeError を投げる** —— CLAUDE.md の
    「次の実装で必ず直すもの」に積んである。このテストはその積み残しが
    黙って消えないようにするための印で、実装を直したときは
    `impl/11` ではなく新しいディレクトリのテストで「直っていること」を検査する。
    """
    body = top_level_functions(SOURCE)["nextBoardSeenNormalWrap"]
    assert "raise" not in body, (
        "impl/11 の不具合が直っている？ 記録済みの実装は凍結する。"
        "直した版は新しいディレクトリに作り、このテストは印として残す"
    )
    note = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "次の実装で必ず直すもの" in note, "CLAUDE.md の積み残しの節が消えている"
    assert "nextBoardSeenNormal" in note, "CLAUDE.md にこの不具合が書かれていない"


def test_no_impl_env_needed() -> None:
    """構成がベースラインと同じなので、ハーネスの既定値でそのまま走る。"""
    assert not (IMPL_DIR / "impl.env").exists()


# --------------------------------------------------------------------------
# ここから下はCの表を実際に動かす。
# 衝突処理と詰め直しのバグは構造テストでは見つからない
# --------------------------------------------------------------------------


class Seen:
    """impl/11 の .so を発見済み表として使うための薄い口。"""

    def __init__(self) -> None:
        self.lib = CDLL(str(impl_library("11_c_seen")))
        for name, restype, argtypes in (
            ("seenInit", c_int32, ()),
            ("seenInsert", c_int32, (c_uint64,)),
            ("seenContains", c_int32, (c_uint64,)),
            ("seenCount", c_uint64, ()),
            ("seenProbes", c_uint64, ()),
            ("seenRehashes", c_uint64, ()),
            ("nextBoardSeenNormal", c_int32, (c_uint64, c_uint64 * 48)),
            ("nextBoardInvNormal", c_int32, (c_uint64, c_uint64 * 48)),
        ):
            fn = getattr(self.lib, name)
            fn.restype = restype
            fn.argtypes = argtypes
        self.lib.seenFree.restype = None
        self.lib.seenFree.argtypes = ()
        self.out = (c_uint64 * 48)()
        assert self.lib.seenInit() == 0

    def successors(self, board: int) -> tuple[int, list[int]]:
        """登録せずに後続だけを見る (照合用)。"""
        n = int(self.lib.nextBoardInvNormal(c_uint64(board), self.out))
        return n, list(self.out[:n]) if n > 0 else []

    def expand(self, board: int) -> tuple[int, list[int]]:
        """登録しながら展開する。初見だったものだけ返る。"""
        n = int(self.lib.nextBoardSeenNormal(c_uint64(board), self.out))
        return n, list(self.out[:n]) if n > 0 else []


def test_the_table_agrees_with_a_python_set() -> None:
    """★挿入の戻り値が Python の set と一致すること (重複込み)。"""
    seen = Seen()
    rng = random.Random(20260919)
    keys = [rng.getrandbits(60) for _ in range(30000)]
    keys += keys[:10000]  # わざと重複させる
    rng.shuffle(keys)

    ref: set[int] = set()
    for key in keys:
        want = 0 if key in ref else 1
        got = int(seen.lib.seenInsert(c_uint64(key)))
        assert got == want, f"{key:#x} の判定が set と違う ({got} != {want})"
        ref.add(key)
    assert int(seen.lib.seenCount()) == len(ref)
    assert all(seen.lib.seenContains(c_uint64(k)) for k in ref)
    seen.lib.seenFree()


def test_nothing_is_lost_across_a_rehash() -> None:
    """★詰め直しをまたいで全件が残ること。

    ここが壊れると「既に見た局面」を初見と誤り、同じ局面を二度探索する。
    2^20 スロットから始めるので、120万件も入れれば2回は詰め直しが起きる。
    """
    seen = Seen()
    rng = random.Random(11)
    keys = [rng.getrandbits(60) for _ in range(1_200_000)]
    for key in keys:
        assert int(seen.lib.seenInsert(c_uint64(key))) >= 0

    assert int(seen.lib.seenRehashes()) >= 2, "詰め直しが起きていない (テストが空振り)"
    assert int(seen.lib.seenCount()) == len(set(keys))
    missing = [k for k in keys if not seen.lib.seenContains(c_uint64(k))]
    assert missing == [], f"詰め直しで消えた盤面がある: {[hex(k) for k in missing[:3]]}"
    # 入れていない値が入っていることにならない
    assert not seen.lib.seenContains(c_uint64(rng.getrandbits(60) | 1 << 61))
    seen.lib.seenFree()


def test_the_sentinel_is_refused() -> None:
    """空きスロットの番兵と同じ値は入れられない (入れたら表が壊れる)。"""
    seen = Seen()
    assert int(seen.lib.seenInsert(c_uint64(0xFFFFFFFFFFFFFFFF))) == -4
    assert int(seen.lib.seenCount()) == 0
    seen.lib.seenFree()


def test_expanding_returns_only_first_time_boards() -> None:
    """★同じ局面を2回展開したら、2回目は初見が0個。

    ラウンド内の重複 (#10 までの F3) も、過去との重複 (#10 までの F4) も、
    この1回の登録が吸収している。
    """
    seen = Seen()
    degree, successors = seen.successors(INITIAL_BOARD)
    assert degree > 0, "初期局面に後続が無い (テストが空振り)"

    n1, first = seen.expand(INITIAL_BOARD)
    assert n1 == degree, "初回なのに初見でない後続がある"
    assert first == successors, "返ってきた後続が nextBoardInvNormal と違う"

    n2, second = seen.expand(INITIAL_BOARD)
    assert n2 == 0 and second == [], "2回目に初見が出た (登録されていない)"
    assert int(seen.lib.seenCount()) == degree
    assert int(seen.lib.seenProbes()) == 2 * degree, "生成した後続の総数が合わない"
    seen.lib.seenFree()


def test_the_classification_matches_the_baseline_generator() -> None:
    """★勝ち・負け・未知の振り分けが nextBoardInvNormal と一致すること。

    ⚠️ 戻り値の規約を付け替えている (-1=キャッチ勝ち / -2=トライ負け / >=0=未知)。
    ここを取り違えると、勝ち盤面が未知に混ざって答えが変わる。
    """
    seen = Seen()
    # ⚠️ 本走では初期局面を buildSeenBoards が表に入れる (前段の updateUKFile が
    #    unknown0 に書いたものを読む). ここでも同じ状態から始める。
    #    入れずに始めると、初期局面が誰かの後続として再び出たときに「初見」になる
    assert int(seen.lib.seenInsert(c_uint64(INITIAL_BOARD))) == 1
    frontier = [INITIAL_BOARD]
    visited = {INITIAL_BOARD}
    wins = loses = unknowns = 0
    dup_seen = False
    while frontier and len(visited) < 60000:
        board = frontier.pop()
        degree, successors = seen.successors(board)
        n, fresh = seen.expand(board)
        if degree == 0:
            assert n == -1, f"{board:#x} はキャッチ勝ちなのに {n}"
            wins += 1
            continue
        if degree < 0:
            assert n == -2, f"{board:#x} はトライ負けなのに {n}"
            loses += 1
            continue
        assert n >= 0, f"{board:#x} は未知なのに {n}"
        unknowns += 1
        # 返ってきたのは初見だけ。⚠️ 同じ局面が同じラウンドで2回出ることがある
        # (指し手が違っても鏡面正規化のあとで同じ値になる)。そのぶんも1回に畳まれる
        want = []
        for b in successors:
            if b not in visited:
                visited.add(b)
                frontier.append(b)
                want.append(b)
        assert fresh == want, "初見の選び方が違う"
        dup_seen |= len(set(successors)) < len(successors)

    assert wins > 0 and loses > 0 and unknowns > 1000, "3種類とも通っていない (空振り)"
    assert dup_seen, "同一局面が2回出るケースを1つも通っていない (テストが空振り)"
    assert int(seen.lib.seenCount()) == len(visited), "表の件数が到達局面と合わない"
    seen.lib.seenFree()
