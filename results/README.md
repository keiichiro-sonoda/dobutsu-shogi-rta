# 記録したアテンプトのログ置き場

README の記録表に載せた実行それぞれについて、証拠をここに残す。

```
results/<番号>_<ラベル>/
    env.txt         実行時のマシン構成と、何を計測したか
    main.log        完全解析のメインログ (verify_log.py に通したもの)
    time.txt        /usr/bin/time -v の出力
    verify.txt      オラクル検証の結果
    fingerprint.txt 直前の記録との成果物照合 (集計経路を変えたときだけ)
```

`fingerprint.txt` は `tools/fingerprint_dat.py` の出力。オラクルは手数別の**局面数**しか
見ないので、実装の集計経路を書き換えたときは `dat/` そのものを突き合わせて
「どの局面がどの手数か」まで確かめる。

`runs/` は .gitignore しているので、記録として残すものだけをここへコピーする
（サブログは巨大になるので入れない）。
