"""計測ハーネス (tools/run.sh) についての取り決め。"""

from __future__ import annotations

import re

from conftest import BASELINE_DIR, RESULTS_DIR, ROOT

RUN_SH = ROOT / "tools" / "run.sh"

# env.txt に必ず入っていてほしい項目。
# 計測機の同一性 (kernel..git_commit) と、何を測ったのか (impl..run_cmd) の両方。
REQUIRED_ENV_FIELDS = (
    "impl",
    "impl_sha256",
    "build_cmd",
    "run_cmd",
    "kernel",
    "cpu",
    "cores",
    "mem_total",
    "gcc",
    "python",
    "git_commit",
    # 記録 #21 から。巨大ページの効き目は THP の設定に依存し、ユーザー時間と
    # カーネル時間の配分はタイマー割り込みの周期 (CONFIG_HZ) で決まる
    "thp_enabled",
    "thp_defrag",
    "config_hz",
)


def run_sh() -> str:
    return RUN_SH.read_text(encoding="utf-8")


def shell_default(name: str) -> str:
    """run.sh が持っている既定値 (`NAME="値"` の形) を取り出す。"""
    m = re.search(rf'^{name}="([^"]*)"', run_sh(), re.MULTILINE)
    assert m, f"tools/run.sh に {name} の既定値が無い"
    return m.group(1)


def test_run_sh_does_not_record_the_hostname() -> None:
    """ホスト名は公開する記録に載せない。計測機の同一性は cpu / cores / mem_total で足りる。"""
    script = run_sh()
    assert "hostname" not in script, "tools/run.sh がホスト名を取得している"
    assert not re.search(r'^\s*echo\s+"host:', script, re.MULTILINE), (
        "tools/run.sh が env.txt に host: 行を書いている"
    )


def test_run_sh_records_what_was_measured() -> None:
    """タイムだけ残っても、何を走らせたか分からなければ記録にならない。"""
    script = run_sh()
    for field in REQUIRED_ENV_FIELDS:
        assert f'echo "{field}:' in script, f"env.txt から {field} が消えている"


def test_recorded_env_files_have_no_hostname() -> None:
    """results/ に置いた証拠にもホスト名を残さない。"""
    env_files = sorted(RESULTS_DIR.glob("*/env.txt"))
    assert env_files, "results/ に env.txt が無い"
    for path in env_files:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not line.startswith("host:"), f"{path}:{lineno} にホスト名が残っている"


def test_run_sh_samples_the_hardware_alongside_the_measurement() -> None:
    """同一コードでもタイムが 3% ばらついた (記録 #4)。原因が分かるまで材料を残す。

    結論には使わない。数本ぶん溜まってから見るためのもの。
    """
    script = run_sh()
    assert "scaling_cur_freq" in script, "CPU 周波数を取っていない"
    assert "thermal_zone" in script, "温度を取っていない"
    assert "package_throttle_count" in script, "サーマルスロットル回数を取っていない"
    assert "> freq.log" in script, "freq.log に書いていない"

    # ビルドは含めず、計測している区間だけを見る
    assert script.index("=== 計測開始") < script.index("sample_hw_loop >> freq.log")
    # 1本目を同期で書く (短い実行でヘッダだけにならないように)
    assert script.index("{ sample_hw_header; sample_hw_row; }") < script.index("sample_hw_loop >>")
    # 途中で落ちてもサンプラを残さない
    assert "trap stop_sampler EXIT" in script
    assert 'kill "$SAMPLER_PID" 2>/dev/null || true' in script


def test_run_sh_records_vmstat_around_the_measurement() -> None:
    """計測の直前と直後に /proc/vmstat を1行ずつ残す (記録 #21 から)。

    巨大ページが付いたか (`thp_fault_fallback`)、そのためのコンパクション、NUMA の自動移動を
    本走でも読めるようにする。門番は `numactl` で固定するが、本走は固定しないので、
    門番に無い振れが出うる。
    """
    script = run_sh()
    for key in ("thp_fault_alloc", "thp_fault_fallback", "compact_stall", "pgmigrate_fail"):
        assert key in script, f"vmstat の {key} を取っていない"
    measure = script.index('/usr/bin/time -v bash -c "$RUN_CMD"')
    assert script.index("vmstat_row before") < measure < script.index("vmstat_row after"), (
        "vmstat を計測の前後で取っていない"
    )


def test_implementation_is_selectable_and_defaults_to_baseline() -> None:
    """第1引数で実装ディレクトリを選ぶ。無指定はベースライン。"""
    assert 'IMPL_ARG="${1:-baseline}"' in run_sh()


def test_baseline_has_no_impl_env() -> None:
    """baseline/ は凍結されているので設定ファイルを置けない。既定値がそのまま効くこと。"""
    assert not (BASELINE_DIR / "impl.env").exists(), (
        "baseline/ に impl.env がある。baseline/ は2021年のまま置く場所で、"
        "ハーネス用のファイルを足してはいけない"
    )


def test_defaults_match_the_baseline_layout() -> None:
    """impl.env を持てない baseline/ が既定値だけで動くこと。"""
    assert "animal_shogi.so" in shell_default("BUILD_CMD")
    assert (BASELINE_DIR / "Makefile").read_text(encoding="utf-8").startswith("animal_shogi.so:")

    assert "animal_shogi.py" in shell_default("RUN_CMD")
    assert (BASELINE_DIR / "animal_shogi.py").exists()


def test_default_main_log_matches_what_the_baseline_writes() -> None:
    """既定の MAIN_LOG が、ベースラインの LOG_PATH_MAIN と食い違っていないこと。"""
    source = (BASELINE_DIR / "animal_shogi.py").read_text(encoding="utf-8")
    m = re.search(r'^LOG_PATH_MAIN\s*=\s*"([^"]+)"', source, re.MULTILINE)
    assert m, "baseline/animal_shogi.py から LOG_PATH_MAIN を読めない"
    assert m.group(1).removeprefix("./") == shell_default("MAIN_LOG")


def test_impl_env_is_not_copied_into_the_work_dir() -> None:
    """impl.env はハーネスの設定であって実装の一部ではない。impl_sha256 にも入れない。"""
    script = run_sh()
    assert 'rm -f "$WORK/impl.env"' in script
    assert "! -name impl.env" in script


def test_analysis_exit_code_is_not_ignored() -> None:
    """検証が PASS でも、解析プロセスが落ちていたら成功にしない。"""
    script = run_sh()
    assert 'if [ "$RC" -ne 0 ]; then' in script, "解析の終了コードを見ていない"
    assert 'exit "$RC"' in script, "解析の終了コードを呼び出し元へ返していない"


def test_verify_failure_does_not_abort_the_script() -> None:
    """set -e の下で検証を直接呼ぶと、落ちた瞬間に打ち切られて成果物の場所が出なくなる。"""
    assert "|| VERDICT=$?" in run_sh()


def test_every_implementation_is_runnable() -> None:
    """impl/*/ は impl.env を持つか、ベースラインと同じ構成であること。

    どちらでもないディレクトリはハーネスが走らせられない。
    """
    impl_root = ROOT / "impl"
    if not impl_root.is_dir():
        return
    for d in sorted(p for p in impl_root.iterdir() if p.is_dir()):
        if (d / "impl.env").exists():
            continue
        for name in ("animal_shogi.py", "Makefile"):
            assert (d / name).exists(), (
                f"{d.relative_to(ROOT)} に impl.env も {name} も無い。"
                f"ハーネスの既定値で走らせられない"
            )
