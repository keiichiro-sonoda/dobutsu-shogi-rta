# 記録したアテンプトのログ置き場

README の記録表に載せた実行それぞれについて、証拠をここに残す。

```
results/<番号>_<ラベル>/
    env.txt         実行時のマシン構成
    main.log        完全解析のメインログ (verify_log.py に通したもの)
    time.txt        /usr/bin/time -v の出力
    verify.txt      検証結果
```

`runs/` は .gitignore しているので、記録として残すものだけをここへコピーする
（サブログは巨大になるので入れない）。
