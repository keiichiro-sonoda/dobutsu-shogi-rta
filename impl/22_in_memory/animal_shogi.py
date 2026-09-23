#!/usr/bin/python3

import datetime
import os
import resource
import time
from array import array
from collections import deque
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
# 記録 #22 で全探索の作業ファイル (未探索と未知) をやめた. ここから先で効いているのは
# 成果物のファイルの区切り (保存形式) と, P0 の詰め方 (U をこの数ちょうどで区切って
# 末尾の塊から. 後退解析の採番順を決めている) の2つ. 待ち行列の区切りは queuePush() を見る.
# ⚠️ 値を変えると採番順も成果物の区切りも動く
BOARD_NUM_MAX = 5000000

# ディレクトリのパス
DIR_PATH = "./dat/"

# 負け盤面のパス
LOSE_PATH_FORMAT = DIR_PATH + "lose{:03d}te_{:03d}.bin"

# 勝ち盤面のパス
WIN_PATH_FORMAT = DIR_PATH + "win{:03d}te_{:03d}.bin"

# 未知盤面のパス
UK_PATH_FORMAT = DIR_PATH + "unknown{:03d}.bin"

# バックアップフラグ (真ならファイル上書きの度にバックアップ)

# 適当なループ数 (break前提)
LOOP_MAX = 10000

# 全探索の待ち行列 (記録 #22). #21 までは unexplored###.bin で, F5 が末尾のファイルを
# 読み直して継ぎ足し, 次のラウンドの F0 が先頭のファイルを読んで消していた.
# 先に入れたものから取り出すので, 何件ずつ取り出しても展開の順は変わらない
# (区切り方は queuePush() が決める. forwardInit() が初期局面1つで始める)
queue = None

# 全探索で未知に振り分けた局面を, 展開した順に並べたもの (U). P0 が後退解析の packed に詰める.
# #21 までは F2 が unknown###.bin の末尾のファイルを読み直して継ぎ足し, P0 が読んで消していた.
# None は「全探索がまだ作っていない / P0 が詰め終えた」
uk_all = None

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
#
# 記録 #22: F6 で書いたあとも手放さず, P0 がファイルから読み戻さずにこのまま詰める
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

# 初見の後続を待ち行列の末尾に積む (記録 #22. F5)
#
# 区切らない: 積んだ array を写さずに1本のまま足す. 前のラウンドが行列の全部を
# 取り出しているので行列の中身は常に1本で, 「前のラウンドの初見の後続」がそのまま
# 次のラウンドの入力になる (1ラウンドが幅優先の1層になる).
# 500万件ずつ区切っていたのは 2021 年のメモリ 2 GB に合わせたもの.
# ⚠️ 門番 gate_22_in_memory の2腕 (chunk / whole) はこの関数だけが違う
def queuePush(new) -> None:
    if new:
        queue.append(new)

# 全探索の入口 (記録 #22)
#
# #21 まではラウンドの頭で dat/ の未探索ファイルを探し, 無ければ初期局面を
# unexplored000.bin に書いていた. 1ラウンド目のあとで buildSeenBoards() が
# unknown000.bin (中身は初期局面1つ) を読んで表に入れるのが, 初期局面が
# 発見済み表に入る唯一の経路だった. どちらもファイルごと消えたので, ここで明示的にやる
def forwardInit() -> None:
    global queue, uk_all, catch_wins, try_loses, tbn_uk, tbn_win, tbn_lose
    if not os.path.isdir(DIR_PATH):
        raise RuntimeError("ディレクトリ「%s」を作成してください" % DIR_PATH)
    # 途中の dat/ から再開しない (CLAUDE.md「途中で落ちたら再走」). 読み戻す経路も持たない
    left = sorted(os.listdir(DIR_PATH))
    if left:
        raise RuntimeError("%s が空でない (空の状態から走らせる)：%s" % (DIR_PATH, left[:3]))
    # 発見済み表を空から始める (前の走行の残りを持ち込まない)
    if seenInit() != 0:
        raise RuntimeError("発見済み表を確保できない")
    # ⚠️ 初期局面を表に入れる. expandRound() は入力の局面を表に入れないので, 入れ忘れると
    #    4手で戻ってきた初期局面 (両者のライオンが出て戻る) を「初見」としてもう一度積み,
    #    件数がずれる. 1ラウンド目の後続 (4局面) に初期局面は含まれないので,
    #    #21 より早く入れても答えは変わらない
    if seenInsert(INITIAL_BOARD) != 1:
        raise RuntimeError("初期局面を発見済み表に入れられない")
    queue = deque([array("Q", [INITIAL_BOARD])])
    uk_all = array("Q")
    catch_wins = array("Q")
    try_loses = array("Q")
    tbn_uk = tbn_win = tbn_lose = 0

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
# ⚠️ 記録 #22 で F0・F2・F5 はファイルを読み書きしなくなり (待ち行列の出し入れと未知の積み足し),
#    S は常に 0 になった (表を組み直す物が無い). どれも列は過去の記録と揃えるために残す.
#    解放の区分 release_wl も, 終端のリストを P0 まで持つようになって中身が無い
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

def _smapsHuge() -> tuple:
    """(Rss の kB, AnonHugePages の kB, 読むのにかかった秒) を返す (記録 #21).

    巨大ページは頼んでも付くとは限らないので, 表を捨てる直前に付いたことを読んで残す.
    ⚠️ smaps_rollup はページ表を歩くので, 4 KiB ページのほうが読むのに時間がかかる.
       判定に使う段の外 (release_seen と P2_free) で呼び, 費用も一緒に残す
    """
    t = _pc()
    rss = huge = -1
    with open("/proc/self/smaps_rollup") as f:
        for line in f:
            if line.startswith("Rss:"):
                rss = int(line.split()[1])
            elif line.startswith("AnonHugePages:"):
                huge = int(line.split()[1])
    return rss, huge, _pc() - t

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
    # 記録 #21: 同じ戻り値のユーザー時間とカーネル時間 (秒, float). 巨大ページの効き目が
    # 表を作る段の fault (カーネル) から出るのか, 表を引く段の番地の翻訳 (ユーザー) から
    # 出るのかを分けるため.
    # ⚠️ 合計は正確だが, ユーザーとカーネルへの配分はタイマー割り込みの標本から比で割り振られる
    #    (この計測機は CONFIG_HZ=1000 で nohz_full なし). 短い区間の1回分は読めない.
    #    段ごとの合計で読む
    _prof["ut_" + name] = _ru.ru_utime
    _prof["st_" + name] = _ru.ru_stime

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
            # 記録 #21: 累積のユーザー時間とカーネル時間 (絶対値. 差は読む側で引く)
            f.write("utime_%s\t%.6f\n" % (m, _prof["ut_" + m]))
            f.write("stime_%s\t%.6f\n" % (m, _prof["st_" + m]))
        # 記録 #21: 索引を捨てる直前の巨大ページ. 区間の行より後ろに置く
        # (gate_stats.py の spans モードは最初の t_ 行で読むのをやめる)
        rss, huge, sec = _prof["smaps_index"]
        f.write("rss_index_kB\t%d\n" % rss)
        f.write("anonhuge_index_kB\t%d\n" % huge)
        f.write("smaps_index_sec\t%.6f\n" % sec)

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
#
# 記録 #22: ファイルを1つも読み書きしない. 待ち行列の先頭を取り出して展開し,
# 未知は uk_all に, 初見の後続は待ち行列に積む. 途中の dat/ から再開する経路
# (未探索ファイルを探す部分と「探索済み」で抜ける部分) は消した. 再開は
# CLAUDE.md で禁じていて (途中で落ちたら再走), 入口の forwardInit() が空でない dat/ を止める
def searchNext():
    global tbn_uk, tbn_win, tbn_lose, catch_wins, try_loses
    _prof.clear()
    _profMark("start")

    # 待ち行列の先頭を取り出す. 取り出したものは F1 で arr に写したあと手放す
    _profMark("F0_begin")
    unexp_boards = queue.popleft()
    _profMark("F0")
    _prof["n_in"] = n = len(unexp_boards)
    printLogSub("探索盤面数：{:d}".format(len(unexp_boards)))

    # 次の状態を計算し, 末端であれば勝ちか負けに振り分ける
    #
    # ⚠️ 展開の順は「待ち行列に積まれた順」. #12 までは
    #    「while unexp_boards: board = unexp_boards.pop()」で, CPython の set.pop()
    #    が表を前から走査するので集合の反復順だった. #16 で読み側が frombytes に,
    #    #17 で書き側の set(...) が外れて「前のラウンドが書いた順そのまま」になり,
    #    #22 でファイルを通さなくなった (順は変わらない)
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
    catch_wins += win_boards
    try_loses += lose_boards
    _prof["n_catch_total"] = len(catch_wins)
    _prof["n_try_total"] = len(try_loses)
    # 未知盤面を展開順のまま積み足す. #21 までの updateUKFile() は, 末尾の unknown###.bin を
    # 読み直して継ぎ足し, BOARD_NUM_MAX を超えたら2つに割って書き戻していた
    _profMark("F2_begin")
    uk_all.extend(uk_boards)
    _profMark("F2")

    printLogSub("新状態数 (重複排除前)：{:d}".format(_prof["n_new_pre"]))

    # 集合化 (F3) は要らない. C 側が登録の時点でラウンド内の重複も落としている
    _profMark("F3_begin")
    _profMark("F3")
    # ⚠️ 集合化後の一意数は測る場所が無くなった (#10 の n_new_uniq). 0 を入れる
    _prof["n_new_uniq"] = 0

    # #21 までは, 1ラウンド目だけここで buildSeenBoards() がディスクから発見済み表を
    # 組み直し (S), 総数もそこから数えていた. 初期局面は forwardInit() が表に入れるので
    # 組み直す物が無い. 列は残して 0
    _prof["S"] = 0.0
    # このラウンドで振り分けた分はそれまでの分と互いに素なので, 足すだけでよい
    # (1ラウンド目もここで数える. #21 が buildSeenBoards() で数えていた値と同じになる)
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

    # ⚠️ ここから先が F5. #10 までは集合をリストに戻していたが, もうリストのまま.
    #    #21 までは末尾の unexplored###.bin を読み直して継ぎ足し, 書き戻していた
    _profMark("F5_begin")
    printLogSub("新状態数 (重複排除後)：{:d}".format(len(new_unexp_boards)))
    printLogSub("総未知盤面数：{:d}, 総勝ち盤面数：{:d}, 総負け盤面数：{:d}".format(
        tbn_uk, tbn_win, tbn_lose
    ))

    # 全探索終了
    # ⚠️ 初見が 0 件でも, 待ち行列に残りがあれば終わらない. #21 は初見が 0 件のラウンドで
    #    終えていたが, 本番では最後のラウンドの入力が行列の全部だったので同じになる
    if not new_unexp_boards and not queue:
        printLogSub("探索終了")
        # メインに書き込み
        printLogMain("総未知盤面数：{:d}, 総勝ち盤面数：{:d}, 総負け盤面数：{:d}".format(
            tbn_uk, tbn_win, tbn_lose
        ))
        # 積む物が無い. 境界だけ記録する (F5 = 0)
        _profMark("F5_begin")
        _profMark("F5")
        return True

    queuePush(new_unexp_boards)
    _profMark("F5")

    return False

# 貯めた終端局面を書き出す (全探索の最後に1回)
# writeWLFilesForDepth() は既存ファイルを一切読まないので, 読み直しはゼロになる
# ⚠️ 書くのは成果物で, 位置も中身も変えない. 後退解析が 1手勝ちの続き (副番号の続き) を
#    書くので, 先に書いておく必要がある
def flushTerminalBoards():
    _profMark("F6_begin")
    writeWLFilesForDepth(catch_wins, 1, True)
    writeWLFilesForDepth(try_loses, 0, False)
    _profMark("F6")
    # 記録 #22: ここではもう手放さない (147,317,599 件ぶん). P0 がファイルから読み戻さずに
    # このまま詰め, 詰め終えたら手放す (P1 の索引より前. ピークは P2 にある).
    # 境界は残す (forward_summary.tsv の release_wl の行を過去の記録と揃えるため)
    _profMark("release_wl")

# 全盤面が出るまで探索
def searchAll():
    global _prof_round
    t0 = time.time()
    _t_all = _pc()
    # 記録 #21: ユーザー時間とカーネル時間の起点. ⚠️ _prof には置かない
    # (searchNext が毎ラウンド _prof.clear() するので消える)
    _ru_start = resource.getrusage(resource.RUSAGE_SELF)
    _cpu_start = {"ut": _ru_start.ru_utime, "st": _ru_start.ru_stime}
    # 段ごとのユーザー時間とカーネル時間をラウンドをまたいで足す (時間の区間と同じ組)
    _cpu = {(kind, k): 0.0 for kind in ("ut", "st") for k in ("F0", "F1", "F2", "F3", "F4", "F5")}
    # 空の dat/ を確かめ, 発見済み表と待ち行列を初期局面1つから始める (記録 #22)
    forwardInit()
    _profWriteHeader()
    _sum = {k: 0.0 for k in PROFILE_TIMES + ("round_total", "residual")}
    for _ in range(LOOP_MAX):
        _t_round = _pc()
        flag = searchNext()
        _round_total = _pc() - _t_round
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
        for kind in ("ut", "st"):
            for k in ("F0", "F1", "F2", "F3", "F4", "F5"):
                _cpu[(kind, k)] += _prof[kind + "_" + k] - _prof[kind + "_" + k + "_begin"]
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
    # 記録 #21: 発見済み表を捨てる直前に, 巨大ページが付いたことを読む (解放の区間に入る)
    _smaps_seen = _smapsHuge()
    # 発見済み表を解放する
    # 後退解析が索引 (8.59 GB) を作る前に手放す (解放時間は全探索側に計上)
    seenFree()
    # 展開バッファ (記録 #13) も同じところで手放す
    expandFreeBuffer()
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
        # 記録 #21: 段ごとのユーザー時間とカーネル時間 (秒). ラウンドをまたいで足した合計.
        # ⚠️ 配分はタイマー割り込みの標本なので, 段ごとの合計で読む (1ラウンドぶんは読めない)
        for kind, name in (("ut", "utime"), ("st", "stime")):
            for k in ("F0", "F1", "F2", "F3", "F4", "F5"):
                f.write("%s_%s\t%.6f\n" % (name, k, _cpu[(kind, k)]))
            f.write("%s_F6\t%.6f\n" % (name, _prof[kind + "_F6"] - _prof[kind + "_F6_begin"]))
            f.write("%s_release\t%.6f\n" % (name, _prof[kind + "_release_seen"] - _prof[kind + "_F6"]))
            f.write("%s_forward_total\t%.6f\n" % (name, _prof[kind + "_release_seen"] - _cpu_start[kind]))
        # 記録 #21: 発見済み表を捨てる直前の巨大ページ
        f.write("rss_seen_kB\t%d\n" % _smaps_seen[0])
        f.write("anonhuge_seen_kB\t%d\n" % _smaps_seen[1])
        f.write("smaps_seen_sec\t%.6f\n" % _smaps_seen[2])

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

# 前向き探索の結果を, 連番を振った packed[] にする (P0)
#
# 記録 #22: ファイルから読み戻さない. 全探索がメモリに残した3本
# (uk_all / catch_wins / try_loses) から詰める.
# ⚠️ 並びは #21 までと同じにする. これが後退解析の採番順で, 変えると P2・P4・174段ループの
#    効き目が動く (CLAUDE.md「採番順は効果量に大きく効く」). #21 までは unknown###.bin を
#    番号順に読んで, 末尾のファイルから uk_chunks.pop() で詰めていた. そのファイルは
#    U (未知を展開順に並べたもの) を先頭から BOARD_NUM_MAX ちょうどで区切ったものだった
#    (1ラウンドの未知は BOARD_NUM_MAX 以下なので, updateUKFile() の3個以上の分割は
#    一度も起きていない). だから U を BOARD_NUM_MAX ちょうどで区切り, 末尾の塊から詰める.
#    ラウンドの区切りには頼らない (待ち行列を区切らないと, 1ラウンドの未知が
#    BOARD_NUM_MAX を超える). 続けて 1手勝ち, 0手負け (どちらも展開順. F6 が書いた
#    ファイルを番号順に読んだ並びと同じ)
def loadForwardResult() -> tuple:
    global uk_all, catch_wins, try_loses
    if uk_all is None:
        raise RuntimeError("全探索の結果がメモリに無い (後退解析はファイルを読まない. searchAll() の後に呼ぶ)")
    t1 = time.time()
    packed = array("Q")
    n_uk = len(uk_all)
    step = BOARD_NUM_MAX
    size = uk_all.itemsize
    # バイト列として区切って写す. frombytes は memcpy で, 要素ごとの PyLong を作らない
    # (array の frombytes は "Q" の memoryview を受け取らないので, "B" に読み替える)
    mv = memoryview(uk_all).cast("B")
    for start in reversed(range(0, n_uk, step)):
        packed.frombytes(mv[start * size:(start + step) * size])
    mv.release()
    n_win = len(catch_wins)
    packed.extend(catch_wins)
    n_lose = len(try_loses)
    packed.extend(try_loses)
    # 詰め終えた3本を手放す. P1 の索引 (8 GiB) より前 (ピークは P2 にある)
    uk_all = None
    catch_wins = array("Q")
    try_loses = array("Q")
    printLogMain("詰めた局面：%d (未知 %d / キャッチ %d / トライ負け %d)" % (
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
    # 記録 #21: 索引を捨てる直前に, 巨大ページが付いたことを読む (P2→P2_free の区間に入る)
    _prof["smaps_index"] = _smapsHuge()
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
