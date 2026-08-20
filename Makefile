# ATA 常用命令。快速启动: make serve
LEDGER ?= $${HOME}/.ata/dev.sqlite

.PHONY: help serve test seed attach-cue

help: ## 列出可用命令
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "%-10s %s\n", $$1, $$2}'

serve: ## 启动 Atatrace（127.0.0.1:8787，自动挂载已装 agent 的会话目录）
	./scripts/serve-dev.sh

test: ## 跑全量单元测试
	python3 -m unittest discover -s tests -v

seed: ## 灌入合成演示数据（pi-compact / droid-missing / pi-long），可与 serve 共用账本
	python3 -m ata seed --ledger $(LEDGER)

attach-cue: ## 安装 Cue 的 Pi Trace extension
	./scripts/attach-cue-pi.sh
