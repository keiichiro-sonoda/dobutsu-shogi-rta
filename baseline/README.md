# baseline/ — 計測の出発点

2021年11月に書いた完全解析プログラムを、**当時のまま**置いたもの。
RTAの出発点なので、このディレクトリのファイルは今後も書き換えない。
改善はすべて別ディレクトリで行う。

| ファイル | sha256 | 役割 |
|---|---|---|
| `animal_shogi.py` | `cc354e30…d48085f7` | 全探索・後退解析の本体。集合演算とファイル分割を担当 |
| `animal_shogi.c` | `79989813…e42f27ad` | 指し手生成・盤面反転・鏡面正規化 |
| `animal_shogi.h` | `fdec3e10…e9365db6` | 上のヘッダ |

`Makefile` だけは共有ライブラリを作るルールだけを残した（当時のファイルには
無関係な課題プログラムのルールも同居していたため）。コマンド行は原文のまま。

```make
animal_shogi.so: animal_shogi.c animal_shogi.h
	gcc animal_shogi.c -o animal_shogi.so -Wall -fPIC -shared
```

⚠️ **最適化フラグが無い**（＝`-O0`）。当時のまま残してある。

## 構成

`main()` は `searchAll()` → `retreatAnalysis()` の2段。
Python + C の共有ライブラリを ctypes で叩くハイブリッドで、
Python が集合演算とファイル分割、C が指し手生成と鏡面正規化を担当する。

## 踏みやすい罠

- **Linux 専用。** `u_long` と `.so` に依存している
- **`animal_shogi.so` があると `import animal_shogi` は `.py` ではなく `.so` を拾う**
  （`PyInit_animal_shogi` が無いので ImportError になる）。直接実行する分には問題ない
- **`./dat/` と `./kaiseki_log/` をカレントディレクトリ相対で使う。**
  どちらも存在しないと動かない。`tools/run.sh` が作業ディレクトリを切って用意する
- ログの出力先が `kaiseki_log/kaizenkaiseki1.txt`（`kanzen` ではない）。当時の誤字
