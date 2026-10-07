"""全探索だけを走らせる (実験 forward_prep。記録試行ではない)。

    python3 driver.py <time|verify>

impl/33 の animal_shogi.py (腕のパッチを当てたもの) を読み込み, searchAll() だけを呼ぶ
(experiments/gate_17_forward の driver と同じ形. 後退解析は走らせない).
searchAll() が kaiseki_log/forward.tsv と forward_summary.tsv を書き, 全探索の側の dat/
(キャッチ局面 win001te_* とトライ負け lose000te_*) を書く.
終わったあとで (計時の外), 全探索が後退解析に渡す3本の列 (未知局面 uk_all, キャッチ局面,
トライ負け局面) の sha256 を出す. 並びまで含めた指紋なので, 腕のあいだで展開の順と採番順が
同じかを見られる. verify のときは, 腕に配列があれば prep.bin に書き出す
(腕 carry の検査用ビルドなら, 積んだランクの食い違いの数も出す).
"""

import ctypes
import hashlib
import importlib.util
import pathlib
import sys
import time

mode = sys.argv[1]
spec = importlib.util.spec_from_file_location("fpmod", "animal_shogi.py")
if spec is None or spec.loader is None:
    raise SystemExit("animal_shogi.py が読めない")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
t = time.perf_counter()
mod.searchAll()
print(f"全探索の所要時間：{time.perf_counter() - t:.2f} 秒")
for name in ("uk_all", "catch_wins", "try_loses"):
    a = getattr(mod, name)
    sha = hashlib.sha256(a.tobytes()).hexdigest()
    print(f"出力の指紋 {name}: {len(a)} 件 sha256 {sha}")
if mode == "verify" and hasattr(mod.lib, "prepPtr"):
    mod.lib.prepPtr.restype = ctypes.c_void_p
    mod.lib.rankRange.restype = ctypes.c_uint64
    n = mod.lib.rankRange()
    pathlib.Path("prep.bin").write_bytes(ctypes.string_at(mod.lib.prepPtr(), n))
    print(f"prep.bin: {n} バイト")
    if hasattr(mod.lib, "prepRankBad"):
        mod.lib.prepRankBad.restype = ctypes.c_uint64
        print(f"積んだランクと計算し直したランクの食い違い: {mod.lib.prepRankBad()}")
