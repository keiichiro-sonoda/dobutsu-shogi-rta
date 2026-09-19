#!/usr/bin/python3

import datetime
import pickle
import os
import time
import re
import shutil
import itertools
from array import array
from ctypes import c_int32, c_uint32, c_uint64, cast, CDLL, POINTER

# 次の盤面を受け取るための配列型
c_uint64_array48 = c_uint64 * 48

# 後続の連番を受け取るための配列型
# 48 は MAX_ACTION_NUM. 末尾の2つは索引外の後続があったときだけ使う
# (out[48] = 索引を引けた数, out[49] = 出次数)
c_uint32_array50 = c_uint32 * 50

INITIAL_BOARD = 0x000a003c914b002

# 1ファイルに格納する盤面数の最大値
# 1000万は2Gメモリがあふれるらしい
BOARD_NUM_MAX = 5000000

# ディレクトリのパス
DIR_PATH = "./dat/"

# 負け盤面のパス
LOSE_PATH_FORMAT = DIR_PATH + "lose{:03d}te_{:03d}.pickle"

# 勝ち盤面のパス
WIN_PATH_FORMAT = DIR_PATH + "win{:03d}te_{:03d}.pickle"

# 未知盤面のパス
UK_PATH_FORMAT = DIR_PATH + "unknown{:03d}.pickle"

# 未探索盤面のパス
UNEXP_PATH_FORMAT = DIR_PATH + "unexplored{:03d}.pickle"

# バックアップフラグ (真ならファイル上書きの度にバックアップ)
BACK_UP = False

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
catch_wins = []
try_loses = []

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

# ラッパー関数
def nextBoardInvNormalWrap(b) -> tuple:
    nba = c_uint64_array48()
    nbn = nextBoardInvNormal(b, nba)
    nbl = []
    if nbn > 0:
        nbl = nba[:nbn]
    return nbn, nbl

# バックアップして書き込み (グローバル変数依存)
# .pickle のみ対応
def writeAndBackup(fnamew, obj):
    # バックアップ
    if BACK_UP and os.path.exists(fnamew):
        m = re.match(r"(.*)(\.pickle)", fnamew)
        fnamew_bu = m.groups()[0] + "_backup.pickle"
        shutil.copyfile(fnamew, fnamew_bu)
    
    # 書き込み
    with open(fnamew, "wb") as f:
        pickle.dump(obj, f)

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
def writeWLFilesForDepth(wlbl: list, wl_depth: int, win: bool) -> None:
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
            writeAndBackup(wl_path_format.format(wl_depth, 0), set())
        return

    # 添字で区切って集合にする. 残りのリストを作り直さない
    # (作り直すと, 呼び出し元が持つ元のリストと残り2枚が同居して RSS のピークを作る.
    #  全探索の終端 1.4 億件で +1.98 GiB, 実行全体のピークがここだった)
    for start in range(0, len(wlbl), BOARD_NUM_MAX):
        writeAndBackup(wl_path_format.format(wl_depth, wl_sub), set(wlbl[start:start + BOARD_NUM_MAX]))
        wl_sub += 1

# 未知盤面 (探索済み) ファイルの更新
def updateUKFile(ukl: list):
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
        writeAndBackup(fnamer_uk, [])
    
    # 最新の副番号のファイルに書き込む
    fnamew_uk = UK_PATH_FORMAT.format(uk_sub)
    # ひとつ前の未知盤面
    with open(fnamew_uk, "rb") as f:
        known_uk = list(pickle.load(f))
    # 新しい未知盤面の集合と結合
    ukl = known_uk + ukl

    # ファイルの上限を上回ったら, 分割
    # 3個以上の分割は考慮しない
    if len(ukl) > BOARD_NUM_MAX:
        # 上限まで元ファイルに書き出し
        writeAndBackup(fnamew_uk, set(ukl[:BOARD_NUM_MAX]))
        # 残りは新ファイルへ. 残りのリストを作り直さず, 添字で区切って集合にする
        uk_sub += 1
        fnamew_uk = UK_PATH_FORMAT.format(uk_sub)
        writeAndBackup(fnamew_uk, set(ukl[BOARD_NUM_MAX:]))
    else:
        # 元のファイルに書き戻し
        writeAndBackup(fnamew_uk, set(ukl))

# 発見済み盤面の集合をディスクから組み立てる (searchNext の初回だけ)
# 未知・1手勝ち・0手負け・未探索 の4つで, これまでに見つけた盤面の全体になる
# unexplored{offset} を読まないのは, 中身がすでに未知/勝ち/負けへ移っているため
# 毎回やらずにこれだけディスクを見るのは, 再開可能性を壊さないため
# (計測中に電源が落ちても, 次の起動でディスクの状態から作り直せる)
def buildSeenBoards(offset: int) -> tuple:
    t1 = time.time()
    seen = set()
    n_uk = 0
    n_win = 0
    n_lose = 0
    # 未知盤面
    for i in range(LOOP_MAX):
        fnamer_uk = UK_PATH_FORMAT.format(i)
        if os.path.exists(fnamer_uk):
            with open(fnamer_uk, "rb") as f:
                past_boards = pickle.load(f)
            seen |= past_boards
            n_uk += len(past_boards)
        else:
            break

    # 勝ち盤面
    for i in range(LOOP_MAX):
        fnamer_win = WIN_PATH_FORMAT.format(1, i)
        if os.path.exists(fnamer_win):
            with open(fnamer_win, "rb") as f:
                past_boards = pickle.load(f)
            seen |= past_boards
            n_win += len(past_boards)
        else:
            break

    # 負け盤面
    for i in range(LOOP_MAX):
        fnamer_lose = LOSE_PATH_FORMAT.format(0, i)
        if os.path.exists(fnamer_lose):
            with open(fnamer_lose, "rb") as f:
                past_boards = pickle.load(f)
            seen |= past_boards
            n_lose += len(past_boards)
        else:
            break

    # 他の未探索盤面
    for i in range(offset + 1, LOOP_MAX):
        fnamer_unexp_another = UNEXP_PATH_FORMAT.format(i)
        if os.path.exists(fnamer_unexp_another):
            with open(fnamer_unexp_another, "rb") as f:
                seen |= pickle.load(f)
        else:
            break

    printLogMain("ディスクから読んだ発見済み盤面：%d" % len(seen))
    printLogMain("再構築時間：{0:02d}時間{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t1)))
    return seen, n_uk, n_win, n_lose

# まずは全盤面を洗い出したい
# 葉ノード (一手で勝てる盤面) は別ファイルに書き出す
# 初期盤面からの手数は考慮せず, 勝ち, 負け, 未知の3種に分けて保存
def searchNext():
    global seen_boards, tbn_uk, tbn_win, tbn_lose, catch_wins, try_loses
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
        # 初期盤面だけの集合をファイルに書き込む
        offset = 0
        fnamer_unexp = UNEXP_PATH_FORMAT.format(0)
        writeAndBackup(fnamer_unexp, set([INITIAL_BOARD]))
    else:
        fnamer_unexp = UNEXP_PATH_FORMAT.format(offset)

    printLogSub(fnamer_unexp + " を探索")
    # 集合をロード
    with open(fnamer_unexp, "rb") as f:
        unexp_boards = pickle.load(f)
    printLogSub("探索盤面数：{:d}".format(len(unexp_boards)))

    win_boards = []
    lose_boards = []
    uk_boards = []
    new_unexp_boards = []

    # 次の状態を計算
    # 末端であれば勝ちか負けのリストに追加
    while unexp_boards:
        board = unexp_boards.pop()
        nbn, nbl = nextBoardInvNormalWrap(board)
        # 勝ち盤面
        if nbn == 0:
            win_boards.append(board)
        # 負け盤面
        elif nbn == -1:
            lose_boards.append(board)
        # 未知盤面
        # 次の盤面は未探索盤面に追加
        else:
            uk_boards.append(board)
            new_unexp_boards += nbl
    
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
    # 未知盤面の更新
    updateUKFile(uk_boards)

    printLogSub("新状態数 (重複排除前)：{:d}".format(len(new_unexp_boards)))

    # 集合に変換
    new_unexp_boards = set(new_unexp_boards)

    # 発見済み盤面との重複排除
    # 以前は unknown / win001te / lose000te / 他の unexplored を毎回読み直していた
    # この4つは発見済み集合の分割なので, 順に引くことと和集合を1回引くことは同値
    if seen_boards is None:
        seen_boards, tbn_uk, tbn_win, tbn_lose = buildSeenBoards(offset)
    else:
        # このラウンドで振り分けた分は既存ファイルの中身と互いに素なので, 足すだけでよい
        tbn_uk += len(uk_boards)
        tbn_win += len(win_boards)
        tbn_lose += len(lose_boards)

    new_unexp_boards -= seen_boards
    seen_boards |= new_unexp_boards

    # 一旦リストに戻す (結合のため)
    new_unexp_boards = list(new_unexp_boards)
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
        return True
    
    # 書き込みファイルが読み込みファイルと同じなら, 空集合で初期化
    if offset == latest:
        writeAndBackup(fnamer_unexp, set())
    # 異なればファイル削除
    else:
        os.remove(fnamer_unexp)
    
    # 書き込み先ファイル
    fnamew_unexp = UNEXP_PATH_FORMAT.format(latest)
    # 読み込んでリストに変換
    with open(fnamew_unexp, "rb") as f:
        old_unexp_boards = list(pickle.load(f))
    # 結合
    new_unexp_boards = old_unexp_boards + new_unexp_boards
    # 分割してファイルに保存 (先頭は latest 番, 以後 1 つずつ番号を進める)
    # 添字で区切って集合にする. 残りのリストを作り直さない
    for start in range(0, len(new_unexp_boards), BOARD_NUM_MAX):
        writeAndBackup(UNEXP_PATH_FORMAT.format(latest), set(new_unexp_boards[start:start + BOARD_NUM_MAX]))
        # 最新番号の更新
        latest += 1

    return False

# 貯めた終端局面を書き出す (全探索の最後に1回)
# writeWLFilesForDepth() は既存ファイルを一切読まないので, 読み直しはゼロになる
def flushTerminalBoards():
    global catch_wins, try_loses
    writeWLFilesForDepth(catch_wins, 1, True)
    writeWLFilesForDepth(try_loses, 0, False)
    # 後退解析が始まる前に手放す (147,317,599 件ぶん)
    catch_wins = []
    try_loses = []

# 全盤面が出るまで探索
def searchAll():
    global seen_boards
    t0 = time.time()
    for _ in range(LOOP_MAX):
        flag = searchNext()
        dt_now = datetime.datetime.now()
        printLogSub(dt_now.strftime('%Y-%m-%d %H:%M:%S'))
        delta_t = int(time.time() - t0)
        printLogSub("%02d時間%02d分%02d秒経過" % (delta_t // 3600, delta_t % 3600 // 60, delta_t % 60))
        if flag:
            break
    # 貯めた終端盤面を書き出す (書き出し時間は全探索側に計上)
    flushTerminalBoards()
    # 発見済み集合を解放する
    # 後退解析の勝ち盤面と同時に抱えないため, ここで手放す (解放時間は全探索側に計上)
    seen_boards = None
    delta_t = int(time.time() - t0)
    printLogMain("%02d時間%02d分%02d秒で全探索終了" % (delta_t // 3600, delta_t % 3600 // 60, delta_t % 60))

# 全盤面の数を出力 (全盤面計算後のテスト用)
def countTotalBoardNum():
    tbn_uk = 0
    tbn_win = 0
    tbn_lose = 0
    for i in range(LOOP_MAX):
        fnamer = UK_PATH_FORMAT.format(i)
        if os.path.exists(fnamer):
            print(fnamer, "を読み込み")
            with open(fnamer, "rb") as f:
                tbn_uk += len(pickle.load(f))
        else:
            break
    for i in range(LOOP_MAX):
        fnamer = WIN_PATH_FORMAT.format(1, i)
        if os.path.exists(fnamer):
            print(fnamer, "を読み込み")
            with open(fnamer, "rb") as f:
                tbn_win += len(pickle.load(f))
        else:
            break
    for i in range(LOOP_MAX):
        fnamer = LOSE_PATH_FORMAT.format(0, i)
        if os.path.exists(fnamer):
            print(fnamer, "を読み込み")
            with open(fnamer, "rb") as f:
                tbn_lose += len(pickle.load(f))
        else:
            break
    print("未知盤面数：{:d}".format(tbn_uk))
    print("勝ち盤面数：{:d}".format(tbn_win))
    print("負け盤面数：{:d}".format(tbn_lose))
    print("末端盤面数：{:d}".format(tbn_win + tbn_win))
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
        with open(fnamer_uk, "rb") as f:
            uk_chunks.append(list(pickle.load(f)))
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
    rest = []
    for chunk in uk_chunks:
        rest += chunk
    total = len(rest)
    files_num = 0
    # 空でも1ファイルは作る (後退解析が全部を確定させた場合)
    if not rest:
        writeAndBackup(UK_PATH_FORMAT.format(0), set())
        files_num = 1
    # 添字で区切って集合にする. 残りのリストを作り直さない
    for start in range(0, total, BOARD_NUM_MAX):
        writeAndBackup(UK_PATH_FORMAT.format(files_num), set(rest[start:start + BOARD_NUM_MAX]))
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
        with open(fnamer, "rb") as f:
            packed.extend(pickle.load(f))
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
# 指し手生成も索引引きもC側で終わっているので, Python がするのは
# 「返ってきたバイト列を succ に繋ぐ」だけ
def buildSuccessors(n_uk: int) -> tuple:
    t1 = time.time()
    succ = array("I")
    succ_off = array("I", bytes(4))
    cnt = bytearray()
    # ⚠️ ループの外で1回だけ確保する. 呼び出しごとに作ると 99,485,568 回ぶん効く
    out = c_uint32_array50()
    # ⚠️ out[:n] と書くと PyLong を n 個作る (記録 #1 で 1.36× を失いかけた罠).
    #    memoryview 経由でバイト列のまま array に繋ぐ
    mv = memoryview(out).cast("B")
    nbi = nextBoardIndexNormal
    frombytes = succ.frombytes
    append_off = succ_off.append
    append_cnt = cnt.append
    total = 0
    outside = 0
    for i in range(n_uk):
        n = nbi(i, out)
        if n > 0:
            # 出次数は MAX_ACTION_NUM (48) 以下なので cnt (bytearray) に必ず入る
            frombytes(mv[: 4 * n])
            append_cnt(n)
            total += n
        elif n == -2:
            # 全探索を打ち切った dat/ では, 後続がまだ発見されていないことがある
            # (小さいフィクスチャでの等価性検査がこの経路を通る. 本番では起きない)
            # 未発見の後続は永久に未確定なので, 辺は張らずに出次数にだけ数えておく.
            # #5 の「lose_boards にも all_wins にも入らない後続」と同じ扱いになる
            n_found = out[48]
            degree = out[49]
            frombytes(mv[: 4 * n_found])
            # cnt は出次数そのもの (未発見の後続も数に入れる = その分 0 にならない)
            append_cnt(degree)
            total += n_found
            outside += degree - n_found
        else:
            # 0 (キャッチ) と -1 (トライ負け) なら未知盤面に終端が混ざっている.
            # -3 は src が範囲外か索引が未構築. どれもバグなので区別せず落とす
            raise RuntimeError("未知盤面の後続を作れない：%d 番目 (戻り値 %d)" % (i, n))
        append_off(total)
        if i % 10000000 == 0:
            printLogSub("P2 後続生成 {0:d}/{1:d} 辺 {2:d} {4:02d}分{5:02d}秒経過".format(
                i, n_uk, total, *s2hms(time.time() - t1)
            ))
    printLogMain("辺の総数：%d (未発見の後続 %d)" % (total, outside))
    printLogMain("P2 後続生成：{0:02d}時間{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t1)))
    return succ, succ_off, cnt

# 辺の向きを逆にして CSR に詰め直す (計数ソート)
def buildPredecessors(succ, succ_off, n_all: int) -> tuple:
    t1 = time.time()
    # 入次数を q+1 の位置に数えると, 累積和がそのままオフセットになる
    indeg = array("I", bytes(4)) * (n_all + 1)
    for q in succ:
        indeg[q + 1] += 1
    pred_off = array("I", itertools.accumulate(indeg))
    del indeg
    printLogSub("P4 入次数まで {0:02d}時間{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t1)))
    # 散らす
    cur = pred_off[:n_all]
    pred = array("I", bytes(4)) * len(succ)
    n_uk = len(succ_off) - 1
    for src in range(n_uk):
        for q in succ[succ_off[src]:succ_off[src + 1]]:
            j = cur[q]
            pred[j] = src
            cur[q] = j + 1
        if src % 10000000 == 0:
            printLogSub("P4 散らし {0:d}/{1:d} {3:02d}分{4:02d}秒経過".format(
                src, n_uk, *s2hms(time.time() - t1)
            ))
    del cur
    if pred_off[n_all] != len(succ):
        raise RuntimeError("前任リストの総数が合わない：%d / %d" % (pred_off[n_all], len(succ)))
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

    packed, n_uk, n_win, n_lose = loadForwardResult()
    n_all = len(packed)
    buildIndex(packed)
    succ, succ_off, cnt = buildSuccessors(n_uk)
    # 後続は連番で入っているので, ここから先で索引は要らない
    indexFree()
    pred, pred_off = buildPredecessors(succ, succ_off, n_all)
    del succ, succ_off

    # 手数. 255 が未確定で, 最後まで 255 のものが引き分けになる
    # 奇数が勝ち, 偶数が負け (パリティで判別できるので結果ビットは要らない)
    dtm = bytearray(b"\xff") * n_all
    catch_lo = n_uk
    catch_hi = n_uk + n_win
    dtm[catch_lo:catch_hi] = b"\x01" * n_win
    dtm[catch_hi:] = bytes(n_lose)

    # 深さ0 のフロンティアはトライ負けの範囲そのもの
    frontier = range(catch_hi, n_all)
    depth = 0
    for _ in range(LOOP_MAX):
        t1 = time.time()
        printLogSub("#" * 100)
        printLogMain("#" * 100)
        nd = depth + 1
        if nd >= 255:
            raise RuntimeError("手数が dtm に入らない：%d" % nd)
        found = []
        append = found.append
        if depth % 2 == 0:
            # q が負け → 前任は1手で勝てる
            for q in frontier:
                for p in pred[pred_off[q]:pred_off[q + 1]]:
                    if dtm[p] == 255:
                        dtm[p] = nd
                        append(p)
        else:
            # q が勝ち → 前任の残り出次数を減らす
            # 0 になったら後続が全部勝ちなので負け
            for q in frontier:
                for p in pred[pred_off[q]:pred_off[q + 1]]:
                    v = cnt[p] - 1
                    cnt[p] = v
                    if v == 0 and dtm[p] == 255:
                        dtm[p] = nd
                        append(p)
        writeWLFilesForDepth([packed[i] for i in found], nd, nd % 2 == 1)
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
            frontier = itertools.chain(range(catch_lo, catch_hi), found)
        else:
            frontier = found
        depth = nd

    # 最後まで未知だった盤面 (＝引き分け) を成果物として書き出す
    writeUnknownChunks([[packed[i] for i in range(n_uk) if dtm[i] == 255]])

def main():
    t0 = time.time()
    searchAll()
    retreatAnalysis()
    printLogMain("完全解析にかかった時間：%2d時間%2d分%2d秒" % s2hms(time.time() - t0))

if __name__ == "__main__":
    main()
