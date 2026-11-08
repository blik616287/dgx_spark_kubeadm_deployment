#!/bin/sh
# Manage the zrok access frontend that puts dgx10's SSH on a local port.
#
# The share token is the *share* token produced on dgx10 by
#   zrok reserve private localhost:22 --backend-mode tcpTunnel --json-output
# It is not the environment enable token. An enable token makes this machine a
# member of the zrok environment; a share token names one reserved share and is
# what `zrok access private` consumes.
#
# Usage:
#   scripts/tunnel.sh start <share-token>
#   scripts/tunnel.sh stop
#   scripts/tunnel.sh status
set -eu

PORT="${DGX_SSH_PORT:-2222}"
STATE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/dgx10-ansible"
PID_FILE="$STATE_DIR/tunnel.pid"
LOG_FILE="$STATE_DIR/tunnel.log"

usage() {
  echo "usage: $0 {start <share-token>|stop|status}" >&2
  exit 2
}

case "${1:-}" in
  start)
    token="${2:-${DGX_SHARE_TOKEN:-}}"
    [ -n "$token" ] || usage
    command -v zrok >/dev/null 2>&1 || {
      echo "zrok not found on PATH; install it first (see README)" >&2
      exit 1
    }

    mkdir -p "$STATE_DIR"
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "tunnel already running (pid $(cat "$PID_FILE")) on 127.0.0.1:${PORT}"
      exit 0
    fi

    zrok access private --headless --bind "127.0.0.1:${PORT}" "$token" \
      >"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"

    # zrok establishes the tunnel asynchronously; give it a moment, then check
    # that the process survived rather than claiming success immediately.
    sleep 3
    if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "tunnel up on 127.0.0.1:${PORT} (pid $(cat "$PID_FILE"))"
      echo "log: $LOG_FILE"
    else
      echo "tunnel failed to start; last lines of $LOG_FILE:" >&2
      tail -n 20 "$LOG_FILE" >&2 || true
      rm -f "$PID_FILE"
      exit 1
    fi
    ;;

  stop)
    if [ -f "$PID_FILE" ]; then
      pid="$(cat "$PID_FILE")"
      kill "$pid" 2>/dev/null || true
      rm -f "$PID_FILE"
      echo "tunnel stopped (pid $pid)"
    else
      echo "no tunnel pid file at $PID_FILE"
    fi
    ;;

  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "running (pid $(cat "$PID_FILE")) on 127.0.0.1:${PORT}"
    else
      echo "stopped"
    fi
    ;;

  *)
    usage
    ;;
esac
