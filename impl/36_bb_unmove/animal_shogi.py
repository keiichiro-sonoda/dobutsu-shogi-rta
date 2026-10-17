#!/usr/bin/python3

import datetime
import os
import resource
import time
from array import array
from collections import deque
from ctypes import (c_int32, c_long, c_size_t, c_uint32, c_uint64, c_void_p,
                    cast, CDLL, POINTER)
from ctypes import c_int, sizeof

# 次の盤面を受け取るための配列型
c_uint64_array48 = c_uint64 * 48

INITIAL_BOARD = 0x000a003c914b002

# 1ファイルに格納する盤面数の最大値
# 1000万は2Gメモリがあふれるらしい
# 記録 #22 で全探索の作業ファイル (未探索と未知) をやめた. ここから先で効いているのは
# 成果物のファイルの区切り (保存形式) と, P0 の詰め方 (U をこの数ちょうどで区切って
# 末尾の塊から. 後退解析の採番順を決めている) の2つ. 待ち行列の区切りは queuePush() を見る.
# 記録 #34 で P0 は無くなった (後退解析は連番を振らない). 効いているのは成果物の区切りと待ち行列の区切り
# 記録 #24 から展開の受け皿 (_exp_bufs) の大きさにも使う (待ち行列の塊がこれ以下なので).
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
# 記録 #34: queue と同じ区切りで持つ, 盤面ごとのランクの列 (array("I")). 後退解析の準備を書く番地
queue_rank = None

# 全探索で未知に振り分けた局面を, 展開した順に並べたもの (U). P0 が後退解析の packed に詰める.
# #21 までは F2 が unknown###.bin の末尾のファイルを読み直して継ぎ足し, P0 が読んで消していた.
# None は「全探索がまだ作っていない / P0 が詰め終えた」
# 記録 #34: 後退解析は詰めずに, 引き分けを拾うとき (U_draw) にこの順で読む
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
# 記録 #34: キャッチ局面の列は後退解析の入口で手放す (前任をたどらないので読まない).
#           トライ負けの列は後退解析の最初のフロンティアになる
catch_wins = array("Q")
try_loses = array("Q")

# 記録 #24: 展開の受け皿 (勝ち・負け・未知の3本) を使い回す (searchNext() の F1).
# 最初のラウンドで BOARD_NUM_MAX 件ずつ1回だけ確保し, 以後は上書きする.
# #23 までは毎ラウンド n 件ぶん3本を新しく確保して 0 で埋めていた (40 MB 級の確保は mmap で
# 毎回まっさらなページが来るので, 触るたびにページフォルトとカーネルのゼロ埋めが起きる).
# ① 0 で埋め直さなくてよい. expandRound() は counts の件数までしか書かず (win[n_win++] など),
#    こちらも counts の件数までしか読まない. 前のラウンドの残りは読まれない
# ② 中身は同じラウンドのうちに catch_wins / try_loses / uk_all へ写し終える. 受け皿を指したまま
#    次のラウンドへ持ち越すものは無い (memoryview は searchNext() の中でしか持たない)
# ③ 大きさは BOARD_NUM_MAX. 待ち行列の塊がそれ以下であること (queuePush()) に頼っているので,
#    超えたら止める検査を searchNext() に残してある
# 全探索が終わっても手放さない. 後退解析の間も 3 × BOARD_NUM_MAX × 8 バイト (120 MB) を持ち続ける
_exp_bufs = None

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

# 後続を作り, seen 表に登録し, 初見だったものだけ返す
# ⚠️ -1=キャッチ勝ち / -2=トライ負け / >=0=未知 (初見の後続数). 規約が違う
nextBoardSeenNormal = lib.nextBoardSeenNormal
nextBoardSeenNormal.restype = c_int32
nextBoardSeenNormal.argtypes = (c_uint64, c_uint32, c_uint64_array48, POINTER(c_uint32))

# 1ラウンドぶんの展開 (記録 #13). 局面ごとの FFI をラウンドあたり1回にまとめる
expandRound = lib.expandRound
expandRound.restype = c_int32
expandRound.argtypes = (
    POINTER(c_uint64), POINTER(c_uint32), c_uint32,
    POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64), POINTER(c_uint64),
)

# 記録 #34: 直前の expandRound が積んだ初見の後続のランク (expandNewPtr と同じ並び)
expandNewRankPtr = lib.expandNewRankPtr
expandNewRankPtr.restype = c_void_p
expandNewRankPtr.argtypes = ()

rankBoard = lib.rankBoard
rankBoard.restype = c_uint64
rankBoard.argtypes = (c_uint64,)

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

# 後退解析: 一手前を直接作る (記録 #34). C の見出しに作りがある
unmoveInit = lib.unmoveInit
unmoveInit.restype = c_int32
unmoveInit.argtypes = ()

unmoveStep = lib.unmoveStep
unmoveStep.restype = c_int32
unmoveStep.argtypes = (
    POINTER(c_uint64), c_size_t, c_int32, c_int32,   # frontier, その数, odd, nd
    POINTER(c_uint64), c_size_t,                     # found の書き始め, 空き容量
    POINTER(c_uint64),                               # out[3]
)

unmoveZeros = lib.unmoveZeros
unmoveZeros.restype = c_long
unmoveZeros.argtypes = (POINTER(c_uint64), c_size_t)

unmoveDraws = lib.unmoveDraws
unmoveDraws.restype = c_long
unmoveDraws.argtypes = (POINTER(c_uint64), c_size_t)

unmoveDrawsPtr = lib.unmoveDrawsPtr
unmoveDrawsPtr.restype = c_void_p
unmoveDrawsPtr.argtypes = ()

prepZeroCount = lib.prepZeroCount
prepZeroCount.restype = c_uint64
prepZeroCount.argtypes = ()

# 記録 #25: 後退解析の配列 (pred / pred_off / cnt / dtm) を C の hugeAlloc で確保して fill で埋める.
# 2 MiB ページを頼んだ領域になる (C の hugeFill の注記). 解放はしない
hugeFill = lib.hugeFill
hugeFill.restype = c_void_p
hugeFill.argtypes = (c_size_t, c_int)

def hugeArray(ctype, n: int, fill: int):
    """C の hugeFill で確保した n 要素の ctypes の配列 (巨大ページを頼んだ領域)。

    array / bytearray の代わりに使う. cast(arr, POINTER(...))・from_buffer・len・添字は
    そのまま通る. 解放はしない (後退解析が終わるまで使い, そのままプロセスが終わる)
    """
    ptr = hugeFill(sizeof(ctype) * n, fill)
    if not ptr:
        raise RuntimeError("巨大ページの配列を確保できない：%d 要素" % n)
    return (ctype * n).from_address(ptr)

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
# BOARD_NUM_MAX ずつの塊にする: 末尾の塊をまず BOARD_NUM_MAX まで埋め, 残りを
# BOARD_NUM_MAX ずつの新しい塊にする. #21 まで F5 が unexplored###.bin でやっていた
# 区切りと同じなので, 先頭の塊 (＝1ラウンドの入力) は min(BOARD_NUM_MAX, 行列の長さ) になる.
# 取り出した塊は F1 で手放すので, 消費した先頭を持ち続けない.
# 区切らない形 (門番の whole 腕. patches/whole.patch) は J ＝ forward_total ＋ P0 が
# 2.48 秒遅かった (F1 と F6 のカーネル時間. 機序は分けていない) ので, 区切りを残した
# ⚠️ 門番 gate_22_in_memory の2腕 (chunk / whole) はこの関数だけが違う
# 記録 #34: ランクの列 new_rank を, 盤面の列と同じ区切りで queue_rank に積む.
# 盤面の待ち行列の区切り方と並びは変えない
def queuePush(new, new_rank) -> None:
    step = BOARD_NUM_MAX
    start = 0
    if queue and len(queue[-1]) < step:
        start = step - len(queue[-1])
        queue[-1].extend(new[:start])
        queue_rank[-1].extend(new_rank[:start])
    for s in range(start, len(new), step):
        queue.append(new[s:s + step])
        queue_rank.append(new_rank[s:s + step])

# 全探索の入口 (記録 #22)
#
# #21 まではラウンドの頭で dat/ の未探索ファイルを探し, 無ければ初期局面を
# unexplored000.bin に書いていた. 1ラウンド目のあとで buildSeenBoards() が
# unknown000.bin (中身は初期局面1つ) を読んで表に入れるのが, 初期局面が
# 発見済み表に入る唯一の経路だった. どちらもファイルごと消えたので, ここで明示的にやる
def forwardInit() -> None:
    global queue, queue_rank, uk_all, catch_wins, try_loses, tbn_uk, tbn_win, tbn_lose
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
    queue_rank = deque([array("I", [rankBoard(INITIAL_BOARD)])])
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
    "U_init",      # 初期化の直後 (手数の配列と残りの数. 記録 #34)
    "U_loop",      # 手数ごとのループ (dat/ への書き出しを含む) を抜けた直後
    "U_draw",      # 引き分けを拾い終えた直後
    "U_uk",        # writeUnknownChunks() の直後
)
# 読む側が毎回引き算しなくて済むように, 隣り合う境界の差だけ名前を付けておく.
# 記録 #34 で段の顔ぶれが変わった. #33 までの段との対応は retreatAnalysis() の上の見出しにある
RETREAT_SPANS = (
    ("U_init", "R_start", "U_init"),
    ("U_loop", "U_init", "U_loop"),
    ("U_draw", "U_loop", "U_draw"),
    ("U_uk", "U_draw", "U_uk"),
    ("retreat_total", "R_start", "U_uk"),
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
        # 記録 #34: 初期化の直後の巨大ページ (#21〜#33 は索引を捨てる直前に読んでいた smaps_index).
        # 区間の行より後ろに置く (gate_stats.py の spans モードは最初の t_ 行で読むのをやめる)
        rss, huge, sec = _prof["smaps_init"]
        f.write("rss_init_kB\t%d\n" % rss)
        f.write("anonhuge_init_kB\t%d\n" % huge)
        f.write("smaps_init_sec\t%.6f\n" % sec)
        # 記録 #25 の計装: ループの配列 (#34 では準備の配列と手数の配列) がまだ生きているうちの
        # 巨大ページ. 読んだのは U_uk のあとで, どの区間にも入らない (費用は smaps_loop_sec)
        rss, huge, sec = _prof["smaps_loop"]
        f.write("rss_loop_kB\t%d\n" % rss)
        f.write("anonhuge_loop_kB\t%d\n" % huge)
        f.write("smaps_loop_sec\t%.6f\n" % sec)

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
    global tbn_uk, tbn_win, tbn_lose, catch_wins, try_loses, _exp_bufs
    _prof.clear()
    _profMark("start")

    # 待ち行列の先頭を取り出す. 取り出したものは F1 で C に渡したあと手放す
    _profMark("F0_begin")
    unexp_boards = queue.popleft()
    unexp_rank = queue_rank.popleft()
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
    # 記録 #24: 入力の写し (#23 までの arr) をやめ, 待ち行列の塊のバッファをそのまま渡す.
    # C は入力を読むだけで, 取り出した塊はもう待ち行列に入っていない
    # ⚠️ array("Q") が8バイトである保証は処理系依存 (#12 が array("I") でやったのと同じ)
    if unexp_boards.itemsize != 8:
        raise RuntimeError("array('Q') が8バイトでない：%d" % unexp_boards.itemsize)
    # 受け皿は最初のラウンドで1回だけ確保する (その回だけ 0 で埋める. 上の _exp_bufs の注記)
    if _exp_bufs is None:
        _exp_bufs = tuple(array("Q", bytes(8)) * BOARD_NUM_MAX for _ in range(3))
    # 勝ち・負け・未知は3本あわせてちょうど n 本. 待ち行列の塊は BOARD_NUM_MAX 件以下のはずで,
    # 超えたら書き始める前に止める (C は受け皿の大きさを知らない)
    if n > len(_exp_bufs[0]):
        raise RuntimeError("受け皿に入らない：%d / %d" % (n, len(_exp_bufs[0])))
    counts = array("Q", bytes(8)) * 5
    if unexp_rank.itemsize != 4 or len(unexp_rank) != n:
        raise RuntimeError("ランクの列が盤面の列と揃っていない：%d / %d" % (len(unexp_rank), n))
    rc = expandRound(
        cast(unexp_boards.buffer_info()[0], POINTER(c_uint64)),
        cast(unexp_rank.buffer_info()[0], POINTER(c_uint32)), n,
        cast(_exp_bufs[0].buffer_info()[0], POINTER(c_uint64)),
        cast(_exp_bufs[1].buffer_info()[0], POINTER(c_uint64)),
        cast(_exp_bufs[2].buffer_info()[0], POINTER(c_uint64)),
        cast(counts.buffer_info()[0], POINTER(c_uint64)),
    )
    # ⚠️ 握りつぶさない. -2 はバッファ, -3 は表を確保できなかった場合で,
    #    どちらもそのラウンドはやり直せない (そこまでの後続はもう表に入っている)
    if rc != 0:
        raise RuntimeError("後続を作れない：%d" % rc)
    del unexp_boards, unexp_rank
    # 写しを作らず, 受け皿の件数ぶんを memoryview で見る (このラウンドのうちに足し終える.
    # #23 までは件数ぶんのスライス, つまりもう1つの写しを作っていた)
    win_boards = memoryview(_exp_bufs[0])[:counts[0]]
    lose_boards = memoryview(_exp_bufs[1])[:counts[1]]
    uk_boards = memoryview(_exp_bufs[2])[:counts[2]]
    # 初見の後続を C のバッファから1回のコピーで受け取る
    # (要素ごとに読むと 2.5 億個の PyLong を作ることになる. 記録 #1 の罠)
    new_unexp_boards = array("Q")
    new_unexp_rank = array("I")
    _n_new = expandNewCount()
    if _n_new:
        new_unexp_boards.frombytes(
            memoryview((c_uint64 * _n_new).from_address(expandNewPtr())).cast("B")
        )
        new_unexp_rank.frombytes(
            memoryview((c_uint32 * _n_new).from_address(expandNewRankPtr())).cast("B")
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
    # 記録 #24: 受け皿の memoryview から足す
    # (array の frombytes は "Q" の memoryview を受け取らないので, "B" に読み替える)
    catch_wins.frombytes(win_boards.cast("B"))
    try_loses.frombytes(lose_boards.cast("B"))
    _prof["n_catch_total"] = len(catch_wins)
    _prof["n_try_total"] = len(try_loses)
    # 未知盤面を展開順のまま積み足す. #21 までの updateUKFile() は, 末尾の unknown###.bin を
    # 読み直して継ぎ足し, BOARD_NUM_MAX を超えたら2つに割って書き戻していた
    _profMark("F2_begin")
    uk_all.frombytes(uk_boards.cast("B"))
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

    queuePush(new_unexp_boards, new_unexp_rank)
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
    # 記録 #34: キャッチ局面の列は後退解析の入口 (R_start の直後) で手放す
    # 境界は残す (forward_summary.tsv の release_wl の行を過去の記録と揃えるため)
    _profMark("release_wl")

# 全盤面が出るまで探索
def searchAll():
    global _prof_round, _exp_bufs
    t0 = time.time()
    _t_all = _pc()
    # 記録 #21: ユーザー時間とカーネル時間の起点. ⚠️ _prof には置かない
    # (searchNext が毎ラウンド _prof.clear() するので消える)
    _ru_start = resource.getrusage(resource.RUSAGE_SELF)
    # 記録 #25 の計装: minor fault の起点 ("min") も同じ辞書に持つ
    _cpu_start = {"ut": _ru_start.ru_utime, "st": _ru_start.ru_stime, "min": _ru_start.ru_minflt}
    # 段ごとのユーザー時間とカーネル時間をラウンドをまたいで足す (時間の区間と同じ組)
    # 記録 #25 の計装: minor fault ("min") も同じ組で足す
    _cpu = {(kind, k): 0.0 for kind in ("ut", "st", "min") for k in ("F0", "F1", "F2", "F3", "F4", "F5")}
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
        for kind in ("ut", "st", "min"):
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
    # 記録 #25: 展開の受け皿 (記録 #24) もここで手放す. 全探索が終わると使わない
    # (#24 は後退解析の間も 120 MB を持ち続け, 全体のピーク RSS (P2) が 0.12 GiB 上がった)
    _exp_bufs = None
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
        # 記録 #25 の計装: 段ごとの minor fault (回数). ラウンドをまたいで足した合計.
        # F1 に残るカーネル時間 (新しいページを用意する仕事) を段ごとに見るため
        for k in ("F0", "F1", "F2", "F3", "F4", "F5"):
            f.write("minflt_%s\t%d\n" % (k, _cpu[("min", k)]))
        f.write("minflt_F6\t%d\n" % (_prof["min_F6"] - _prof["min_F6_begin"]))
        f.write("minflt_release\t%d\n" % (_prof["min_release_seen"] - _prof["min_F6"]))
        f.write("minflt_forward_total\t%d\n" % (_prof["min_release_seen"] - _cpu_start["min"]))

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

# ---- 後退解析: 一手前を直接作る (記録 #34) ------------------------------------------
#
# #33 までは, 全探索の結果に連番を振り (P0), 番号を引く索引を作り (P1, 8.59 GB), 未知局面の後続を
# 全部作り (P2), 向きを逆にして前任の表に並べ替え (P4), 174段ループでその表を引いていた.
# #34 からは, 全探索が展開した局面ごとに種類とキャッチ抜きの数をランクを添字にした配列に書いておき
# (nextBoardSeenNormal), 後退解析では決まった局面から手を1つ戻して前任をその場で作る (C の unmoveStep).
# 連番も索引も前任の表も作らないので, P0〜P4 が無くなる. 実験 unmove_bench〜forward_prep で確かめた形.
#
# 段 (retreat_summary.tsv の区間) と #33 までの段の対応:
#   U_init  初期化. 配列から手数の配列を作り, 配列をその場で残りの数に読み替える   ← P0・P1・R_dtm (と P2・P4 の確保)
#   U_loop  手数ごとのループ. 前任を作って手数を決め, 手数ごとに dat/ に書く       ← P2・P4・174段ループ
#   U_draw  引き分けを拾う (未知局面の列を順に見て, 手数が未定のものを集める)     ← R_draw
#   U_uk    引き分けを書く                                                       ← R_uk
#
# キャッチ局面は手数 1 の勝ちで, そこからは前任をたどらない. キャッチ抜きの数が 0 の未知局面は
# 手数 2 の負けで, 初期化で決め, 手数 2 の段のフロンティアに足す (experiments/unmove_catch).
# ⚠️ 保存の中の並び (後退解析が局面を決めた順) は #33 と変わる. 成果物はバイト比較ではなく,
#    ファイルの名前と件数・オラクル・指紋で見る (CLAUDE.md「保存形式を変えると採番順は必ず動く」)
def retreatAnalysis():
    """
    全探索終了後に実行
    よくわからないけど後退解析と呼ぶらしい
    """
    global catch_wins
    for fnamer in (WIN_PATH_FORMAT.format(3, 0), LOSE_PATH_FORMAT.format(2, 0)):
        if os.path.exists(fnamer):
            raise RuntimeError("途中まで進んだ dat/ からは再開できない：%s" % fnamer)

    _profMark("R_start")
    n_uk = len(uk_all)
    # キャッチ局面の列は F6 が書いたあとはもう読まない (#33 までは P0 が詰めてから手放していた)
    catch_wins = None
    rc = unmoveInit()
    if rc != 0:
        raise RuntimeError("後退解析の配列を作れない：%d" % rc)
    # 決まった局面 (キャッチ局面とトライ負け局面を除く) を手数の順に並べる列. 未知局面の数を超えない
    if uk_all.itemsize != 8 or try_loses.itemsize != 8:
        raise RuntimeError("array('Q') が8バイトでない")
    found_buf = array("Q", bytes(8)) * n_uk
    found_base = found_buf.buffer_info()[0]
    step_out = (c_uint64 * 3)()
    n_zero = prepZeroCount()
    _profMark("U_init")
    _prof["smaps_init"] = _smapsHuge()

    # 手数 nd の段は, 手数 nd − 1 で決まった局面 (フロンティア) から前任を作る. 最初のフロンティアはトライ負け
    front_ptr = cast(try_loses.buffer_info()[0], POINTER(c_uint64)) if len(try_loses) else None
    front_n = len(try_loses)
    cursor = 0
    depth = 0
    n_cand = n_kept = 0
    for _ in range(LOOP_MAX):
        t1 = time.time()
        printLogSub("#" * 100)
        printLogMain("#" * 100)
        nd = depth + 1
        if nd >= 254:
            raise RuntimeError("手数が dtm に入らない：%d" % nd)
        start = cursor
        rc = unmoveStep(
            front_ptr, front_n, depth % 2, nd,
            cast(found_base + 8 * cursor, POINTER(c_uint64)), n_uk - cursor, step_out,
        )
        if rc != 0:
            raise RuntimeError("後退解析の1段を進められない：%d (手数 %d)" % (rc, nd))
        cursor += step_out[0]
        n_cand += step_out[1]
        n_kept += step_out[2]
        # キャッチ抜きの数が 0 の未知局面 (初期化で手数 2 の負けに決めた) を, 手数 2 で決まった局面に足す
        if nd == 2:
            got = unmoveZeros(cast(found_base + 8 * cursor, POINTER(c_uint64)), n_uk - cursor)
            if got != n_zero:
                raise RuntimeError("手数 2 の負けを足せない：%d / %d" % (got, n_zero))
            cursor += got
        wl = found_buf[start:cursor]
        writeWLFilesForDepth(wl, nd, nd % 2 == 1)
        # 1手勝ち盤面だけ例外 (前向き探索が書いたキャッチは含まない)
        if nd == 1:
            printLogMain("  1手勝ち盤面総数 (キャッチ除く)：%d" % len(wl))
        elif nd % 2 == 1:
            printLogMain("%3d手勝ち盤面総数：%d" % (nd, len(wl)))
        else:
            printLogMain("%3d手負け盤面総数：%d" % (nd, len(wl)))
        printLogMain("所要時間：{0:02d}時間{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t1)))
        # 盤面が増えなかった
        if not wl:
            printLogMain("完全解析終了")
            break
        del wl
        front_ptr = cast(found_base + 8 * start, POINTER(c_uint64))
        front_n = cursor - start
        depth = nd
    printLogMain("前任の候補：%d (手数が未定で残ったもの %d)" % (n_cand, n_kept))
    _profMark("U_loop")

    # 最後まで未知だった盤面 (＝引き分け) を成果物として書き出す. 未知局面の列の順に拾う
    n_drawn = unmoveDraws(cast(uk_all.buffer_info()[0], POINTER(c_uint64)) if n_uk else None, n_uk)
    if n_drawn < 0:
        raise RuntimeError("引き分けを拾えない：%d" % n_drawn)
    draws = array("Q")
    if n_drawn:
        draws.frombytes(memoryview((c_uint64 * n_drawn).from_address(unmoveDrawsPtr())).cast("B"))
    _profMark("U_draw")
    writeUnknownChunks([draws])
    _profMark("U_uk")
    # 後退解析の配列 (準備の配列と手数の配列) が生きているうちに巨大ページを読む. どの区間にも入らない
    _prof["smaps_loop"] = _smapsHuge()
    _retreatWriteSummary()

def main():
    t0 = time.time()
    searchAll()
    retreatAnalysis()
    printLogMain("完全解析にかかった時間：%2d時間%2d分%2d秒" % s2hms(time.time() - t0))

if __name__ == "__main__":
    main()
