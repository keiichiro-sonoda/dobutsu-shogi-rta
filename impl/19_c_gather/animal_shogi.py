#!/usr/bin/python3

import datetime
import os
import resource
import time
from array import array
from ctypes import (c_int32, c_int64, c_size_t, c_ubyte, c_uint32, c_uint64, c_void_p,
                    cast, CDLL, POINTER)

# 次の盤面を受け取るための配列型
c_uint64_array48 = c_uint64 * 48

# 後続の連番を受け取るための配列型
# 48 は MAX_ACTION_NUM. 末尾の2つは索引外の後続があったときだけ使う
# (out[48] = 索引を引けた数, out[49] = 出次数)
c_uint32_array50 = c_uint32 * 50

# P2 後続生成の中継バッファ (記録 #15). C が1回で埋める量.
# ⚠️ 大きくしてもピーク RSS に直に乗るだけ. 全体のピークを決めているのは
#    P2 の末尾 (索引 8.59 GB + packed 1.97 GB + succ 3.75 GB + succ_off/cnt 0.50 GB)
SUCC_STAGE = 65536

# buildSuccRange の戻り値を受け取る配列型 (下流の戻り値が負なので符号付き)
c_int64_array4 = c_int64 * 4

INITIAL_BOARD = 0x000a003c914b002

# 1ファイルに格納する盤面数の最大値
# 1000万は2Gメモリがあふれるらしい
BOARD_NUM_MAX = 5000000

# ディレクトリのパス
DIR_PATH = "./dat/"

# 負け盤面のパス
LOSE_PATH_FORMAT = DIR_PATH + "lose{:03d}te_{:03d}.bin"

# 勝ち盤面のパス
WIN_PATH_FORMAT = DIR_PATH + "win{:03d}te_{:03d}.bin"

# 未知盤面のパス
UK_PATH_FORMAT = DIR_PATH + "unknown{:03d}.bin"

# 未探索盤面のパス
UNEXP_PATH_FORMAT = DIR_PATH + "unexplored{:03d}.bin"

# バックアップフラグ (真ならファイル上書きの度にバックアップ)

# 適当なループ数 (break前提)
LOOP_MAX = 10000

# 前向き探索で「すでに見つけた盤面」を全部持つ常駐集合
# searchNext() は毎ラウンドこれを引く
# 初回だけディスクから組み立てるので, 途中で落ちても次の起動で作り直せる
# (全探索が終わったら searchAll() で解放する)
seen_boards = None

# 前向き探索で見つけた終端局面. 全探索の最後に1回だけ書き出す
#
# updateWLFile() はラウンドごとに呼ばれ, 毎回その深さの末尾ファイルを丸ごと
# 読み直して書き戻していた. 名簿に載るのは 147,317,599 局面なのに, 書き写した
# 延べ要素は 639,329,035 で 4.3 倍ある. 貯めて最後に1回書けば読み直しが消える
# (記録 #5 で後退解析側にやったのと同じことを, 残っていた前向き側にも入れる)
#
# 途中で落ちるとこのリストごと消えるが, それでよい. ディスクに中途半端な名簿が
# 残らないので「再開できそうに見えて中身が古い」状態にはならない
# (CLAUDE.md の「途中で落ちたら再走」と整合する)
catch_wins = array("Q")
try_loses = array("Q")

# 各盤面の総数
# 以前は重複排除でファイルを読み直すついでに数えていた
# ループを消したのでカウンタとして持ち回る
tbn_uk = 0
tbn_win = 0
tbn_lose = 0

# 出力ファイル
LOG_PATH_SUB = "./kaiseki_log/kaiseki_log7.txt"
# LOG_PATH_SUB = ""
# LOG_PATH_MAIN = "./kaiseki_log/kaiseki_log6.txt"
LOG_PATH_MAIN = "./kaiseki_log/kaizenkaiseki1.txt"

lib = CDLL("./animal_shogi.so")

showBoard = lib.showBoard
showBoard.restype = None
showBoard.argtypes = (c_uint64,)

nextBoardInvNormal = lib.nextBoardInvNormal
nextBoardInvNormal.restype = c_int32
nextBoardInvNormal.argtypes = (c_uint64, c_uint64_array48)

normalBoard = lib.normalBoard
normalBoard.restype = c_uint64
normalBoard.argtypes = (c_uint64,)

# パック値 → 連番 の索引. 後退解析でしか使わない
indexBuild = lib.indexBuild
indexBuild.restype = c_int32
indexBuild.argtypes = (POINTER(c_uint64), c_uint32)

indexFree = lib.indexFree
indexFree.restype = None
indexFree.argtypes = ()

# 指し手生成と索引引きをC側で済ませる. 辺ごとに ctypes を呼んだら
# 呼び出しのオーバーヘッド (約1µs) だけで辞書引きより遅くなるため,
# 呼び出し回数は未知盤面の数 (99,485,568) のまま増やさない
nextBoardIndexNormal = lib.nextBoardIndexNormal
nextBoardIndexNormal.restype = c_int32
nextBoardIndexNormal.argtypes = (c_uint32, c_uint32_array50)

# 全探索の発見済み集合 (C 側の平坦なハッシュ表. #10 までの Python の set)
seenInit = lib.seenInit
seenInit.restype = c_int32
seenInit.argtypes = ()

seenFree = lib.seenFree
seenFree.restype = None
seenFree.argtypes = ()

seenInsertMany = lib.seenInsertMany
seenInsertMany.restype = c_int32
seenInsertMany.argtypes = (POINTER(c_uint64), c_uint32)

seenInsert = lib.seenInsert
seenInsert.restype = c_int32
seenInsert.argtypes = (c_uint64,)

seenCount = lib.seenCount
seenCount.restype = c_uint64
seenCount.argtypes = ()

# 検算用 (本走の経路では使わない)
seenContains = lib.seenContains
seenContains.restype = c_int32
seenContains.argtypes = (c_uint64,)

seenProbes = lib.seenProbes
seenProbes.restype = c_uint64
seenProbes.argtypes = ()

seenRehashes = lib.seenRehashes
seenRehashes.restype = c_uint64
seenRehashes.argtypes = ()

# 前任リストの計数ソート (P4). array("I") の連続バッファをゼロコピーで渡す
predCount = lib.predCount
predCount.restype = c_int32
predCount.argtypes = (POINTER(c_uint32), c_size_t, c_uint32, POINTER(c_uint32))

predScatter = lib.predScatter
predScatter.restype = c_int32
predScatter.argtypes = (
    POINTER(c_uint32), c_size_t, POINTER(c_uint32), c_uint32,
    c_uint32, POINTER(c_uint32), POINTER(c_uint32),
)

# 後続を作り, seen 表に登録し, 初見だったものだけ返す
# ⚠️ -1=キャッチ勝ち / -2=トライ負け / >=0=未知 (初見の後続数). 規約が違う
nextBoardSeenNormal = lib.nextBoardSeenNormal
nextBoardSeenNormal.restype = c_int32
nextBoardSeenNormal.argtypes = (c_uint64, c_uint64_array48)

# 1ラウンドぶんの展開 (記録 #13). 局面ごとの FFI をラウンドあたり1回にまとめる
expandRound = lib.expandRound
expandRound.restype = c_int32
expandRound.argtypes = (
    POINTER(c_uint64), c_uint32,
    POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64),
)

# 直前の expandRound が積んだ初見の後続
expandNewPtr = lib.expandNewPtr
expandNewPtr.restype = c_void_p
expandNewPtr.argtypes = ()

expandNewCount = lib.expandNewCount
expandNewCount.restype = c_uint64
expandNewCount.argtypes = ()

expandFreeBuffer = lib.expandFreeBuffer
expandFreeBuffer.restype = None
expandFreeBuffer.argtypes = ()

# 174段ループの1段 (記録 #14). 辺 9.4 億本の走査を深さあたり1〜2回の呼び出しにまとめる
retreatStep = lib.retreatStep
retreatStep.restype = c_int32
retreatStep.argtypes = (
    POINTER(c_uint32), POINTER(c_uint32),      # pred, pred_off
    POINTER(c_ubyte), POINTER(c_ubyte),        # dtm, cnt (書き込み可能なまま渡す)
    c_uint32, c_uint32,                        # n_all, n_uk
    POINTER(c_uint32), c_uint32, c_uint32,     # frontier (NULL なら範囲), lo, hi
    c_ubyte, c_int32,                          # nd, odd
    POINTER(c_uint32), c_uint32,               # found の書き始め, 空き容量
    POINTER(c_uint32),                         # out[0] = 書いた数
)

# P2 後続生成の一区間 (記録 #15). 局面ごとの FFI を区間あたり1回にまとめる
buildSuccRange = lib.buildSuccRange
buildSuccRange.restype = c_int32
buildSuccRange.argtypes = (
    c_uint32, c_uint32, c_uint32,              # lo, hi, n_uk
    POINTER(c_uint32), c_uint32,               # 中継バッファ, その容量
    POINTER(c_uint32), POINTER(c_ubyte),       # succ_off, cnt (書き込み可能なまま渡す)
    c_uint32,                                  # base (succ に既に入っている辺の数)
    POINTER(c_int64),                          # out[4]
)

# 連番 → パック値 の翻訳 (記録 #19). 後退解析は連番で動くが dat/ に書くのは
# パック値で, #18 まではその翻訳が Python のリスト内包に残っていた
# (①174段ループ 96,802,868 回 / ②引き分けの抽出 99,485,568 回の走査).
# ⚠️ indexFree() のあと C は packed を持っていないので, どちらも引数で渡す
gatherPacked = lib.gatherPacked
gatherPacked.restype = c_int32
gatherPacked.argtypes = (
    POINTER(c_uint64), c_uint32,               # packed, n_all
    POINTER(c_uint32), c_uint32,               # found の書き始め, その数
    POINTER(c_uint64),                         # out (長さは n ちょうど)
)

gatherDraws = lib.gatherDraws
gatherDraws.restype = c_int32
gatherDraws.argtypes = (
    POINTER(c_uint64), POINTER(c_ubyte), c_uint32,   # packed, dtm, n_uk
    POINTER(c_uint64), c_uint32,                     # out (NULL なら数えるだけ), 容量
    POINTER(c_uint32),                               # n_out[0] = 書いた (数えた) 数
)

# ⚠️ dat/ は array("Q") の生バイト列をそのまま並べる (ヘッダ無し). 8 バイトで
#    リトルエンディアンであることは処理系依存なので, 起動時に1回だけ確かめる
#    (#13 以降の itemsize 検査と同じ置き方). ここが違う機械で読み書きすると,
#    オラクルも指紋も通らないが, 落ちる場所が遠くなる
def checkRawFormat():
    if array("Q").itemsize != 8:
        raise RuntimeError("array('Q') が8バイトでない：%d" % array("Q").itemsize)
    probe = array("Q", [1]).tobytes()
    if probe != b"\x01\x00\x00\x00\x00\x00\x00\x00":
        raise RuntimeError("array('Q') がリトルエンディアンでない：%r" % probe)
    back = array("Q")
    back.frombytes(probe)
    if len(back) != 1 or back[0] != 1:
        raise RuntimeError("array('Q') の往復が壊れている：%r" % back)

checkRawFormat()

# 盤面を1ファイル書き出す
#
# 記録 #15 まではここが pickle.dump で, BACK_UP が True のときだけ
# バックアップを取っていた. BACK_UP は baseline を含む16ファイルすべてで False で
# 一度も動いておらず, 拡張子が正規表現に埋まっていたので .bin にすると
# 「死んでいる」から「有効にしたら必ず落ちる」に変わる. CLAUDE.md が
# 「途中で落ちたら再開ではなく再走」と定めていて戻れても使い道がないので, 落とした。
#
# 記録 #17 で, 呼び出し側の set(...) を10か所とも外した. 集合を作ると要素ごとに
# PyLong を起こしてハッシュし, 約2N スロットの表を組み, それをランダム順に反復して
# uint64 に戻していた. obj が array("Q") のスライスなら, 外せば同型どうしの写しになる.
# ファイルに並ぶ順序は「渡された並びそのまま」で, それが後退解析の採番順になる
# (記録 #16 までは集合の反復順だった. experiments/numbering_order/).
#
# 記録 #19 で, list で来ていた2か所 (174段ループの翻訳と引き分けの抽出) を
# C 側の gatherPacked / gatherDraws に移した.
# ⚠️ obj は array("Q") かそのスライスか空の []. PyLong から uint64 への変換は
#    もう1か所も残っていない
def writeBoards(fnamew, obj):
    with open(fnamew, "wb") as f:
        f.write(array("Q", obj).tobytes())

# 盤面を1ファイル読み込む. pickle と違って要素ごとの PyLong を作らない (memcpy 1回)
def readBoards(fnamer):
    a = array("Q")
    with open(fnamer, "rb") as f:
        a.frombytes(f.read())
    return a

# 件数だけが要るとき. ヘッダが無いのでファイルを開かずに分かる
def countBoards(fnamer):
    return os.path.getsize(fnamer) // 8

# 秒を時間分秒のタプルで返す
def s2hms(s):
    s = int(s)
    return s // 3600, s % 3600 // 60, s % 60

# 勝ち盤面, 負け盤面をその深さのぶんまとめて書き出す (後退解析用)
#
# updateWLFile() は未知盤面チャンクごとに呼ばれるので, 毎回その深さの末尾ファイルを
# 読み直して書き直していた. 深さごとに1回だけ書くなら追記が要らないので,
# 読み出しは完全に無くなる. 空いている副番号から新しいファイルとして書くだけ.
#
# 副番号を 0 から連番に保つこと. loadAllWinBoards() も searchWinBoard() の
# 負け盤面ロードも「最初に見つからない番号で break」している.
def writeWLFilesForDepth(wlbl, wl_depth: int, win: bool) -> None:
    if win:
        wl_path_format = WIN_PATH_FORMAT
    else:
        wl_path_format = LOSE_PATH_FORMAT

    # 空いている副番号を探す
    # 1手勝ちは前向き探索が書いたファイルの続きになる (その末尾は上限未満のまま残る)
    wl_sub = 0
    while os.path.exists(wl_path_format.format(wl_depth, wl_sub)):
        wl_sub += 1

    # 0件でもファイルは作る
    # 次の手数の導出が win{N}te_000 / lose{N}te_000 の存在を見ているため
    if not wlbl:
        if wl_sub == 0:
            writeBoards(wl_path_format.format(wl_depth, 0), [])
        return

    # 添字で区切って書く. 残りのリストを作り直さない
    # (作り直すと, 呼び出し元が持つ元のリストと残り2枚が同居して RSS のピークを作る.
    #  全探索の終端 1.4 億件で +1.98 GiB, 実行全体のピークがここだった)
    for start in range(0, len(wlbl), BOARD_NUM_MAX):
        writeBoards(wl_path_format.format(wl_depth, wl_sub), wlbl[start:start + BOARD_NUM_MAX])
        wl_sub += 1

# 未知盤面 (探索済み) ファイルの更新
def updateUKFile(ukl):
    uk_sub = 0
    # 副番号探索
    for i in range(LOOP_MAX):
        fnamer_uk = UK_PATH_FORMAT.format(i)
        if os.path.exists(fnamer_uk):
            uk_sub = i
        else:
            break
    
    # ファイルが存在しない場合は作成 (空ファイルから)
    if i == 0:
        fnamer_uk = UK_PATH_FORMAT.format(i)
        writeBoards(fnamer_uk, [])
    
    # 最新の副番号のファイルに書き込む
    fnamew_uk = UK_PATH_FORMAT.format(uk_sub)
    # ひとつ前の未知盤面
    known_uk = readBoards(fnamew_uk)
    # 新しい未知盤面と結合
    ukl = known_uk + ukl

    # ファイルの上限を上回ったら, 分割
    # 3個以上の分割は考慮しない
    if len(ukl) > BOARD_NUM_MAX:
        # 上限まで元ファイルに書き出し
        writeBoards(fnamew_uk, ukl[:BOARD_NUM_MAX])
        # 残りは新ファイルへ. 残りのリストを作り直さず, 添字で区切る
        uk_sub += 1
        fnamew_uk = UK_PATH_FORMAT.format(uk_sub)
        writeBoards(fnamew_uk, ukl[BOARD_NUM_MAX:])
    else:
        # 元のファイルに書き戻し
        writeBoards(fnamew_uk, ukl)

# 発見済み盤面の集合をディスクから組み立てる (searchNext の初回だけ)
# 未知・1手勝ち・0手負け・未探索 の4つで, これまでに見つけた盤面の全体になる
# unexplored{offset} を読まないのは, 中身がすでに未知/勝ち/負けへ移っているため
# 毎回やらずにこれだけディスクを見るのは, 再開可能性を壊さないため
# (計測中に電源が落ちても, 次の起動でディスクの状態から作り直せる)
# ディスクにある発見済み盤面を C の表に入れ直す (searchNext の初回だけ)
# ⚠️ 空の dat/ から始める本番では, ここで読めるのは前段の updateUKFile が
#    書いた初期局面 1 個だけ. 表の中身は生成と同時に育っている
# ⚠️ 途中の dat/ から再開した場合, この関数より先に F1 の登録が走るので,
#    既出を初見と誤る. レギュレーションが再開を禁じている (再走する) 前提の割り切り
def buildSeenBoards(offset: int) -> tuple:
    t1 = time.time()
    n_seen = 0
    n_uk = 0
    n_win = 0
    n_lose = 0

    def insertAll(arr) -> int:
        # ファイルから読んだ array をそのまま C へ渡す. FFI はファイル1つにつき1回.
        # ⚠️ 表は所属しか見ないので, 入れる順が変わっても答えは変わらない
        added = seenInsertMany(cast(arr.buffer_info()[0], POINTER(c_uint64)), len(arr))
        if added < 0:
            raise RuntimeError("発見済み盤面を C の表に入れられない：%d" % added)
        return added
    # 未知盤面
    for i in range(LOOP_MAX):
        fnamer_uk = UK_PATH_FORMAT.format(i)
        if os.path.exists(fnamer_uk):
            past_boards = readBoards(fnamer_uk)
            n_seen += insertAll(past_boards)
            n_uk += len(past_boards)
        else:
            break

    # 勝ち盤面
    for i in range(LOOP_MAX):
        fnamer_win = WIN_PATH_FORMAT.format(1, i)
        if os.path.exists(fnamer_win):
            past_boards = readBoards(fnamer_win)
            n_seen += insertAll(past_boards)
            n_win += len(past_boards)
        else:
            break

    # 負け盤面
    for i in range(LOOP_MAX):
        fnamer_lose = LOSE_PATH_FORMAT.format(0, i)
        if os.path.exists(fnamer_lose):
            past_boards = readBoards(fnamer_lose)
            n_seen += insertAll(past_boards)
            n_lose += len(past_boards)
        else:
            break

    # 他の未探索盤面
    for i in range(offset + 1, LOOP_MAX):
        fnamer_unexp_another = UNEXP_PATH_FORMAT.format(i)
        if os.path.exists(fnamer_unexp_another):
            n_seen += insertAll(readBoards(fnamer_unexp_another))
        else:
            break

    printLogMain("ディスクから読んだ発見済み盤面：%d" % n_seen)
    printLogMain("再構築時間：{0:02d}時間{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t1)))
    return n_seen, n_uk, n_win, n_lose

# ---------------------------------------------------------------------------
# 全探索の計装. 後退解析の P0〜P4 と同じ扱いで, 記録実装に常設する
#
#   F0 未探索チャンクの読み込み / F1 展開 / F2 未知盤面の書き出し / F3 集合化
#   S  buildSeenBoards (初回のみ) / F4 重複排除 (差集合 + 合併) /
#   F5 未探索チャンクの書き出し / F6 終端の書き出し / 解放 (終端リストと seen 表)
#
# ⚠️ 記録 #11 で F3 と F4 は構造上 0 になる (C 側が登録の時点で重複を落とすため).
#    列は #10 までと比べられるように残してある. n_new_uniq も測る場所が無いので 0.
#    代わりに n_rehash (表を詰め直した回数) を足した
#
# ⚠️ 時計は区分ごとに1組. 1局面ごとの while ループの内側には置かない
#    (246,803,167 回呼ばれて, それだけで数十秒の歪みになる)
# ⚠️ 秒未満を切り捨てない. float のまま貯めて TSV に小数6桁で出す
#    (main.log の行は s2hms を通すので表示値は下限. 正確な値は TSV)
# ⚠️ 区分の境界で RSS (/proc/self/statm) と高水位 (VmHWM) を読む.
#    VmHWM が跳ねた境界を見れば, 境界の間で立つ一過性のピークがどの区分か分かる
# 実測のオーバーヘッドは 0.06 秒 (experiments/forward_profile/ の実績)
# ---------------------------------------------------------------------------
PROFILE_PATH = "./kaiseki_log/forward.tsv"
PROFILE_SUMMARY_PATH = "./kaiseki_log/forward_summary.tsv"
_pc = time.perf_counter
_PAGE = os.sysconf("SC_PAGE_SIZE")
# searchNext() が区分の値を置き, searchAll() がラウンド時間を足して1行にする
_prof = {}
_prof_round = 0

def _rssBytes() -> int:
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * _PAGE

def _hwmBytes() -> int:
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    return -1

def _profMark(name: str) -> None:
    """区分の境界. 時刻と RSS と高水位とページフォルトを記録する (1ラウンドに十数回だけ)

    ⚠️ ここにキーを足しても forward.tsv と forward_summary.tsv の列は増えない.
    どちらも PROFILE_COLUMNS と明示したキーを回して組み立てているため
    (記録 #18 までの forward.tsv は results/ の凍結物と列が揃っている).
    """
    _prof["t_" + name] = _pc()
    _prof["rss_" + name] = _rssBytes()
    _prof["hwm_" + name] = _hwmBytes()
    # ⚠️ getrusage は自分のぶんだけ. /usr/bin/time -v が親で受け取るものと同じ rusage なので,
    #    最後の境界の min_ は time.txt の Minor page faults と一致するはず (記録ノートで照合する)
    _ru = resource.getrusage(resource.RUSAGE_SELF)
    _prof["min_" + name] = _ru.ru_minflt
    _prof["maj_" + name] = _ru.ru_majflt

# 境界の名前 (RSS と高水位をこの順で列にする)
PROFILE_MARKS = (
    "start", "F0_begin", "F0", "F1_begin", "F1", "F2_begin", "F2",
    "F3_begin", "F3", "F4_begin", "F4_mid", "F4", "F5_begin", "F5",
)
PROFILE_COUNTS = (
    "n_in", "n_win", "n_lose", "n_uk", "n_new_pre", "n_new_uniq", "n_new_post",
    "n_seen", "n_rehash", "n_catch_total", "n_try_total",
)
PROFILE_TIMES = ("F0", "F1", "F2", "F3", "S", "F4", "F4_diff", "F4_union", "F5")
PROFILE_COLUMNS = (
    ("round",) + PROFILE_COUNTS + PROFILE_TIMES + ("round_total", "residual")
    + tuple("rss_" + m for m in PROFILE_MARKS) + tuple("hwm_" + m for m in PROFILE_MARKS)
)

# ---- 後退解析側の計装 (記録 #19) --------------------------------------------
#
# #18 まで _profMark の対象は F0〜F5, つまり全探索だけだった. 揺れているのは
# 後退解析のほうなのに, そちらには境界が1つも無い. gate_15 の16本では
# minor page fault の多い走行と P2 の遅い走行が完全に一致していて,
# experiments/retreat_profile/ が段ごとに割ったところ, 遅れは索引を作る段
# (P0→P1) に集中していた. /usr/bin/time -v は走行全体の合計しか出さないので,
# どの段で起きているかは本走の記録から後で読めない.
#
# ⚠️ 174段ループの内側には置かない (CLAUDE.md「ホットループの内側に時計を置かない」).
RETREAT_SUMMARY_PATH = "./kaiseki_log/retreat_summary.tsv"
RETREAT_MARKS = (
    "R_start",     # retreatAnalysis() の入口 (再開検査の後)
    "P0",          # loadForwardResult() の直後
    "P1",          # buildIndex() の直後
    "P2_alloc",    # buildSuccessors() の中. succ_off / cnt / stage を確保した直後
    "P2",          # buildSuccessors() の直後
    "P2_free",     # indexFree() の直後
    "P4_count",    # buildPredecessors() の中. predCount の直後
    "P4",          # buildPredecessors() の直後
    "R_dtm",       # dtm / found_buf を確保し終えた直後 (174段ループの直前)
    "R_loop",      # 174段ループを抜けた直後 (＝引き分けの抽出を始める点)
    "R_draw",      # 引き分けの抽出が終わった直後 (記録 #19 で足した1つ)
    "R_uk",        # writeUnknownChunks() の直後
)
# 読む側が毎回引き算しなくて済むように, 隣り合う境界の差だけ名前を付けておく
#
# ⚠️ R_loop→R_draw が記録 #19 の標的の片方. #18 までは引き分けの抽出が
#    writeUnknownChunks() の引数の中にあり, 関数の中で始まるタイマーより前に
#    終わっていたので, main.log の「未知盤面の書き出し時間」には入っていなかった.
#    9,948 万回の走査が後退解析の残差に埋もれていた.
RETREAT_SPANS = (
    ("P0", "R_start", "P0"),
    ("P1", "P0", "P1"),
    ("P2_alloc", "P1", "P2_alloc"),
    ("P2_loop", "P2_alloc", "P2"),
    ("P2", "P1", "P2"),
    ("P2_free", "P2", "P2_free"),
    ("P4_count", "P2_free", "P4_count"),
    ("P4_scatter", "P4_count", "P4"),
    ("P4", "P2_free", "P4"),
    ("R_dtm", "P4", "R_dtm"),
    ("loop174", "R_dtm", "R_loop"),
    ("R_draw", "R_loop", "R_draw"),
    ("R_uk", "R_draw", "R_uk"),
    ("retreat_total", "R_start", "R_uk"),
)

def _retreatWriteSummary() -> None:
    """2列の TSV を1本書く. forward_summary.tsv と同じ形.

    ⚠️ カウンタは絶対値で %d. 丸めない. 差分は読む側で引く
    (RETREAT_SPANS はあくまで手間を省くためのもので, 元の値も全部出す).
    """
    with open(RETREAT_SUMMARY_PATH, "w", encoding="utf-8") as f:
        for name, a, b in RETREAT_SPANS:
            f.write("%s\t%.4f\n" % (name, _prof["t_" + b] - _prof["t_" + a]))
        base = _prof["t_R_start"]
        for m in RETREAT_MARKS:
            f.write("t_%s\t%.4f\n" % (m, _prof["t_" + m] - base))
            f.write("rss_%s\t%d\n" % (m, _prof["rss_" + m]))
            f.write("hwm_%s\t%d\n" % (m, _prof["hwm_" + m]))
            f.write("min_%s\t%d\n" % (m, _prof["min_" + m]))
            f.write("maj_%s\t%d\n" % (m, _prof["maj_" + m]))

def _profWriteHeader() -> None:
    """searchAll() の入口で呼ぶ. 前回の行が残っていても上書きして始める"""
    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        f.write("\t".join(PROFILE_COLUMNS) + "\n")

def _profWriteRow(row: dict) -> None:
    with open(PROFILE_PATH, "a", encoding="utf-8") as f:
        f.write("\t".join(
            ("%.6f" % row[c]) if isinstance(row[c], float) else str(row[c])
            for c in PROFILE_COLUMNS
        ) + "\n")

# まずは全盤面を洗い出したい
# 葉ノード (一手で勝てる盤面) は別ファイルに書き出す
# 初期盤面からの手数は考慮せず, 勝ち, 負け, 未知の3種に分けて保存
def searchNext():
    global seen_boards, tbn_uk, tbn_win, tbn_lose, catch_wins, try_loses
    _prof.clear()
    _profMark("start")
    if not os.path.isdir(DIR_PATH):
        print("ディレクトリ「%s」を作成してください" % DIR_PATH)
        return True
    
    offset = -1
    latest = 0
    # 未探索盤面の検索
    for i in range(LOOP_MAX):
        fnamer_unexp = UNEXP_PATH_FORMAT.format(i)
        # 最初に見つけたファイルの番号をオフセットとし, そのファイルを探索
        if os.path.exists(fnamer_unexp):
            if offset < 0:
                offset = i
            # 存在する最新の番号も保存
            latest = i
        elif offset >= 0:
            break
    
    # 未探索盤面ファイルが存在しない
    if offset < 0:
        fnamer_uk = UK_PATH_FORMAT.format(0)
        # 未探索盤面が存在しないが未知盤面が存在した場合, 解析終了と判断する
        if os.path.exists(fnamer_uk):
            print("探索済み")
            return True
        # 初期盤面だけをファイルに書き込む
        offset = 0
        fnamer_unexp = UNEXP_PATH_FORMAT.format(0)
        writeBoards(fnamer_unexp, [INITIAL_BOARD])
    else:
        fnamer_unexp = UNEXP_PATH_FORMAT.format(offset)

    printLogSub(fnamer_unexp + " を探索")
    # 未探索の盤面をロード
    _profMark("F0_begin")
    unexp_boards = readBoards(fnamer_unexp)
    _profMark("F0")
    _prof["n_in"] = n = len(unexp_boards)
    printLogSub("探索盤面数：{:d}".format(len(unexp_boards)))

    # 次の状態を計算し, 末端であれば勝ちか負けに振り分ける
    #
    # ⚠️ 展開の順は「ファイルに並んでいる順」. #12 までは
    #    「while unexp_boards: board = unexp_boards.pop()」で, CPython の set.pop()
    #    が表を前から走査するので集合の反復順だった. #16 で読み側が frombytes に,
    #    #17 で書き側の set(...) が外れたので, いまは前のラウンドが書いた順そのまま
    _gen0 = seenProbes()
    _rehash0 = seenRehashes()
    _profMark("F1_begin")
    arr = array("Q", unexp_boards)
    # C を呼ぶ前に読み込んだ配列を手放す (写しは arr に取ってある)
    del unexp_boards
    # ⚠️ array("Q") が8バイトである保証は処理系依存 (#12 が array("I") でやったのと同じ)
    if arr.itemsize != 8:
        raise RuntimeError("array('Q') が8バイトでない：%d" % arr.itemsize)
    # 勝ち・負け・未知は3本あわせてちょうど n 本. 上限ぶん確保して渡す
    win_boards = array("Q", bytes(8)) * n
    lose_boards = array("Q", bytes(8)) * n
    uk_boards = array("Q", bytes(8)) * n
    counts = array("Q", bytes(8)) * 5
    rc = expandRound(
        cast(arr.buffer_info()[0], POINTER(c_uint64)), n,
        cast(win_boards.buffer_info()[0], POINTER(c_uint64)),
        cast(lose_boards.buffer_info()[0], POINTER(c_uint64)),
        cast(uk_boards.buffer_info()[0], POINTER(c_uint64)),
        cast(counts.buffer_info()[0], POINTER(c_uint64)),
    )
    # ⚠️ 握りつぶさない. -2 はバッファ, -3 は表を確保できなかった場合で,
    #    どちらもそのラウンドはやり直せない (そこまでの後続はもう表に入っている)
    if rc != 0:
        raise RuntimeError("後続を作れない：%d" % rc)
    del arr
    win_boards = win_boards[:counts[0]]
    lose_boards = lose_boards[:counts[1]]
    uk_boards = uk_boards[:counts[2]]
    # 初見の後続を C のバッファから1回のコピーで受け取る
    # (要素ごとに読むと 2.5 億個の PyLong を作ることになる. 記録 #1 の罠)
    new_unexp_boards = array("Q")
    _n_new = expandNewCount()
    if _n_new:
        new_unexp_boards.frombytes(
            memoryview((c_uint64 * _n_new).from_address(expandNewPtr())).cast("B")
        )
    _profMark("F1")
    _prof["n_win"] = len(win_boards)
    _prof["n_lose"] = len(lose_boards)
    _prof["n_uk"] = len(uk_boards)
    # 生成した後続の総数. Python 側はもう持っていないので C の計数器の差で取る
    # (#10 までの n_new_pre と同じ意味・同じ値)
    _prof["n_new_pre"] = seenProbes() - _gen0
    _prof["n_rehash"] = seenRehashes() - _rehash0
    
    printLogSub("勝ち盤面数：{:d}, 負け盤面数：{:d}, 未知盤面数：{:d}".format(
        len(win_boards), len(lose_boards), len(uk_boards)
    ))

    # 末端は貯めるだけ. 書き出しは searchAll() の最後に1回
    #
    # ⚠️ ここで書かなくなったぶん, 次の buildSeenBoards() は win001te_* /
    #    lose000te_* を読めない. 初回ラウンドは初期局面1個しか見ず終端が0個なので
    #    新規の走行では影響しない (n_win = n_lose = 0 が正しい初期値になる).
    #    途中の dat/ から再開した場合は終端が seen に入らないが, それは再走する場面
    catch_wins += win_boards
    try_loses += lose_boards
    _prof["n_catch_total"] = len(catch_wins)
    _prof["n_try_total"] = len(try_loses)
    # 未知盤面の更新
    _profMark("F2_begin")
    updateUKFile(uk_boards)
    _profMark("F2")

    printLogSub("新状態数 (重複排除前)：{:d}".format(_prof["n_new_pre"]))

    # 集合化 (F3) は要らない. C 側が登録の時点でラウンド内の重複も落としている
    _profMark("F3_begin")
    _profMark("F3")
    # ⚠️ 集合化後の一意数は測る場所が無くなった (#10 の n_new_uniq). 0 を入れる
    _prof["n_new_uniq"] = 0

    # 発見済み盤面との重複排除
    # 以前は unknown / win001te / lose000te / 他の unexplored を毎回読み直していた
    # この4つは発見済み集合の分割なので, 順に引くことと和集合を1回引くことは同値
    _prof["S"] = 0.0
    if seen_boards is None:
        _t = _pc()
        seen_boards, tbn_uk, tbn_win, tbn_lose = buildSeenBoards(offset)
        _prof["S"] = _pc() - _t
    else:
        # このラウンドで振り分けた分は既存ファイルの中身と互いに素なので, 足すだけでよい
        tbn_uk += len(uk_boards)
        tbn_win += len(win_boards)
        tbn_lose += len(lose_boards)

    # 重複排除 (F4) も要らない. #10 では差集合 385 秒 + 合併 112 秒だった仕事が,
    # 後続を作ったその場での1回の挿入に変わっている
    _profMark("F4_begin")
    _profMark("F4_mid")
    _profMark("F4")
    _prof["n_new_post"] = len(new_unexp_boards)
    _prof["n_seen"] = seenCount()

    # ⚠️ ここから先が F5. #10 までは集合をリストに戻していたが, もうリストのまま
    _profMark("F5_begin")
    printLogSub("新状態数 (重複排除後)：{:d}".format(len(new_unexp_boards)))
    printLogSub("総未知盤面数：{:d}, 総勝ち盤面数：{:d}, 総負け盤面数：{:d}".format(
        tbn_uk, tbn_win, tbn_lose
    ))

    # 全探索終了
    if not new_unexp_boards:
        printLogSub("探索終了")
        # メインに書き込み
        printLogMain("総未知盤面数：{:d}, 総勝ち盤面数：{:d}, 総負け盤面数：{:d}".format(
            tbn_uk, tbn_win, tbn_lose
        ))
        # ファイル削除
        os.remove(fnamer_unexp)
        # 書き出しは通らない. 境界だけ記録する (F5 = 0)
        _profMark("F5_begin")
        _profMark("F5")
        return True
    
    # 書き込みファイルが読み込みファイルと同じなら, 空で初期化
    if offset == latest:
        writeBoards(fnamer_unexp, [])
    # 異なればファイル削除
    else:
        os.remove(fnamer_unexp)
    
    # 書き込み先ファイル
    fnamew_unexp = UNEXP_PATH_FORMAT.format(latest)
    # 読み込んでリストに変換
    old_unexp_boards = readBoards(fnamew_unexp)
    # 結合
    new_unexp_boards = old_unexp_boards + new_unexp_boards
    # 分割してファイルに保存 (先頭は latest 番, 以後 1 つずつ番号を進める)
    # 添字で区切って書く. 残りのリストを作り直さない
    for start in range(0, len(new_unexp_boards), BOARD_NUM_MAX):
        writeBoards(UNEXP_PATH_FORMAT.format(latest), new_unexp_boards[start:start + BOARD_NUM_MAX])
        # 最新番号の更新
        latest += 1
    _profMark("F5")

    return False

# 貯めた終端局面を書き出す (全探索の最後に1回)
# writeWLFilesForDepth() は既存ファイルを一切読まないので, 読み直しはゼロになる
def flushTerminalBoards():
    global catch_wins, try_loses
    _profMark("F6_begin")
    writeWLFilesForDepth(catch_wins, 1, True)
    writeWLFilesForDepth(try_loses, 0, False)
    _profMark("F6")
    # 後退解析が始まる前に手放す (147,317,599 件ぶん)
    catch_wins = array("Q")
    try_loses = array("Q")
    _profMark("release_wl")

# 全盤面が出るまで探索
def searchAll():
    global seen_boards, _prof_round
    t0 = time.time()
    _t_all = _pc()
    # 発見済み表を空から始める (前の走行の残りを持ち込まない)
    if seenInit() != 0:
        raise RuntimeError("発見済み表を確保できない")
    _profWriteHeader()
    _sum = {k: 0.0 for k in PROFILE_TIMES + ("round_total", "residual")}
    for _ in range(LOOP_MAX):
        _t_round = _pc()
        flag = searchNext()
        _round_total = _pc() - _t_round
        # 探索が始まる前に返る経路 (dat/ が無い / 探索済み) には区分の境界が無い.
        # 行を作らずに抜ける (空の dat/ から走らせる本番では通らない)
        if "t_F5" not in _prof:
            break
        _prof_round += 1
        _row = {"round": _prof_round, "round_total": _round_total}
        for a, b in (("F0", "F0"), ("F1", "F1"), ("F2", "F2"), ("F3", "F3"),
                     ("F4_diff", "F4_mid"), ("F5", "F5")):
            _row[a] = _prof["t_" + b] - _prof["t_" + a.split("_")[0] + "_begin"]
        _row["F4_union"] = _prof["t_F4"] - _prof["t_F4_mid"]
        _row["F4"] = _row["F4_diff"] + _row["F4_union"]
        _row["S"] = _prof["S"]
        _row["residual"] = _round_total - sum(_row[k] for k in PROFILE_TIMES if k != "F4")
        for k in PROFILE_COUNTS:
            _row[k] = _prof.get(k, 0)
        for m in PROFILE_MARKS:
            _row["rss_" + m] = _prof["rss_" + m]
            _row["hwm_" + m] = _prof["hwm_" + m]
        for k in _sum:
            _sum[k] += _row[k]
        _profWriteRow(_row)
        dt_now = datetime.datetime.now()
        printLogSub(dt_now.strftime('%Y-%m-%d %H:%M:%S'))
        delta_t = int(time.time() - t0)
        printLogSub("%02d時間%02d分%02d秒経過" % (delta_t // 3600, delta_t % 3600 // 60, delta_t % 60))
        if flag:
            break
    # 貯めた終端盤面を書き出す (書き出し時間は全探索側に計上)
    flushTerminalBoards()
    _f6 = _prof["t_F6"] - _prof["t_F6_begin"]
    _release_wl = _prof["t_release_wl"] - _prof["t_F6"]
    # 発見済み表を解放する
    # 後退解析が索引 (8.59 GB) を作る前に手放す (解放時間は全探索側に計上)
    seenFree()
    # 展開バッファ (記録 #13) も同じところで手放す
    expandFreeBuffer()
    seen_boards = None
    _profMark("release_seen")
    _release_seen = _prof["t_release_seen"] - _prof["t_release_wl"]
    _total = _pc() - _t_all
    delta_t = int(time.time() - t0)
    printLogMain("%02d時間%02d分%02d秒で全探索終了" % (delta_t // 3600, delta_t % 3600 // 60, delta_t % 60))
    # 区分ごとの内訳. ⚠️ ここは s2hms を通すので表示値は下限. 正確な値は forward.tsv
    _in_rounds = sum(_sum[k] for k in PROFILE_TIMES if k != "F4")
    for _name, _label, _sec in (
        ("F0", "未探索の読み込み", _sum["F0"]), ("F1", "展開", _sum["F1"]),
        ("F2", "未知の書き出し", _sum["F2"]), ("F3", "集合化", _sum["F3"]),
        ("F4", "重複排除", _sum["F4"]), ("  F4a", "  差集合", _sum["F4_diff"]),
        ("  F4b", "  合併", _sum["F4_union"]), ("F5", "未探索の書き出し", _sum["F5"]),
        ("F6", "終端の書き出し", _f6), ("--", "解放", _release_wl + _release_seen),
        ("--", "残差", _total - _in_rounds - _f6 - _release_wl - _release_seen),
    ):
        printLogMain("%s %s：%02d時間%02d分%02d秒" % ((_name, _label) + s2hms(_sec)))
    # 機械が読むほうは切り捨てない
    with open(PROFILE_SUMMARY_PATH, "w", encoding="utf-8") as f:
        f.write("rounds\t%d\n" % _prof_round)
        for k in PROFILE_TIMES:
            f.write("%s\t%.4f\n" % (k, _sum[k]))
        f.write("F6\t%.4f\n" % _f6)
        f.write("release_wl\t%.4f\n" % _release_wl)
        f.write("release_seen\t%.4f\n" % _release_seen)
        f.write("sum_rounds_F\t%.4f\n" % _in_rounds)
        f.write("sum_round_total\t%.4f\n" % _sum["round_total"])
        f.write("residual_in_rounds\t%.4f\n" % _sum["residual"])
        f.write("forward_total\t%.4f\n" % _total)
        f.write("residual_total\t%.4f\n" % (_total - _in_rounds - _f6 - _release_wl - _release_seen))
        for m in ("F6_begin", "F6", "release_wl", "release_seen"):
            f.write("rss_%s\t%d\n" % (m, _prof["rss_" + m]))
            f.write("hwm_%s\t%d\n" % (m, _prof["hwm_" + m]))

# 全盤面の数を出力 (全盤面計算後のテスト用)
def countTotalBoardNum():
    tbn_uk = 0
    tbn_win = 0
    tbn_lose = 0
    for i in range(LOOP_MAX):
        fnamer = UK_PATH_FORMAT.format(i)
        if os.path.exists(fnamer):
            print(fnamer, "を数える")
            tbn_uk += countBoards(fnamer)
        else:
            break
    for i in range(LOOP_MAX):
        fnamer = WIN_PATH_FORMAT.format(1, i)
        if os.path.exists(fnamer):
            print(fnamer, "を数える")
            tbn_win += countBoards(fnamer)
        else:
            break
    for i in range(LOOP_MAX):
        fnamer = LOSE_PATH_FORMAT.format(0, i)
        if os.path.exists(fnamer):
            print(fnamer, "を数える")
            tbn_lose += countBoards(fnamer)
        else:
            break
    print("未知盤面数：{:d}".format(tbn_uk))
    print("勝ち盤面数：{:d}".format(tbn_win))
    print("負け盤面数：{:d}".format(tbn_lose))
    print("末端盤面数：{:d}".format(tbn_win + tbn_lose))
    print("全盤面数　：{:d}".format(tbn_uk + tbn_win + tbn_lose))

# 標準出力でなくファイルに出力
# 引数は文字列一つであることに注意
# moji は文字列じゃなくてもいい
def printLog(fnamea, moji):
    with open(fnamea, "a", encoding="utf-8") as f:
        print(moji, file=f)

# サブログファイル (高頻度出力)
def printLogSub(moji):
    if LOG_PATH_SUB:
        printLog(LOG_PATH_SUB, moji)

# メインログファイル (低頻度出力)
def printLogMain(moji):
    printLog(LOG_PATH_MAIN, moji)

# 未知盤面を全てメモリへ
# ディスクに置いていたのは 2021 年当時のメモリ制約の名残
# 所属判定には使われず pop() と len() だけなので, 集合である必要も無い
# (リストなら 40B/要素. 集合だと 2^28 の表で 77B/要素かかる)
#
# 読んだファイルはその場で消す
# 途中で落ちたときに古い未知盤面が残っていると,
# 「再開できそうに見えて中身が古い」という一番たちの悪い壊れ方をする
# 途中落ちは再走なので, 紛らわしい残骸を残さないのが正しい
# 進捗は win{N}te_* / lose{N}te_* が深さごとに書かれるので, そちらで分かる
def loadAllUnknownBoards() -> list:
    t1 = time.time()
    uk_chunks = []
    for i in range(LOOP_MAX):
        fnamer_uk = UK_PATH_FORMAT.format(i)
        if not os.path.exists(fnamer_uk):
            break
        uk_chunks.append(readBoards(fnamer_uk))
        os.remove(fnamer_uk)
    printLogMain("常駐させた未知盤面：%d (%d チャンク)" % (
        sum(len(c) for c in uk_chunks), len(uk_chunks)
    ))
    printLogMain("未知盤面の読み込み時間：{0:02d}時間{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t1)))
    return uk_chunks

# 最後まで未知だった盤面 (＝引き分け) を成果物として書き出す
# 到達可能な全局面を成果物に含めるための最後の一手間で,
# tools/fingerprint_dat.py の照合もここを見る
def writeUnknownChunks(uk_chunks: list) -> None:
    t1 = time.time()
    # ⚠️ 受け皿を list から array("Q") に変えた (記録 #19). 呼び出し側が
    #    array("Q") を渡すようになったので, list のままだと繋ぎ直す段で
    #    要素ごとの PyLong が戻ってきて, C に移した意味が消える.
    #    区切り方 (添字で BOARD_NUM_MAX ずつ) は #18 のまま
    rest = array("Q")
    for chunk in uk_chunks:
        rest.extend(chunk)
    total = len(rest)
    files_num = 0
    # 空でも1ファイルは作る (後退解析が全部を確定させた場合)
    if not rest:
        writeBoards(UK_PATH_FORMAT.format(0), [])
        files_num = 1
    # 添字で区切って書く. 残りのリストを作り直さない
    for start in range(0, total, BOARD_NUM_MAX):
        writeBoards(UK_PATH_FORMAT.format(files_num), rest[start:start + BOARD_NUM_MAX])
        files_num += 1
    printLogMain("書き出した未知盤面：%d (%d ファイル)" % (total, files_num))
    printLogMain("未知盤面の書き出し時間：{0:02d}時間{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t1)))

# ---- 後退解析: 連番化 + CSR 前任リスト + カウンタ ----------------------------
#
# #5 までは未確定局面を174ラウンド舐め直し, そのたびに指し手を作り直していた.
# 延べ訪問 1,479,788,351 回 (局面 246,803,167 の6倍) のうち,
# 48.1% は同一ラウンド内の作り直し, 31.5% は引き分けの空振りだった.
# 原因は「前任局面を引けないこと」の一点.
#
# 前任リストがあれば, 辺 938,671,869 本をちょうど1回ずつ通るだけで済む.
# 引き分け 2,682,700 は cnt が 0 にならず勝ち後続も来ないので, 特別扱いのコード無しに
# 一度も触られずに残る (#5 の空振り 31.5% が構造として消える).
#
# 連番の並びは3群を連続させる:
#     [0, n_uk)                  未知      (辺はここからしか出ない)
#     [n_uk, n_uk + n_win)       キャッチ  (1手勝ち)
#     [n_uk + n_win, n_all)      トライ負け (0手負け)
# 連番は全単射でありさえすればよく順序に意味は無いので, パック値のソートはしない.
# 群を連続させておくと cnt[] と succ_off[] が未知のぶんだけで済み,
# 深さ0と深さ1の初期フロンティアが range() になる.

# 指定した手数のファイルを packed の末尾へ足して, 足した数を返す
def appendFamily(packed, path_format, depth: int) -> int:
    before = len(packed)
    for i in range(LOOP_MAX):
        fnamer = path_format.format(depth, i)
        if not os.path.exists(fnamer):
            break
        packed.extend(readBoards(fnamer))
    return len(packed) - before

# 前向き探索の成果物を読んで, 連番を振った packed[] にする
def loadForwardResult() -> tuple:
    t1 = time.time()
    packed = array("Q")
    # 未知盤面 (読んだファイルはその場で消える)
    # チャンクは1本ずつ捨てながら移す. int オブジェクトを全部同時に抱えないため
    uk_chunks = loadAllUnknownBoards()
    while uk_chunks:
        packed.extend(uk_chunks.pop())
    n_uk = len(packed)
    # キャッチ (1手勝ち) と トライ負け (0手負け) は前向き探索が確定させている
    n_win = appendFamily(packed, WIN_PATH_FORMAT, 1)
    n_lose = appendFamily(packed, LOSE_PATH_FORMAT, 0)
    printLogMain("読み込んだ局面：%d (未知 %d / キャッチ %d / トライ負け %d)" % (
        len(packed), n_uk, n_win, n_lose
    ))
    printLogMain("P0 読み込み：{0:02d}時間{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t1)))
    return packed, n_uk, n_win, n_lose

# パック値 → 連番 の索引をC側に作る
# 構築でしか使わない. pred[] を確保する前に捨てるのがピークを決める
#
# Python の dict は 2.4 億件で 24.41 GiB に膨らみ, 1回の引きに約 0.85 µs
# かかっていた. C側のフラットハッシュ表なら 8.59 GB で, 1回の引きで触る
# キャッシュラインが1本で済む
#
# ⚠️ C は packed の生ポインタを持つ. indexFree() までリサイズしてはいけない
def buildIndex(packed) -> None:
    t1 = time.time()
    ptr = cast(packed.buffer_info()[0], POINTER(c_uint64))
    rc = indexBuild(ptr, len(packed))
    # -5 は「キーが重複している」. 3群が互いに素であることの検算で,
    # #6・#7 の if len(idx) != len(packed) に相当する
    if rc != 0:
        raise RuntimeError("索引を作れない：%d (局面数 %d)" % (rc, len(packed)))
    printLogMain("P1 索引：{0:02d}時間{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t1)))

# 未知局面の後続を連番で並べた CSR (succ, succ_off) と, 出次数 cnt を作る
#
# #14 までは局面ごとに nextBoardIndexNormal を呼んでいた (99,485,568 回).
# 記録 #15 でその for をC側へ移し, Python がするのは
# 「中継バッファに返ってきたバイト列を succ に繋ぐ」だけになった (約 14,300 回)
def buildSuccessors(n_uk: int) -> tuple:
    t1 = time.time()
    succ = array("I")
    # 長さが先に分かるものは Python 側で確保して C に直接埋めさせる
    succ_off = array("I", bytes(4)) * (n_uk + 1)
    cnt = bytearray(n_uk)
    # ⚠️ array("I") が4バイトである保証は処理系依存. C に渡す前に確かめる
    if succ.itemsize != 4 or succ_off.itemsize != 4:
        raise RuntimeError("array('I') が4バイトでない：%d / %d" % (succ.itemsize, succ_off.itemsize))
    if len(cnt) != n_uk:
        raise RuntimeError("cnt の長さが未知局面数と違う：%d / %d" % (len(cnt), n_uk))
    # ⚠️ succ を先に確保して C に直接書かせない. 触ったページだけが常駐するので,
    #    0 で埋めて確保した時点で余分ぶんがそのままピーク RSS に乗る
    #    (全体のピークを決めているのは P2 の末尾). 中継バッファを経由して,
    #    succ の伸び方は #14 までと同じ array("I") の継ぎ足しのままにする
    stage = array("I", bytes(4)) * SUCC_STAGE
    stage_mv = memoryview(stage).cast("B")
    stage_ptr = cast(stage.buffer_info()[0], POINTER(c_uint32))
    succ_off_ptr = cast(succ_off.buffer_info()[0], POINTER(c_uint32))
    # ⚠️ from_buffer はゼロコピー. from_buffer_copy にすると C が書いた出次数が
    #    cnt に出ず, 174段ループが1局面も確定できなくなる
    cnt_c = (c_ubyte * n_uk).from_buffer(cnt)
    _profMark("P2_alloc")
    out = c_int64_array4()
    frombytes = succ.frombytes
    total = 0
    outside = 0
    i = 0
    # 進捗行は #14 までと同じ位置 (1000万件ごと) に出す. 出しているのは
    # 「その局面を処理した直後の辺の総数」なので, 区間の切れ目をそこに合わせる
    for hi in sorted({m + 1 for m in range(0, n_uk, 10000000)} | {n_uk}):
        while i < hi:
            rc = buildSuccRange(i, hi, n_uk, stage_ptr, SUCC_STAGE,
                                succ_off_ptr, cnt_c, total, out)
            # 0 (キャッチ) と -1 (トライ負け) なら未知盤面に終端が混ざっている.
            # -3 は src が範囲外か索引が未構築. どれもバグなので区別せず落とす
            if rc == -5:
                raise RuntimeError("未知盤面の後続を作れない：%d 番目 (戻り値 %d)" % (out[1], out[3]))
            # ⚠️ 握りつぶさない. -1 は引数不正, -6 は出次数が cnt に収まらない,
            #    -7 は辺の総数が uint32 を超えた場合で, どれも不変条件が崩れている
            if rc != 0:
                raise RuntimeError("後続の区間を作れない：%d (%d 番目)" % (rc, out[1]))
            frombytes(stage_mv[: 4 * out[0]])
            total += out[0]
            outside += out[2]
            i = out[1]
        if (hi - 1) % 10000000 == 0:
            printLogSub("P2 後続生成 {0:d}/{1:d} 辺 {2:d} {4:02d}分{5:02d}秒経過".format(
                hi - 1, n_uk, total, *s2hms(time.time() - t1)
            ))
    printLogMain("辺の総数：%d (未発見の後続 %d)" % (total, outside))
    printLogMain("P2 後続生成：{0:02d}時間{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t1)))
    return succ, succ_off, cnt

# 辺の向きを逆にして CSR に詰め直す (計数ソート)
def buildPredecessors(succ, succ_off, n_all: int) -> tuple:
    t1 = time.time()
    # ⚠️ array("I") が4バイトである保証は処理系依存. C に渡す前に確かめる
    if succ.itemsize != 4 or succ_off.itemsize != 4:
        raise RuntimeError("array('I') が4バイトでない：%d / %d" % (succ.itemsize, succ_off.itemsize))
    n_edges = len(succ)
    n_uk = len(succ_off) - 1
    # 入次数を q+1 の位置に数えると, 累積和がそのままオフセットになる (C 側も同じ形)
    pred_off = array("I", bytes(4)) * (n_all + 1)
    rc = predCount(
        cast(succ.buffer_info()[0], POINTER(c_uint32)), n_edges,
        n_all, cast(pred_off.buffer_info()[0], POINTER(c_uint32)),
    )
    if rc != 0:
        raise RuntimeError("入次数を数えられない：%d" % rc)
    _profMark("P4_count")
    printLogSub("P4 入次数まで {0:02d}時間{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t1)))
    # 散らす. ⚠️ カーソルの複製 (#11 までの cur = pred_off[:n_all], 987 MB) は作らない
    pred = array("I", bytes(4)) * n_edges
    rc = predScatter(
        cast(succ.buffer_info()[0], POINTER(c_uint32)), n_edges,
        cast(succ_off.buffer_info()[0], POINTER(c_uint32)), n_uk,
        n_all,
        cast(pred.buffer_info()[0], POINTER(c_uint32)),
        cast(pred_off.buffer_info()[0], POINTER(c_uint32)),
    )
    if rc != 0:
        raise RuntimeError("前任リストを散らせない：%d" % rc)
    # C 側でも検算しているが, O(1) なので Python 側にも残す
    if pred_off[n_all] != n_edges:
        raise RuntimeError("前任リストの総数が合わない：%d / %d" % (pred_off[n_all], n_edges))
    printLogMain("P4 前任リスト：{0:02d}時間{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t1)))
    return pred, pred_off

def retreatAnalysis():
    """
    全探索終了後に実行
    よくわからないけど後退解析と呼ぶらしい
    """
    # 構造を全てメモリ上に作り直すので, 途中まで進んだ dat/ からは再開できない
    # 黙って違う答えを出すより, ここで止める
    for fnamer in (WIN_PATH_FORMAT.format(3, 0), LOSE_PATH_FORMAT.format(2, 0)):
        if os.path.exists(fnamer):
            raise RuntimeError("途中まで進んだ dat/ からは再開できない：%s" % fnamer)

    _profMark("R_start")
    packed, n_uk, n_win, n_lose = loadForwardResult()
    _profMark("P0")
    n_all = len(packed)
    buildIndex(packed)
    _profMark("P1")
    succ, succ_off, cnt = buildSuccessors(n_uk)
    _profMark("P2")
    # 後続は連番で入っているので, ここから先で索引は要らない
    indexFree()
    _profMark("P2_free")
    pred, pred_off = buildPredecessors(succ, succ_off, n_all)
    del succ, succ_off
    _profMark("P4")

    # 手数. 255 が未確定で, 最後まで 255 のものが引き分けになる
    # 奇数が勝ち, 偶数が負け (パリティで判別できるので結果ビットは要らない)
    dtm = bytearray(b"\xff") * n_all
    catch_lo = n_uk
    catch_hi = n_uk + n_win
    dtm[catch_lo:catch_hi] = b"\x01" * n_win
    dtm[catch_hi:] = bytes(n_lose)

    # ⚠️ array("I") が4バイト, bytearray が1要素1バイトであることは処理系依存
    if pred.itemsize != 4 or pred_off.itemsize != 4:
        raise RuntimeError("array('I') が4バイトでない：%d / %d" % (pred.itemsize, pred_off.itemsize))
    if len(dtm) != n_all or len(cnt) != n_uk:
        raise RuntimeError("dtm / cnt の長さが合わない：%d / %d" % (len(dtm), len(cnt)))
    # ⚠️ gatherDraws には n_all を渡さず, packed[0..n_uk) を添字で舐めさせる.
    #    「未知が packed の先頭に連続している」ことがその前提なので, ここで確かめる
    if n_uk > n_all:
        raise RuntimeError("未知局面数が全局面数を超えている：%d / %d" % (n_uk, n_all))

    # 確定した局面を書き出すバッファ. 全深さで使い回す
    # 各局面は一生に一度しか確定しない (dtm が 255 から離れたら戻らない) ので,
    # 全深さを合わせても n_uk を超えない. ⚠️ 伸ばす必要が無いので伸ばさない
    found_buf = array("I", bytes(4)) * n_uk
    found_base = found_buf.buffer_info()[0]
    found_ptr = cast(found_base, POINTER(c_uint32))
    found_mv = memoryview(found_buf)
    cursor = 0
    # ⚠️ from_buffer はゼロコピー. from_buffer_copy にすると C の書き込みが
    #    dtm / cnt に出ず, ループの後の引き分けの書き出しが1件も拾えなくなる
    dtm_c = (c_ubyte * n_all).from_buffer(dtm)
    cnt_c = (c_ubyte * n_uk).from_buffer(cnt)
    pred_ptr = cast(pred.buffer_info()[0], POINTER(c_uint32))
    pred_off_ptr = cast(pred_off.buffer_info()[0], POINTER(c_uint32))
    step_out = array("I", bytes(4))
    step_out_ptr = cast(step_out.buffer_info()[0], POINTER(c_uint32))
    # ⚠️ ここから先で packed をリサイズしない (buildIndex と同じ制約).
    #    174段ループの翻訳と引き分けの抽出がこの生ポインタを引く
    packed_ptr = cast(packed.buffer_info()[0], POINTER(c_uint64))
    # 引き分けの件数を受け取る1要素. 数える周と詰める周で同じ箱を使う
    n_draw = array("I", bytes(4))
    n_draw_ptr = cast(n_draw.buffer_info()[0], POINTER(c_uint32))
    _profMark("R_dtm")

    # 深さ0 のフロンティアはトライ負けの範囲そのもの
    # (フロンティアの持ち方は (配列 or None, lo, hi) の並び. None なら範囲そのもの)
    frontier = ((None, catch_hi, n_all),)
    depth = 0
    for _ in range(LOOP_MAX):
        t1 = time.time()
        printLogSub("#" * 100)
        printLogMain("#" * 100)
        nd = depth + 1
        if nd >= 255:
            raise RuntimeError("手数が dtm に入らない：%d" % nd)
        start = cursor
        # 偶数深さは q が負け (前任は1手で勝てる), 奇数深さは q が勝ち (前任の出次数を減らす)
        for f_ptr, lo, hi in frontier:
            rc = retreatStep(
                pred_ptr, pred_off_ptr, dtm_c, cnt_c, n_all, n_uk,
                f_ptr, lo, hi, nd, depth % 2,
                cast(found_base + 4 * cursor, POINTER(c_uint32)), n_uk - cursor,
                step_out_ptr,
            )
            if rc != 0:
                raise RuntimeError("後退解析の1段を進められない：%d (手数 %d)" % (rc, nd))
            cursor += step_out[0]
        found = found_mv[start:cursor]
        # 連番をパック値に戻す (記録 #19). #18 までは [packed[i] for i in found] で,
        # 1要素につき PyLong を2個 (添字と盤面値) 起こして list に積んでいた.
        # ⚠️ 長さは found の数ちょうど. 詰める順も found の順 (j = 0..n-1) で #18 と同じ
        wl = array("Q", bytes(8)) * len(found)
        rc = gatherPacked(
            packed_ptr, n_all,
            cast(found_base + 4 * start, POINTER(c_uint32)), len(found),
            cast(wl.buffer_info()[0], POINTER(c_uint64)) if len(found) else None,
        )
        # -3 は found に n_all 以上の連番が入っていた場合. 黙って別の局面を
        # 書き出すより落とす (retreatStep の範囲検査と同じ理由)
        if rc != 0:
            raise RuntimeError("確定した局面をパック値に戻せない：%d (手数 %d)" % (rc, nd))
        writeWLFilesForDepth(wl, nd, nd % 2 == 1)
        # 1手勝ち盤面だけ例外 (前向き探索が書いたキャッチは含まない)
        if nd == 1:
            printLogMain("  1手勝ち盤面総数 (キャッチ除く)：%d" % len(found))
        elif nd % 2 == 1:
            printLogMain("%3d手勝ち盤面総数：%d" % (nd, len(found)))
        else:
            printLogMain("%3d手負け盤面総数：%d" % (nd, len(found)))
        printLogMain("所要時間：{0:02d}時間{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t1)))
        # 盤面が増えなかった
        if not found:
            printLogMain("完全解析終了")
            break
        if nd == 1:
            # 深さ1は前向き探索のキャッチと合わせて一つのフロンティアになる
            # ⚠️ 範囲 → found の順で呼ぶ. 逆にすると found の並びが変わる
            frontier = ((None, catch_lo, catch_hi), (found_ptr, start, cursor))
        else:
            frontier = ((found_ptr, start, cursor),)
        depth = nd

    # ⚠️ ループを抜ける経路は2つ (found が空での break と LOOP_MAX の尽き) だが,
    #    どちらもここに落ちる. R_loop はそのまま「引き分けの抽出を始める点」でもある
    _profMark("R_loop")

    # 最後まで未知だった盤面 (＝引き分け) を成果物として書き出す
    #
    # ⚠️ 抽出を writeUnknownChunks() の引数の中に書かない. #18 まではそこだったので,
    #    関数の中で始まるタイマーより前に終わっていて, 9,948 万回の走査が
    #    後退解析の残差に埋もれていた. 変数に出すことが R_loop→R_draw の窓を作る.
    #
    # 2周する. 1周目は数えるだけ (out に NULL), 2周目でちょうどの長さに詰める.
    # 伸びるバッファも再開も要らない. 2周しても 2.0 億バイトの直線走査
    rc = gatherDraws(packed_ptr, dtm_c, n_uk, None, 0, n_draw_ptr)
    if rc != 0:
        raise RuntimeError("引き分けを数えられない：%d" % rc)
    n_drawn = n_draw[0]
    draws = array("Q", bytes(8)) * n_drawn
    rc = gatherDraws(
        packed_ptr, dtm_c, n_uk,
        cast(draws.buffer_info()[0], POINTER(c_uint64)) if n_drawn else None,
        n_drawn, n_draw_ptr,
    )
    if rc != 0:
        raise RuntimeError("引き分けを詰められない：%d" % rc)
    # 2周の間に dtm は動かないので一致するはず. ずれたら詰めたぶんが足りていない
    if n_draw[0] != n_drawn:
        raise RuntimeError("引き分けの数が2周で食い違う：%d / %d" % (n_draw[0], n_drawn))
    _profMark("R_draw")
    writeUnknownChunks([draws])
    _profMark("R_uk")
    _retreatWriteSummary()

def main():
    t0 = time.time()
    searchAll()
    retreatAnalysis()
    printLogMain("完全解析にかかった時間：%2d時間%2d分%2d秒" % s2hms(time.time() - t0))

if __name__ == "__main__":
    main()
