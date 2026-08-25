#!/bin/bash
# ============================================================
# BabelDOC 后台管理脚本
# 用于在后台运行 babeldoc_translator.py (Gradio Web 服务)
# 使用方式: ./start.sh {start|stop|restart|status|logs}
# ============================================================

APP_NAME="BabelDOC"
APP_FILE="babeldoc_translator.py"
PID_FILE=".babeldoc.pid"
LOG_DIR="logs"
LOG_FILE="${LOG_DIR}/babeldoc.log"
PORT=7865
PYTHON="python3"

# 颜色样式
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 切换到项目根目录
cd "$(dirname "$0")" || exit 1

# ---------- 辅助函数 ----------
_check_python() {
    if ! command -v $PYTHON &>/dev/null; then
        echo -e "${RED}[错误] 未找到 $PYTHON，请先安装 Python 3${NC}"
        exit 1
    fi
}

_check_deps() {
    if ! $PYTHON -c "import gradio" 2>/dev/null; then
        echo -e "${YELLOW}[提示] 缺少依赖，正在安装...${NC}"
        pip install -r requirements.txt
    fi
}

_get_pid() {
    if [ -f "$PID_FILE" ]; then
        cat "$PID_FILE"
    else
        echo ""
    fi
}

_is_running() {
    local pid
    pid=$(_get_pid)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    return 1
}

_check_port() {
    if command -v ss &>/dev/null; then
        if ss -tlnp | grep -q ":$PORT "; then
            return 0
        fi
    elif command -v lsof &>/dev/null; then
        if lsof -i :$PORT -P -n 2>/dev/null | grep -q LISTEN; then
            return 0
        fi
    fi
    return 1
}

# ---------- 子命令 ----------
start() {
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  启动 ${APP_NAME} 服务${NC}"
    echo -e "${CYAN}========================================${NC}"

    _check_python

    if _is_running; then
        local pid
        pid=$(_get_pid)
        echo -e "${YELLOW}[!] ${APP_NAME} 已在运行中 (PID: $pid)${NC}"
        echo -e "    如需重启请运行: ${GREEN}$0 restart${NC}"
        exit 0
    fi

    # 检查端口占用
    if _check_port; then
        echo -e "${YELLOW}[!] 端口 $PORT 已被占用，请检查是否有其他实例在运行${NC}"
        echo -e "    ${GREEN}lsof -i :$PORT${NC}"
    fi

    _check_deps

    # 创建日志目录
    mkdir -p "$LOG_DIR"

    # 后台启动
    echo -e "[*] 启动命令: ${PYTHON} ${APP_FILE}"
    echo -e "[*] 日志文件: ${LOG_FILE}"
    echo -e "[*] 访问地址: ${GREEN}http://localhost:${PORT}${NC}"
    echo ""

    nohup $PYTHON "$APP_FILE" >> "$LOG_FILE" 2>&1 &
    local pid=$!
    echo $pid > "$PID_FILE"

    # 等待几秒检查是否启动成功
    sleep 2
    if kill -0 $pid 2>/dev/null; then
        echo -e "${GREEN}[✓] ${APP_NAME} 已成功启动 (PID: $pid)${NC}"
        echo -e "${GREEN}[✓] 访问地址: http://localhost:${PORT}${NC}"
        echo -e "${GREEN}[✓] 查看日志: $0 logs${NC}"
    else
        echo -e "${RED}[✗] ${APP_NAME} 启动失败，请检查日志:${NC}"
        echo -e "    ${GREEN}tail -50 ${LOG_FILE}${NC}"
        rm -f "$PID_FILE"
        exit 1
    fi
}

stop() {
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  停止 ${APP_NAME} 服务${NC}"
    echo -e "${CYAN}========================================${NC}"

    local pid
    pid=$(_get_pid)

    if [ -z "$pid" ]; then
        echo -e "${YELLOW}[!] 未找到 PID 文件，尝试通过端口查找...${NC}"
        # 尝试通过端口杀进程
        local pids
        pids=$(lsof -ti :$PORT 2>/dev/null)
        if [ -n "$pids" ]; then
            echo -e "[*] 找到进程: $pids"
            kill $pids 2>/dev/null
            echo -e "${GREEN}[✓] 已停止${NC}"
        else
            echo -e "${YELLOW}[!] 没有正在运行的 ${APP_NAME} 进程${NC}"
        fi
        rm -f "$PID_FILE"
        return
    fi

    if kill -0 $pid 2>/dev/null; then
        echo -e "[*] 正在停止进程 (PID: $pid)..."
        kill $pid 2>/dev/null

        # 等待进程退出
        for i in $(seq 1 10); do
            if ! kill -0 $pid 2>/dev/null; then
                break
            fi
            sleep 0.5
        done

        # 强制终止
        if kill -0 $pid 2>/dev/null; then
            echo -e "[*] 强制终止 (SIGKILL)..."
            kill -9 $pid 2>/dev/null
        fi

        echo -e "${GREEN}[✓] ${APP_NAME} 已停止${NC}"
    else
        echo -e "${YELLOW}[!] 进程 (PID: $pid) 已不存在${NC}"
    fi

    rm -f "$PID_FILE"
}

restart() {
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  重启 ${APP_NAME} 服务${NC}"
    echo -e "${CYAN}========================================${NC}"
    stop
    echo ""
    start
}

status() {
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  ${APP_NAME} 服务状态${NC}"
    echo -e "${CYAN}========================================${NC}"

    local pid
    pid=$(_get_pid)

    if _is_running; then
        # 获取更多进程信息
        local run_time cmd mem
        run_time=$(ps -o etime= -p "$pid" 2>/dev/null | xargs)
        cmd=$(ps -o args= -p "$pid" 2>/dev/null)
        mem=$(ps -o rss= -p "$pid" 2>/dev/null | xargs)
        [ -n "$mem" ] && mem="$((mem / 1024)) MB"

        echo -e "  状态:  ${GREEN}运行中${NC}"
        echo -e "  PID:   $pid"
        echo -e "  运行:  ${run_time:-N/A}"
        echo -e "  内存:  ${mem:-N/A}"
        echo -e "  端口:  $PORT"
        echo -e "  命令:  ${cmd:-N/A}"
        echo ""
        echo -e "  访问:  ${GREEN}http://localhost:${PORT}${NC}"
        echo -e "  日志:  ${GREEN}$0 logs${NC}"
    else
        echo -e "  状态:  ${RED}未运行${NC}"
        if [ -n "$pid" ]; then
            echo -e "  PID 文件存在 (PID: $pid) 但进程已不存在"
            echo -e "  可运行 ${GREEN}$0 stop${NC} 清理"
        fi
        if _check_port; then
            echo -e "  端口 $PORT 被占用（可能是其他程序）"
        fi
    fi
}

logs() {
    if [ ! -f "$LOG_FILE" ]; then
        echo -e "${YELLOW}[!] 日志文件不存在: ${LOG_FILE}${NC}"
        echo "  服务还未启动过，或日志已被清理"
        exit 1
    fi

    echo -e "${CYAN}实时日志 (Ctrl+C 退出)${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo ""
    tail -f "$LOG_FILE"
}

# ---------- 主入口 ----------
case "${1:-help}" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    *)
        echo -e "${CYAN}========================================${NC}"
        echo -e "${CYAN}  BabelDOC 后台管理脚本${NC}"
        echo -e "${CYAN}========================================${NC}"
        echo ""
        echo -e "  用法: ${GREEN}$0 {command}${NC}"
        echo ""
        echo -e "  命令:"
        echo -e "    ${GREEN}start${NC}     启动服务（后台运行）"
        echo -e "    ${GREEN}stop${NC}      停止服务"
        echo -e "    ${GREEN}restart${NC}   重启服务"
        echo -e "    ${GREEN}status${NC}    查看服务状态"
        echo -e "    ${GREEN}logs${NC}      实时查看日志"
        echo ""
        echo -e "  示例:"
        echo -e "    ${GREEN}$0 start${NC}     # 启动"
        echo -e "    ${GREEN}$0 status${NC}    # 查看状态"
        echo -e "    ${GREEN}$0 logs${NC}      # 看日志"
        echo ""
        ;;
esac
