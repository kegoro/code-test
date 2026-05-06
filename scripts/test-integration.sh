#!/usr/bin/env bash
# Footprint 端對端整合測試
#
# 流程：
#   1. 背景啟動 uvicorn
#   2. 等待 /health 200（最多 10 秒）
#   3. 驗證 /api/footprint/history?bars=5
#   4. 用 websocat 接 3 筆 ws/footprint 訊息並驗證欄位
#   5. 關閉後端
#
# 依賴：python -m uvicorn, curl, jq, websocat
#   websocat 安裝：cargo install websocat 或 brew install websocat

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="127.0.0.1"
PORT="8765"
BASE="http://${HOST}:${PORT}"
WS="ws://${HOST}:${PORT}/ws/footprint"
LOG="${ROOT}/.integration-uvicorn.log"

PASS=0
FAIL=0

ok()   { echo "  [PASS] $1"; PASS=$((PASS+1)); }
bad()  { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }

require() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[ERROR] 缺少必要工具: $1"
    exit 2
  fi
}

require curl
require jq
require python
require websocat

echo "==> 啟動 uvicorn 後端 ($HOST:$PORT)..."
cd "$ROOT"
python -m uvicorn backend.main:app --host "$HOST" --port "$PORT" --log-level warning >"$LOG" 2>&1 &
UVICORN_PID=$!

cleanup() {
  if kill -0 "$UVICORN_PID" 2>/dev/null; then
    kill "$UVICORN_PID" 2>/dev/null || true
    wait "$UVICORN_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "==> 等待 /health (最多 10s)..."
READY=0
for _ in $(seq 1 20); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health" || true)"
  if [ "$CODE" = "200" ]; then
    READY=1
    break
  fi
  sleep 0.5
done

if [ "$READY" -ne 1 ]; then
  bad "/health 未在 10 秒內回 200"
  echo "---- uvicorn log ----"
  tail -n 50 "$LOG" || true
  echo "==> 結果: PASS=$PASS FAIL=$FAIL"
  exit 1
fi
ok "/health 200"

echo "==> 等待聚合器累積資料 (3s)..."
sleep 3

echo "==> 驗證 /api/footprint/history?bars=5"
HIST_JSON="$(curl -s "$BASE/api/footprint/history?bars=5" || true)"
HIST_LEN="$(echo "$HIST_JSON" | jq '.bars | length' 2>/dev/null || echo 0)"
if [ "$HIST_LEN" -gt 0 ] 2>/dev/null; then
  ok "history bars 長度 = $HIST_LEN"
else
  bad "history 回傳異常: $HIST_JSON"
fi

echo "==> 從 WebSocket 收 3 筆訊息..."
WS_OUT="$(websocat --no-close -n1 -B 65536 --max-messages 3 "$WS" 2>/dev/null || true)"

if [ -z "$WS_OUT" ]; then
  bad "WebSocket 未收到任何訊息"
else
  COUNT=0
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    COUNT=$((COUNT+1))
    TYPE="$(echo "$line" | jq -r '.type // empty' 2>/dev/null)"
    case "$TYPE" in
      snapshot)
        FIRST="$(echo "$line" | jq '.data[0] // empty' 2>/dev/null)"
        if [ -n "$FIRST" ] && [ "$FIRST" != "null" ]; then
          if echo "$FIRST" | jq -e '.timestamp and .levels and (.totalDelta // 0 | type == "number")' >/dev/null 2>&1; then
            ok "msg#$COUNT snapshot 欄位完整"
          else
            bad "msg#$COUNT snapshot 缺欄位"
          fi
        else
          ok "msg#$COUNT snapshot (空陣列亦可)"
        fi
        ;;
      bar_update|bar_close)
        if echo "$line" | jq -e '.data.timestamp and .data.levels and (.data.totalDelta | type == "number")' >/dev/null 2>&1; then
          ok "msg#$COUNT $TYPE 欄位完整"
        else
          bad "msg#$COUNT $TYPE 缺 timestamp/levels/totalDelta"
        fi
        ;;
      *)
        bad "msg#$COUNT 未知 type=$TYPE"
        ;;
    esac
  done <<EOF
$WS_OUT
EOF

  if [ "$COUNT" -lt 3 ]; then
    bad "僅收到 $COUNT 筆訊息（期望 3）"
  fi
fi

echo "==> 關閉後端"
cleanup

echo
echo "================================================="
echo " 結果: PASS=$PASS  FAIL=$FAIL"
echo "================================================="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
