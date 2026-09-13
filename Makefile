# どうぶつしょうぎ完全解析 RTA — 開発ハーネス
#
#   make setup    初回セットアップ (.venv 作成 + 開発ツール導入)
#   make check    CI と同じ一式 (lint + type + test)
#   make measure  ベースラインの計測 (数時間かかる)
#
# 現状は Python + Bash だが、改善の梯子の先には C / Rust がある。
# 言語が増えたら lint-<lang> / test-<lang> を足して check に繋ぐこと。

UV ?= uv
LABEL ?= baseline

.DEFAULT_GOAL := help

.PHONY: help setup fmt lint lint-sh type test cov check hooks measure clean

help:  ## このヘルプを出す
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup:  ## .venv を作って開発ツールを入れる
	$(UV) sync

fmt:  ## コードを整形する (ruff format)
	$(UV) run ruff format .

lint:  ## Python を lint する (ruff check + format --check)
	$(UV) run ruff check .
	$(UV) run ruff format --check .

lint-sh:  ## シェルスクリプトを lint する (shellcheck)
	$(UV) run shellcheck tools/run.sh

type:  ## 型検査する (mypy)
	$(UV) run mypy

test:  ## テストを走らせる (pytest)
	$(UV) run pytest

cov:  ## カバレッジ付きでテストし HTML レポートも出す
	$(UV) run pytest --cov --cov-report=term-missing --cov-report=html
	@echo "HTML レポート: htmlcov/index.html"

check: lint lint-sh type test  ## CI と同じ一式を回す

hooks:  ## pre-commit を git フックとして仕掛ける
	$(UV) run pre-commit install

measure:  ## ベースラインを計測する (数時間 / 要 40GB 空き)
	tools/run.sh $(LABEL)

clean:  ## キャッシュ類を消す (.venv と runs/ は消さない)
	rm -rf .ruff_cache .mypy_cache .pytest_cache htmlcov .coverage
	find . -path ./.venv -prune -o -name __pycache__ -type d -print0 | xargs -0 -r rm -rf
