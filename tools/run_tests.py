"""テスト一式を、`.so` を読み込むテストのファイルごとに別のプロセスで回す。

`ctypes` で読み込んだ `.so` はプロセスが終わるまで外れず、#34 から C の側は番号の範囲全体の
配列 (発見済みの表 約 107 MB、`g_prep`・`g_dtm` 各 約 855 MB) を確保して埋めるので、
版のテストを1つのプロセスで続けて回すと、版ごとに約 3 GB ずつ積み上がる (#39 で 16 GB の
CI のランナーを超えて止まった。docs/lessons.md)。そこで:

- `.so` を読み込むテストのファイル (本文に ctypes / load_impl などが出てくるもの) は
  1ファイル1プロセス
- そのほかのテストのファイルはまとめて1プロセス
- 順に1本ずつ回す (同時に回すと足し算になる)
- プロセスごとのピークの RSS (`wait4` の `ru_maxrss`) を測り、上限 (既定 8 GiB) を超えたら落とす。
  次に版のテストを足して積み上がったときに、黙って CI のランナーを使い切らないため
- カバレッジは各プロセスで `--cov-append` して、最後に1回だけ `coverage report`
  (`fail_under` はそこで見る)
- 集めたテストと通ったテストの数は、各プロセスの JUnit XML を足して出す

使い方:
    python3 tools/run_tests.py [--max-rss-gib 8] [<テストのパス>…] [-- pytest の引数…]
パスを省くと tests/ の全部。`make test` / `make check` / CI と、コミットのフック
(`tools/select_tests.py --run`) がこれを通る。
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
# `.so` を読み込むテストの目印 (conftest の読み込みの道具と ctypes)
LOADS_SO = re.compile(r"\b(ctypes|CDLL|load_impl|impl_library|shared_library)\b")
MAX_RSS_GIB = 8.0  # GitHub の ubuntu-latest (16 GB) の半分
COV_ARGS = ("--cov", "--cov-append", "--cov-report=", "--cov-fail-under=0")


@dataclass
class Result:
    """1プロセスの結果。"""

    paths: list[str]
    code: int
    rss_kib: int
    tests: int = 0
    failed: int = 0
    skipped: int = 0


def loads_so(path: pathlib.Path) -> bool:
    return bool(LOADS_SO.search(path.read_text(encoding="utf-8")))


def expand(paths: list[str], root: pathlib.Path) -> list[str]:
    """パスをテストのファイル (や `ファイル::テスト`) の並びにする。
    ディレクトリはその中の test_*.py。"""
    out: list[str] = []
    for p in paths:
        q = root / p.split("::", 1)[0]
        if q.is_dir():
            out += [str(f.relative_to(root)) for f in sorted(q.glob("test_*.py"))]
        else:
            out.append(p)
    return out


def plan(paths: list[str], root: pathlib.Path) -> list[list[str]]:
    """プロセスの並び。`.so` を読み込むファイルは1つずつ、そのほかはまとめて先頭に1つ。"""
    light: list[str] = []
    heavy: dict[str, list[str]] = {}
    for p in expand(paths, root):
        f = p.split("::", 1)[0]
        if loads_so(root / f):
            heavy.setdefault(f, []).append(p)
        else:
            light.append(p)
    return ([light] if light else []) + list(heavy.values())


def counts(xml: pathlib.Path) -> tuple[int, int, int]:
    """JUnit XML の (テストの数, 失敗とエラーの数, 飛ばした数)。"""
    if not xml.exists():
        return 0, 0, 0
    root = ET.parse(xml).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    n = sum(int(s.get("tests", 0)) for s in suites)
    bad = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    skip = sum(int(s.get("skipped", 0)) for s in suites)
    return n, bad, skip


def run_one(paths: list[str], extra: list[str], xml: pathlib.Path, cwd: pathlib.Path) -> Result:
    """pytest を1プロセスで回し, 終了コードとピークの RSS を返す。"""
    cmd = [sys.executable, "-m", "pytest", f"--junitxml={xml}", *extra, *paths]
    proc = subprocess.Popen(cmd, cwd=cwd)
    _, status, usage = os.wait4(proc.pid, 0)
    proc.returncode = os.waitstatus_to_exitcode(status)
    return Result(paths, proc.returncode, usage.ru_maxrss, *counts(xml))


def run(
    paths: list[str], extra: list[str], max_rss_gib: float = MAX_RSS_GIB, cwd: pathlib.Path = ROOT
) -> int:
    """プロセスに分けて順に回す。どれかが落ちる・上限を超える・カバレッジが足りなければ 0 以外。"""
    cov = "--no-cov" not in extra
    groups = plan(paths, cwd)
    if cov:
        subprocess.run([sys.executable, "-m", "coverage", "erase"], cwd=cwd, check=True)
    results = []
    with tempfile.TemporaryDirectory() as t:
        for i, g in enumerate(groups):
            args = [*COV_ARGS, *extra] if cov else extra
            results.append(run_one(g, args, pathlib.Path(t) / f"{i}.xml", cwd))
    limit = int(max_rss_gib * 1024 * 1024)
    over = [r for r in results if r.rss_kib > limit]
    bad = [r for r in results if r.code != 0]
    code = 0
    if cov:
        code = subprocess.run([sys.executable, "-m", "coverage", "report"], cwd=cwd).returncode
    top = max(results, key=lambda r: r.rss_kib, default=None)
    print(
        f"run_tests: プロセス {len(results)} 本 / テスト {sum(r.tests for r in results)} 個"
        f" (失敗とエラー {sum(r.failed for r in results)},"
        f" 飛ばした {sum(r.skipped for r in results)})"
    )
    if top is not None:
        print(
            f"run_tests: プロセスごとのピークの RSS の最大 {top.rss_kib / 1024 / 1024:.2f} GiB"
            f" ({' '.join(top.paths) if len(top.paths) == 1 else f'{len(top.paths)} ファイル'})"
            f" / 上限 {max_rss_gib:g} GiB"
        )
    for r in over:
        print(
            f"run_tests: !!! ピークの RSS {r.rss_kib / 1024 / 1024:.2f} GiB が"
            f"上限 {max_rss_gib:g} GiB を超えた: {' '.join(r.paths)}",
            file=sys.stderr,
        )
    for r in bad:
        print(f"run_tests: !!! 終了コード {r.code}: {' '.join(r.paths)}", file=sys.stderr)
    if bad or over:
        return 1
    return code


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    extra: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1 :]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--max-rss-gib", type=float, default=MAX_RSS_GIB, help="プロセスごとのピークの RSS の上限"
    )
    ap.add_argument("paths", nargs="*", help="テストのパス (省くと tests/ の全部)")
    args = ap.parse_args(argv)
    return run(args.paths or ["tests"], extra, args.max_rss_gib)


if __name__ == "__main__":
    sys.exit(main())
