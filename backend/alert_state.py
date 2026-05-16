"""持久化警示去重狀態。

對應 LESSONS.md §2.7.6 P1：避免同一個警示（first_beat / db_approach）
重複推 telegram。state 寫 data/alert_state.json，bot 重啟也不會忘記。

API 設計：純函式 + frozen dataclass，無全域 mutable 狀態。
每次呼叫 should_push 都會去讀檔；mark_pushed 寫檔（原子寫入）。

key 慣例：
  first_beat:{symbol}:{date}            一天只推一次
  db_approach:{symbol}:{ob_id}:{date}   同一天同一 OB 只推一次
  aistockmap_brief:{date}:{slot}        morning / evening 各一次
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("alert-state")

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "alert_state.json"


@dataclass(frozen=True)
class AlertState:
    """key → ISO timestamp of last push。"""

    last_pushed: dict[str, str]


def load(path: Path = _DEFAULT_PATH) -> AlertState:
    """讀檔。檔案不存在回空 state。"""
    if not path.exists():
        return AlertState(last_pushed={})
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("alert_state read failed (%s) — treating as empty", exc)
        return AlertState(last_pushed={})
    return AlertState(last_pushed=dict(raw.get("last_pushed", {})))


def save(state: AlertState, path: Path = _DEFAULT_PATH) -> None:
    """原子寫入。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"last_pushed": state.last_pushed}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def should_push(
    key: str,
    *,
    within_minutes: int = 60,
    now: datetime | None = None,
    path: Path = _DEFAULT_PATH,
) -> bool:
    """判斷此 key 是否該推（過去 within_minutes 內推過則 False）。"""
    state = load(path)
    last_iso = state.last_pushed.get(key)
    if last_iso is None:
        return True
    try:
        last_ts = datetime.fromisoformat(last_iso)
    except ValueError:
        return True
    now = now or datetime.now()
    return (now - last_ts) >= timedelta(minutes=within_minutes)


def mark_pushed(
    key: str,
    *,
    now: datetime | None = None,
    path: Path = _DEFAULT_PATH,
) -> None:
    """標記 key 已推過。"""
    state = load(path)
    now = now or datetime.now()
    new_pushed = dict(state.last_pushed)
    new_pushed[key] = now.isoformat(timespec="seconds")
    save(AlertState(last_pushed=new_pushed), path)


def gc_old_keys(
    *,
    keep_within_days: int = 7,
    now: datetime | None = None,
    path: Path = _DEFAULT_PATH,
) -> int:
    """清掉超過 keep_within_days 沒推的 key（避免檔案無限長）。Returns 清掉的數量。"""
    state = load(path)
    now = now or datetime.now()
    cutoff = now - timedelta(days=keep_within_days)
    kept: dict[str, str] = {}
    for k, ts_iso in state.last_pushed.items():
        try:
            ts = datetime.fromisoformat(ts_iso)
        except ValueError:
            continue
        if ts >= cutoff:
            kept[k] = ts_iso
    n_dropped = len(state.last_pushed) - len(kept)
    if n_dropped > 0:
        save(AlertState(last_pushed=kept), path)
    return n_dropped
