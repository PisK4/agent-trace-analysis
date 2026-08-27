# ATA 常用命令。快速启动: make serve
LEDGER ?= $${HOME}/.ata/dev.sqlite
PORT ?= 17877
PROXY_PORT ?= 17878
PROXY_UPSTREAM ?= http://127.0.0.1:31415

.PHONY: help serve serve-no-proxy test seed attach-cue

help: ## 列出可用命令
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "%-10s %s\n", $$1, $$2}'

serve: ## 启动 Atatrace + 代理采集通道（17877 + 17878）
	ATA_PORT=$(PORT) ATA_PROXY_PORT=$(PROXY_PORT) ATA_PROXY_UPSTREAM=$(PROXY_UPSTREAM) \
		./scripts/serve-dev.sh

serve-no-proxy: ## 启动 Atatrace 不开代理（仅 17877）
	ATA_PORT=$(PORT) ATA_PROXY_PORT=0 ./scripts/serve-dev.sh

test: ## 跑全量单元测试
	python3 -m unittest discover -s tests -v

seed: ## 灌入合成演示数据（pi-compact / droid-missing / pi-long），可与 serve 共用账本
	python3 -m ata seed --ledger $(LEDGER)

attach-cue: ## 安装 Cue 的 Pi Trace extension
	./scripts/attach-cue-pi.sh
