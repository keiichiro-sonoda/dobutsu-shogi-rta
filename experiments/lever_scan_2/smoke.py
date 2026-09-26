#!/usr/bin/python3
"""6腕を小さく回して, 出力が base と一致することを確かめる (実験 lever_scan_2。記録試行ではない)。

    python3 experiments/lever_scan_2/smoke.py > experiments/lever_scan_2/logs/smoke.txt

門番 (完走 36本) の前に, 腕の組み立てと答えの取り違えを小さく見つけるためのもの。
腕ごとに make_arm.sh で組み (門番と同じ .so), 別のプロセスで次を走らせる:

  BOARD_NUM_MAX = 2000 にして searchAll() を 40 ラウンドで打ち切り,
  そのまま retreatAnalysis() まで回す

比べるもの (どれも base と一致するはず):
  - dat/ の中身 (ファイル名と md5 の一覧の sha256)
  - buildPredecessors() が返した pred / pred_off のバイト列の sha256
    (hugeR は確保の経路を C に変えたので, 中身も並びも変わらないことをここで見る)
  - ラウンドごとの件数 (forward.tsv の件数の列と同じ値)
  - 計装の行 (minflt_F1 / anonhuge_loop_kB) が要約ファイルに出ていること
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ARMS = ("base", "pf2", "pf3", "hugeR", "reuse", "all")
ROUNDS = 40
BOARD_NUM_MAX = 2000

DRIVER = r"""
import hashlib, importlib.util, json, pathlib
KEYS = ("n_in", "n_win", "n_lose", "n_uk", "n_new_post")
spec = importlib.util.spec_from_file_location("arm", "animal_shogi.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
vars(m)["BOARD_NUM_MAX"] = %(board_num_max)d
counts = []
got = {}
real_next = m.searchNext
real_bp = m.buildPredecessors

def limited():
    flag = bool(real_next())
    counts.append([m._prof.get(k, 0) for k in KEYS])
    return flag or len(counts) >= %(rounds)d

def bp(*args):
    pred, pred_off = real_bp(*args)
    got["pred"] = hashlib.sha256(bytes(memoryview(pred))).hexdigest()
    got["pred_off"] = hashlib.sha256(bytes(memoryview(pred_off))).hexdigest()
    return pred, pred_off

vars(m)["searchNext"] = limited
vars(m)["buildPredecessors"] = bp
m.searchAll()
m.retreatAnalysis()
lines = [
    "%%s  %%s" %% (hashlib.md5(p.read_bytes()).hexdigest(), p.name)
    for p in sorted(pathlib.Path("dat").iterdir())
]
got["files"] = len(lines)
got["dat"] = hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()
got["counts"] = counts
fs = dict(ln.split("\t", 1) for ln in open("kaiseki_log/forward_summary.tsv").read().splitlines())
rs = dict(ln.split("\t", 1) for ln in open("kaiseki_log/retreat_summary.tsv").read().splitlines())
got["instr"] = "minflt_F1" in fs and "anonhuge_loop_kB" in rs
print(json.dumps(got))
"""


def run(arm: str, work: pathlib.Path) -> dict:
    subprocess.run([str(HERE / "make_arm.sh"), arm, str(work)], check=True, capture_output=True)
    (work / "dat").mkdir()
    (work / "kaiseki_log").mkdir()
    code = DRIVER % {"board_num_max": BOARD_NUM_MAX, "rounds": ROUNDS}
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=work, capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise SystemExit(f"{arm} が落ちた:\n{done.stderr}")
    result: dict = json.loads(done.stdout.strip().splitlines()[-1])
    return result


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        results = {arm: run(arm, pathlib.Path(tmp) / arm) for arm in ARMS}
    base = results["base"]
    print("# 6腕を小さく回して base と比べた (smoke.py の出力)")
    print(f"# BOARD_NUM_MAX = {BOARD_NUM_MAX}, searchAll() を {ROUNDS} ラウンドで打ち切って")
    print("# retreatAnalysis() まで回した")
    print("#")
    ok = True
    for arm, r in results.items():
        same = {k: r[k] == base[k] for k in ("dat", "pred", "pred_off", "counts")}
        verdict = "一致" if all(same.values()) and r["instr"] else "**不一致**"
        ok = ok and verdict == "一致"
        print(
            f"{arm:6s} dat {r['files']} ファイル {r['dat'][:16]}… / pred {r['pred'][:16]}… / "
            f"pred_off {r['pred_off'][:16]}… / {len(r['counts'])} ラウンド / 計装の行 "
            f"{'あり' if r['instr'] else '**無し**'} → base と {verdict}"
        )
    print()
    print("=> 6腕とも base と一致" if ok else "=> **一致しない腕がある**")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
