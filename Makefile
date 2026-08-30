SHELL := bash
.DEFAULT_GOAL := help
.PHONY: help up down down-v infra-up infra-down services-up services-down restart ps logs \
        install local-up local-down local-logs local-backend local-runner local-frontend

COMPOSE := docker compose

INFRA_SERVICES := postgres redis minio minio-init
APP_SERVICES   := backend-api agent-runner frontend

PID_DIR := .make-pids
LOG_DIR := .make-logs

help: ## 显示本帮助信息
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ------------------------------------------------------------------
# 全量容器编排：一键启停所有 docker compose 服务
# ------------------------------------------------------------------

up: ## 一键启动所有服务（容器：infra + backend-api + agent-runner + frontend）
	$(COMPOSE) up -d --build
	@echo "全部服务已在容器中启动，使用 'make ps' 查看状态，'make logs' 查看日志"

down: ## 一键关闭所有 docker 启动的服务（保留数据卷）
	$(COMPOSE) down
	@echo "已停止并移除所有容器（数据卷保留）"

down-v: ## 关闭所有 docker 服务并删除数据卷（会清空数据库/redis/minio 数据，谨慎使用）
	$(COMPOSE) down -v
	@echo "已停止并移除所有容器及数据卷"

restart: down up ## 重启所有 docker 服务

ps: ## 查看 docker compose 服务状态
	$(COMPOSE) ps

logs: ## 跟随查看所有 docker compose 服务日志
	$(COMPOSE) logs -f

# ------------------------------------------------------------------
# 仅基础设施（容器）：postgres / redis / minio
# ------------------------------------------------------------------

infra-up: ## 仅启动基础设施容器（postgres/redis/minio）
	$(COMPOSE) up -d $(INFRA_SERVICES)
	@echo "基础设施服务已启动：$(INFRA_SERVICES)"

infra-down: ## 停止基础设施容器（不删除容器，数据卷保留）
	$(COMPOSE) stop $(INFRA_SERVICES)
	@echo "基础设施服务已停止"

# ------------------------------------------------------------------
# 仅业务服务（容器）：backend-api / agent-runner / frontend
# 依赖 docker-compose.yml 中的 depends_on，会自动带起所需的基础设施
# ------------------------------------------------------------------

services-up: ## 仅在容器中启动业务服务（backend-api/agent-runner/frontend，自动带起依赖的基础设施）
	$(COMPOSE) up -d --build $(APP_SERVICES)
	@echo "业务服务已在容器中启动：$(APP_SERVICES)"

services-down: ## 停止容器中的业务服务（基础设施容器保留运行）
	$(COMPOSE) stop $(APP_SERVICES)

# ------------------------------------------------------------------
# 本地启动业务服务：基础设施仍走 docker，业务服务在宿主机本地进程运行
# 各服务目录下有自己的 .env（env_file=".env" 相对 cwd 加载），
# 这里在子 shell 里 source 对应目录的 .env 后再启动，保证端口/连接信息一致
# ------------------------------------------------------------------

install: ## 安装本地开发依赖（backend-api/agent-runner 用 uv，frontend 用 pnpm）
	cd backend-api && uv sync
	cd agent-runner && uv sync
	cd frontend && pnpm install

local-backend: ## 本地前台启动 backend-api（单独占用一个终端，Ctrl+C 停止）
	@cd backend-api && set -a && . ./.env && set +a && \
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port "$${BACKEND_API_PORT:-8080}"

# local-runner: Windows 下 celery 默认 prefork pool 依赖 billiard 的 spawn 子进程句柄复制，从 Git
# Bash/Cygwin 里启动时会报 WinError 5/87；--pool=solo 单进程运行任务规避这个问题。生产环境（Linux
# 容器，见 agent-runner/entrypoint.sh）不受影响，不需要同样处理
local-runner: ## 本地前台启动 agent-runner（celery worker + http server，Ctrl+C 停止）
	@cd agent-runner && set -a && . ./.env && set +a && \
	trap 'kill 0' EXIT INT TERM; \
	uv run celery -A app.worker.celery_app worker --loglevel=info --pool=solo & \
	uv run uvicorn app.server.main:app --reload --host 0.0.0.0 --port "$${AGENT_RUNNER_HTTP_PORT:-8100}" & \
	wait

local-frontend: ## 本地前台启动 frontend（vite dev server，Ctrl+C 停止）
	cd frontend && pnpm dev

local-up: infra-up ## 一键本地启动全部业务服务（后台进程，基础设施仍用 docker），日志见 .make-logs/
	@mkdir -p $(PID_DIR) $(LOG_DIR)
	@echo "启动 backend-api（后台）..."
	@bash -c 'cd backend-api && set -a && . ./.env && set +a && \
		nohup uv run uvicorn app.main:app --host 0.0.0.0 --port "$${BACKEND_API_PORT:-8080}" \
		> ../$(LOG_DIR)/backend-api.log 2>&1 & echo $$! > ../$(PID_DIR)/backend-api.pid'
	@echo "启动 agent-runner worker（后台）..."
	@bash -c 'cd agent-runner && set -a && . ./.env && set +a && \
		nohup uv run celery -A app.worker.celery_app worker --loglevel=info \
		> ../$(LOG_DIR)/agent-runner-worker.log 2>&1 & echo $$! > ../$(PID_DIR)/agent-runner-worker.pid'
	@echo "启动 agent-runner http server（后台）..."
	@bash -c 'cd agent-runner && set -a && . ./.env && set +a && \
		nohup uv run uvicorn app.server.main:app --host 0.0.0.0 --port "$${AGENT_RUNNER_HTTP_PORT:-8100}" \
		> ../$(LOG_DIR)/agent-runner-server.log 2>&1 & echo $$! > ../$(PID_DIR)/agent-runner-server.pid'
	@echo "启动 frontend（后台）..."
	@bash -c 'cd frontend && nohup pnpm dev > ../$(LOG_DIR)/frontend.log 2>&1 & echo $$! > ../$(PID_DIR)/frontend.pid'
	@echo "本地业务服务已在后台启动：backend-api / agent-runner(worker+server) / frontend"
	@echo "日志：$(LOG_DIR)/*.log（'make local-logs' 跟随查看），停止：'make local-down'"

local-down: ## 停止 local-up 启动的所有本地后台进程
	@if [ ! -d "$(PID_DIR)" ]; then echo "没有正在运行的本地进程"; exit 0; fi
	@for f in $(PID_DIR)/*.pid; do \
		[ -f "$$f" ] || continue; \
		pid=$$(cat "$$f"); \
		name=$$(basename "$$f" .pid); \
		if kill -0 "$$pid" 2>/dev/null; then \
			kill "$$pid" 2>/dev/null && echo "已停止 $$name (pid $$pid)"; \
		else \
			echo "$$name (pid $$pid) 已不在运行"; \
		fi; \
		rm -f "$$f"; \
	done

local-logs: ## 跟随查看 local-up 启动的本地服务日志
	@tail -f $(LOG_DIR)/*.log
