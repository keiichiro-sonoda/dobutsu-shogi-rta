#!/usr/bin/python3

import datetime
import pickle
import os
import time
import re
import shutil
from ctypes import c_int32, c_uint64, CDLL

# 次の盤面を受け取るための配列型
c_uint64_array48 = c_uint64 * 48

INITIAL_BOARD = 0x000a003c914b002

# 1ファイルに格納する盤面数の最大値
# 1000万は2Gメモリがあふれるらしい
BOARD_NUM_MAX = 5000000

# 未知盤面の連結判定に用いる定数
# 10倍で溢れたので結合はもっと小さくしてから
UK_FILE_SIZE_MAX = BOARD_NUM_MAX * 4

# ディレクトリのパス
DIR_PATH = "./dat/"

# 負け盤面のパス
LOSE_PATH_FORMAT = DIR_PATH + "lose{:03d}te_{:03d}.pickle"

# 勝ち盤面のパス
WIN_PATH_FORMAT = DIR_PATH + "win{:03d}te_{:03d}.pickle"

# 未知盤面のパス
UK_PATH_FORMAT = DIR_PATH + "unknown{:03d}.pickle"

# 未知盤面周辺盤面のパス
UK_NEXT_PATH_FORMAT = DIR_PATH + "unknown{:03d}_next.pickle"

# 未知盤面周辺勝ち盤面のパス
UK_NEXT_WIN_PATH_FORMAT = DIR_PATH + "unknown{:03d}_next_win.pickle"

# 未探索盤面のパス
UNEXP_PATH_FORMAT = DIR_PATH + "unexplored{:03d}.pickle"

# バックアップフラグ (真ならファイル上書きの度にバックアップ)
BACK_UP = False

# 適当なループ数 (break前提)
LOOP_MAX = 10000

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

def updateWLFile(wlbl: list, wl_depth: int, win: bool) -> int:
    """
    勝ち盤面, 負け盤面のファイルの更新.
    手数も考慮する.
    副番号はこの関数内で探す.
    引数にはリストを与えるが, 集合に変換して書き込む.
    """
    if win:
        wl_path_format = WIN_PATH_FORMAT
    else:
        wl_path_format = LOSE_PATH_FORMAT
    wl_sub = 0
    # 副番号探索
    for i in range(300):
        fnamer_wl = wl_path_format.format(wl_depth, i)
        if os.path.exists(fnamer_wl):
            wl_sub = i
        else:
            break
    
    # その深さのファイルが存在しない場合は作成 (空ファイルから)
    if i == 0:
        fnamer_wl = wl_path_format.format(wl_depth, 0)
        writeAndBackup(fnamer_wl, [])
    
    # 最新の副番号のファイルに書き込む
    fnamew_wl = wl_path_format.format(wl_depth, wl_sub)
    # 過去に出た勝ち (負け) 盤面
    with open(fnamew_wl, "rb") as f:
        known_wlbl = list(pickle.load(f))
    # 新しい勝ち盤面のリストと結合
    wlbl = known_wlbl + wlbl

    # ファイルの上限を上回ったら, 分割
    # 3個以上の分割は考慮しない
    if len(wlbl) > BOARD_NUM_MAX:
        # 上限まで元ファイルに書き出し
        writeAndBackup(fnamew_wl, set(wlbl[:BOARD_NUM_MAX]))
        # リストとファイル名を変更
        wlbl = wlbl[BOARD_NUM_MAX:]
        wl_sub += 1
        fnamew_wl = wl_path_format.format(wl_depth, wl_sub)

    # 元のファイルに書き戻し (または新ファイルに書き出し)
    writeAndBackup(fnamew_wl, set(wlbl))

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
        # リストとファイル名を変更
        ukl = ukl[BOARD_NUM_MAX:]
        uk_sub += 1
        fnamew_uk = UK_PATH_FORMAT.format(uk_sub)

    # 元のファイルに書き戻し (または新ファイルに書き出し)
    writeAndBackup(fnamew_uk, set(ukl))

# まずは全盤面を洗い出したい
# 葉ノード (一手で勝てる盤面) は別ファイルに書き出す
# 初期盤面からの手数は考慮せず, 勝ち, 負け, 未知の3種に分けて保存
def searchNext():
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

    # 末端の更新
    updateWLFile(win_boards, 1, True)
    updateWLFile(lose_boards, 0, False)
    # 未知盤面の更新
    updateUKFile(uk_boards)

    printLogSub("新状態数 (重複排除前)：{:d}".format(len(new_unexp_boards)))

    # 集合に変換
    new_unexp_boards = set(new_unexp_boards)

    # 重複排除のついでに各盤面の総数も計算
    tbn_uk = 0
    tbn_win = 0
    tbn_lose = 0
    # 未知盤面との重複排除
    for i in range(LOOP_MAX):
        fnamer_uk = UK_PATH_FORMAT.format(i)
        if os.path.exists(fnamer_uk):
            with open(fnamer_uk, "rb") as f:
                past_boards = pickle.load(f)
            new_unexp_boards -= past_boards
            tbn_uk += len(past_boards)
        else:
            break
    
    # 勝ち盤面との重複排除
    for i in range(LOOP_MAX):
        fnamer_win = WIN_PATH_FORMAT.format(1, i)
        if os.path.exists(fnamer_win):
            with open(fnamer_win, "rb") as f:
                past_boards = pickle.load(f)
            new_unexp_boards -= past_boards
            tbn_win += len(past_boards)
        else:
            break
    
    # 負け盤面との重複排除
    for i in range(LOOP_MAX):
        fnamer_lose = LOSE_PATH_FORMAT.format(0, i)
        if os.path.exists(fnamer_lose):
            with open(fnamer_lose, "rb") as f:
                past_boards = pickle.load(f)
            new_unexp_boards -= past_boards
            tbn_lose += len(past_boards)
        else:
            break
    
    # 他の未探索盤面との重複排除
    for i in range(offset + 1, LOOP_MAX):
        fnamer_unexp_another = UNEXP_PATH_FORMAT.format(i)
        if os.path.exists(fnamer_unexp_another):
            with open(fnamer_unexp_another, "rb") as f:
                past_boards = pickle.load(f)
            new_unexp_boards -= past_boards
        else:
            break

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
    # 分割してファイルに保存
    while len(new_unexp_boards) > BOARD_NUM_MAX:
        # 集合に変換
        writeAndBackup(fnamew_unexp, set(new_unexp_boards[:BOARD_NUM_MAX]))
        # 分割した残り
        new_unexp_boards = new_unexp_boards[BOARD_NUM_MAX:]
        # 最新番号の更新
        latest += 1
        fnamew_unexp = UNEXP_PATH_FORMAT.format(latest)
    
    # 残り
    if new_unexp_boards:
        writeAndBackup(fnamew_unexp, set(new_unexp_boards))

    return False

# 全盤面が出るまで探索
def searchAll():
    t0 = time.time()
    for _ in range(LOOP_MAX):
        flag = searchNext()
        dt_now = datetime.datetime.now()
        printLogSub(dt_now.strftime('%Y-%m-%d %H:%M:%S'))
        delta_t = int(time.time() - t0)
        printLogSub("%02d時間%02d分%02d秒経過" % (delta_t // 3600, delta_t % 3600 // 60, delta_t % 60))
        if flag:
            break
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

# 勝ち盤面の探索
# ひとつ前の負け盤面を参照
# ファイルには集合型で保存してある
def searchWinBoard():
    printLogSub("#" * 100)
    printLogMain("#" * 100)
    t1 = time.time()
    act_num = 0
    end_flag = False
    # 最新ファイルを探す
    for i in range(0, LOOP_MAX, 2):
        fnamer_lose = LOSE_PATH_FORMAT.format(i, 0)
        if os.path.exists(fnamer_lose):
            # ループ終了時に最新の手数が入るはず
            act_num = i
        else:
            break
    # リストで連結
    lose_boards = []
    for i in range(LOOP_MAX):
        fnamer_lose = LOSE_PATH_FORMAT.format(act_num, i)
        if os.path.exists(fnamer_lose):
            # 存在したら負け盤面に追加
            with open(fnamer_lose, "rb") as f:
                lose_boards += list(pickle.load(f))
        else:
            break
    # in の高速化のために集合型に戻す
    lose_boards = set(lose_boards)
    printLogSub("参照する{:3d}手負け盤面の数：{:03d}".format(act_num, len(lose_boards)))
    act_num += 1
    printLogSub("{:3d}手勝ち盤面の検索".format(act_num))
    tbnw = 0
    # 全 unknown ファイルについて処理を行う
    for i in range(LOOP_MAX):
        printLogSub("#" * 100)
        fnamer_uk = UK_PATH_FORMAT.format(i)
        if not os.path.exists(fnamer_uk):
            break
        printLogSub("%sから勝ち盤面を検索" % fnamer_uk)
        new_uk_boards = []
        new_win_boards = []
        # 負け盤面作成の際に用いる周辺盤面も作成
        next_boards = []
        fnamer_uk_next = UK_NEXT_PATH_FORMAT.format(i)
        # 未知盤面集合を取得
        with open(fnamer_uk, "rb") as f:
            uk_boards = pickle.load(f)
        printLogSub("探索盤面数：{:d}".format(len(uk_boards)))
        # 全探索するまでループ
        while uk_boards:
            board = uk_boards.pop()
            # 末端盤面でないことは前提とする
            nbn, nbl = nextBoardInvNormalWrap(board)
            for nb in nbl:
                # 負け盤面に遷移できるなら勝ち盤面とする
                if nb in lose_boards:
                    new_win_boards.append(board)
                    break
            # break なしなら未知のまま
            else:
                new_uk_boards.append(board)
                next_boards += nbl
        tmp_len = len(new_win_boards)
        tbnw += tmp_len
        printLogSub("新勝ち盤面数：{:d}, 新未知盤面数：{:d}".format(tmp_len, len(new_uk_boards)))
        # 重複排除で集合に変換
        next_boards = set(next_boards)
        printLogSub("周辺盤面数：{:d}".format(len(next_boards)))
        # 勝ち盤面更新 (リストで渡すが集合に変換される)
        updateWLFile(new_win_boards, act_num, True)
        # 新未知盤面を書き戻し (集合に変換)
        writeAndBackup(fnamer_uk, set(new_uk_boards))
        # 周辺盤面の書き出し
        writeAndBackup(fnamer_uk_next, next_boards)
        dt_now = datetime.datetime.now()
        printLogSub(dt_now.strftime('%Y-%m-%d %H:%M:%S'))
        printLogSub("{1:02d}分{2:02d}秒経過".format(*s2hms(time.time() - t1)))
    # 1手勝ち盤面だけ例外
    if act_num == 1:
        printLogMain("  1手勝ち盤面総数 (キャッチ除く)：%d" % tbnw)
    else:
        printLogMain("%3d手勝ち盤面総数：%d" % (act_num, tbnw))
    printLogMain("所要時間：{0:02d}時間{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t1)))
    # 勝ち盤面が増えなかった
    if tbnw == 0:
        printLogMain("完全解析終了")
        end_flag = True
    return end_flag

# 負け盤面の探索
# 周辺勝ち盤面を参照
def searchLoseBoard():
    printLogSub("#" * 100)
    printLogMain("#" * 100)
    t1 = time.time()
    act_num = 0
    end_flag = False
    # 勝ち盤面の最新手数を探す
    for i in range(1, 300, 2):
        fnamer_lose = WIN_PATH_FORMAT.format(i, 0)
        if os.path.exists(fnamer_lose):
            # ループ終了時に最新の手数が入るはず
            act_num = i
        else:
            break
    # 次に進める
    act_num += 1
    printLogSub("{:3d}手負け盤面の検索".format(act_num))
    tbnl = 0
    # 全 unknown ファイルについて処理を行う
    for i in range(LOOP_MAX):
        printLogSub("#" * 100)
        fnamer_uk = UK_PATH_FORMAT.format(i)
        if not os.path.exists(fnamer_uk):
            break
        printLogSub(fnamer_uk + "から負け盤面を検索")
        # 未知盤面取得
        with open(fnamer_uk, "rb") as f:
            uk_boards = pickle.load(f)
        printLogSub("探索盤面数：{:d}".format(len(uk_boards)))

        # 周辺勝ち盤面を集合で取得
        fnamer_uk_next_win = UK_NEXT_WIN_PATH_FORMAT.format(i)
        with open(fnamer_uk_next_win, "rb") as f:
            win_boards = pickle.load(f)
        printLogSub("参照勝ち盤面数：{:d}".format(len(win_boards)))

        new_uk_boards = []
        new_lose_boards = []
        # 全探索するまでループ
        while uk_boards:
            board = uk_boards.pop()
            # 末端盤面でないことは前提とする
            nbn, nbl = nextBoardInvNormalWrap(board)
            for nb in nbl:
                # 勝ち盤面に含まれない盤面に遷移できるなら未知とする
                if not nb in win_boards:
                    new_uk_boards.append(board)
                    break
            # break なし (行き先が全て勝ち盤面) なら負け盤面
            else:
                new_lose_boards.append(board)

        tmp_len = len(new_lose_boards)
        tbnl += tmp_len
        printLogSub("新負け盤面数：{:d}, 新未知盤面数：{:d}".format(tmp_len, len(new_uk_boards)))
        # 負け盤面更新
        updateWLFile(new_lose_boards, act_num, False)
        # 新未知盤面を書き戻し (集合に戻す)
        writeAndBackup(fnamer_uk, set(new_uk_boards))
        dt_now = datetime.datetime.now()
        printLogSub(dt_now.strftime('%Y-%m-%d %H:%M:%S'))
        printLogSub("{1:02d}分{2:02d}秒経過".format(*s2hms(time.time() - t1)))
    
    printLogMain("%3d手負け盤面総数：%d" % (act_num, tbnl))
    printLogMain("所要時間：{0:02d}時間{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t1)))
    
    # 負け盤面が見つからなかった
    if tbnl == 0:
        printLogMain("完全解析終了")
        end_flag = True

    return end_flag

# 新規作成
def createNextWin():
    t1 = time.time()
    printLogMain("周辺勝ち盤面の新規作成")
    # 未知盤面の周辺
    for i in range(LOOP_MAX):
        fnamer_uk_next = UK_NEXT_PATH_FORMAT.format(i)
        if not os.path.exists(fnamer_uk_next):
            break
        fnamew_uk_next_win = UK_NEXT_WIN_PATH_FORMAT.format(i)
        printLogSub(fnamew_uk_next_win + " の作成")
        # リストを初期化
        next_win_boards = []
        # 周辺盤面集合を取得
        with open(fnamer_uk_next, "rb") as f:
            next_boards = pickle.load(f)
        printLogSub("周辺盤面数：{:d}".format(len(next_boards)))
        # 1手勝ち盤面全て
        for i in range(LOOP_MAX):
            fnamer_win = WIN_PATH_FORMAT.format(1, i)
            if not os.path.exists(fnamer_win):
                break
            with open(fnamer_win, "rb") as f:
                win_boards = pickle.load(f)
            # 積集合を計算し, リストに追加
            next_win_boards += list(next_boards & win_boards)
        printLogSub("周辺勝ち盤面数：{:d}".format(len(next_win_boards)))
        # 集合に変換してファイル書き込み
        writeAndBackup(fnamew_uk_next_win, set(next_win_boards))
        printLogSub("%02d時間%02d分%02d秒経過" % s2hms(time.time() - t1))
    printLogMain("所要時間：%02d時間%02d分%02d秒" % s2hms(time.time() - t1))

# 周辺の勝ち盤面を更新
# または新規作成
def updateNextWin():
    act_num = 0
    # 最新の勝ち盤面を探索
    for i in range(1, LOOP_MAX, 2):
        fnamer_win = WIN_PATH_FORMAT.format(i, 0)
        if os.path.exists(fnamer_win):
            act_num = i
        else:
            break

    # 初めて
    if act_num == 1:
        createNextWin()
        return
    
    printLogMain("#" * 100)
    t1 = time.time()
    printLogMain("周辺勝ち盤面に{:3d}手勝ち盤面を追加".format(act_num))
    # 全未知盤面ファイルで繰り返し
    for i in range(LOOP_MAX):
        printLogSub("#" * 100)
        fnamer_uk_next = UK_NEXT_PATH_FORMAT.format(i)
        if not os.path.exists(fnamer_uk_next):
            break
        # 読み込み件書き込みファイル
        fnamew_uk_next_win = UK_NEXT_WIN_PATH_FORMAT.format(i)
        printLogSub(fnamew_uk_next_win + "を更新")
        next_win_boards = []
        # 周辺盤面を取得
        with open(fnamer_uk_next, "rb") as f:
            next_boards = pickle.load(f)
        printLogSub("周辺盤面数：{:d}".format(len(next_boards)))
        # 過去の周辺勝ち盤面を取得
        with open(fnamew_uk_next_win, "rb") as f:
            win_boards = pickle.load(f)
        printLogSub("旧周辺勝ち盤面数：{:d}".format(len(win_boards)))
        # 過去の周辺勝ち盤面から不要な部分を削除
        next_win_boards += list(next_boards & win_boards)
        # n手勝ち盤面全て
        for i in range(100):
            fnamer_win = WIN_PATH_FORMAT.format(act_num, i)
            if not os.path.exists(fnamer_win):
                break
            with open(fnamer_win, "rb") as f:
                win_boards = pickle.load(f)
            # 積集合を計算し, リストに追加
            next_win_boards += list(next_boards & win_boards)
        printLogSub("新周辺勝ち盤面数：{:d}".format(len(next_win_boards)))
        # ファイル更新 (集合に変換)
        writeAndBackup(fnamew_uk_next_win, set(next_win_boards))
        dt_now = datetime.datetime.now()
        printLogSub(dt_now.strftime('%Y-%m-%d %H:%M:%S'))
        printLogSub("{1:02d}分{2:02d}秒経過".format(*s2hms(time.time() - t1)))
    printLogMain("所要時間：%02d時間%02d分%02d秒" % s2hms(time.time() - t1))

# 参照渡しで与えたリストにファイルから読み込んだ盤面をくっつける
# リストでくっつけた方がはやい??
def addUKRelatedBoards(ukbl: list, uknbl: list, uknwbl: list, n: int) -> None:
    fnamer_uk = UK_PATH_FORMAT.format(n)
    # 他ファイルの盤面と結合
    with open(fnamer_uk, "rb") as f:
        ukbl += list(pickle.load(f))
    # 周辺盤面も結合
    fnamer_uk_next = UK_NEXT_PATH_FORMAT.format(n)
    with open(fnamer_uk_next, "rb") as f:
        uknbl += list(pickle.load(f))
    # 周辺勝ち盤面も結合
    fnamer_uk_next_win = UK_NEXT_WIN_PATH_FORMAT.format(n)
    with open(fnamer_uk_next_win, "rb") as f:
        uknwbl += list(pickle.load(f))

# 未知盤面関連ファイルの書き込み
# 周辺盤面, 周辺勝ち盤面
# 重複排除も行う
def writeUKRelatedFiles(ukbl: list, uknbl: list, uknwbl: list, n: int) -> None:
    # 全て集合に変換
    ukbs = set(ukbl)
    uknbs = set(uknbl)
    uknwbs = set(uknwbl)

    # 与えられたリストは全てクリア
    ukbl.clear()
    uknbl.clear()
    uknwbl.clear()

    fnamew_uk = UK_PATH_FORMAT.format(n)
    fnamew_uk_next = UK_NEXT_PATH_FORMAT.format(n)
    fnamew_uk_next_win = UK_NEXT_WIN_PATH_FORMAT.format(n)

    printLogSub("盤面数 %d で %s に書き込み" % (len(ukbs), fnamew_uk))
    printLogSub("盤面数 %d で %s に書き込み" % (len(uknbs), fnamew_uk_next))
    printLogSub("盤面数 %d で %s に書き込み" % (len(uknwbs), fnamew_uk_next_win))

    writeAndBackup(fnamew_uk, ukbs)
    writeAndBackup(fnamew_uk_next, uknbs)
    writeAndBackup(fnamew_uk_next_win, uknwbs)

def organizeUKFiles():
    """
    未知盤面ファイルの整理
    連番ファイルの盤面数の和が一定値以下の場合, ファイルを結合
    next, next_win ファイルも結合
    """
    printLogSub("#" * 100)
    printLogSub("結合後上限ファイルサイズ：%d" % UK_FILE_SIZE_MAX)
    t0 = time.time()
    comb_nums_list = []
    uk_file_siz = 0
    comb_nums = tuple()
    files_num = 0
    for i in range(LOOP_MAX):
        fnamer_uk = UK_PATH_FORMAT.format(i)
        if os.path.exists(fnamer_uk):
            # 盤面数でなくファイルサイズを見る (時短のため)
            tmp_siz = os.path.getsize(fnamer_uk)
            printLogSub("%sのファイルサイズ：%d" % (fnamer_uk, tmp_siz))
            uk_file_siz += tmp_siz
            if uk_file_siz <= UK_FILE_SIZE_MAX:
                comb_nums += (i,)
            elif comb_nums:
                comb_nums_list.append(comb_nums)
                comb_nums = (i,)
                uk_file_siz = tmp_siz
            else:
                comb_nums_list.append((i,))
                uk_file_siz = 0
        else:
            files_num = i
            break

    if comb_nums:
        comb_nums_list.append(comb_nums)
    printLogSub("結合する番号のペア")
    printLogSub(comb_nums_list)
    uk_boards = []
    uk_next_boards = []
    uk_next_win_boards = []
    for i, comb_nums in enumerate(comb_nums_list):
        # 結合できなかった場合
        if len(comb_nums) == 1:
            j = comb_nums[0]
            # さらに番号が異なる場合, ファイル名だけ変えてコピー
            if i != j:
                shutil.copyfile(UK_PATH_FORMAT.format(j), UK_PATH_FORMAT.format(i))
                shutil.copyfile(UK_NEXT_PATH_FORMAT.format(j), UK_NEXT_PATH_FORMAT.format(i))
                shutil.copyfile(UK_NEXT_WIN_PATH_FORMAT.format(j), UK_NEXT_WIN_PATH_FORMAT.format(i))
            continue
        # 全部足す
        for j in comb_nums:
            addUKRelatedBoards(uk_boards, uk_next_boards, uk_next_win_boards, j)
        # 書き込んでクリア
        writeUKRelatedFiles(uk_boards, uk_next_boards, uk_next_win_boards, i)
    printLogSub("整理にかかった時間：{1:02d}分{2:02d}秒".format(*s2hms(time.time() - t0)))

    # ファイル削除
    for i in range(i + 1, files_num):
        os.remove(UK_PATH_FORMAT.format(i))
        os.remove(UK_NEXT_PATH_FORMAT.format(i))
        os.remove(UK_NEXT_WIN_PATH_FORMAT.format(i))

def retreatAnalysis():
    """
    全探索終了後に実行
    よくわからないけど後退解析と呼ぶらしい
    """
    for _ in range(LOOP_MAX):
        if searchWinBoard():
            break
        updateNextWin()
        organizeUKFiles()
        if searchLoseBoard():
            break

def main():
    t0 = time.time()
    searchAll()
    retreatAnalysis()
    printLogMain("完全解析にかかった時間：%2d時間%2d分%2d秒" % s2hms(time.time() - t0))

if __name__ == "__main__":
    main()
