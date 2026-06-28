"""第一刀 watcher — 每日盤後掃觀察名單,出現「整理後第一支帶量長紅K」就通知。

去重:同一支紅K(red_date)只推一次,不會每天重推同一個訊號。
觀察名單:`data/blade1_watchlist.json`(可手動編輯 {代號:名稱})。
排程由 smc_bot 每日盤後呼叫 scan();手動指令呼叫 run_report()。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.diamond_blade1 import _analyze

logger = logging.getLogger("blade1_watcher")

_ROOT = Path(__file__).resolve().parent.parent
WL_PATH = _ROOT / "data" / "blade1_watchlist.json"
STATE_PATH = _ROOT / "data" / "blade1_state.json"


def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def load_watchlist() -> dict[str, str]:
    return _load_json(WL_PATH, {})


def _fmt_alert(r) -> str:
    return (
        f"🚨 第一刀訊號:{r.code} {r.name} 收{r.last:.0f}\n"
        f"  {r.red_date} 帶量長紅K(實體+{r.body_pct:.1f}%、量{r.vol_ratio:.1f}倍"
        f"{'、突破盤整' if r.breakout else ''})\n"
        f"  主力成本≈{r.red_low:.0f}~{r.red_close:.0f}\n"
        f"  進場≈{r.entry:.0f} 停損{r.stop:.0f} 目標{r.target:.0f}(賺賠比{r.rr:.1f})\n"
        f"  {r.status}"
    )


def scan(watchlist: dict[str, str] | None = None) -> list[str]:
    """掃名單,回「新出現的第一刀進場訊號」訊息(已去重)。排程用:沒新訊號回空清單。"""
    wl = watchlist if watchlist is not None else load_watchlist()
    state = _load_json(STATE_PATH, {})  # {code: 已推過的 red_date}
    msgs: list[str] = []
    changed = False
    for code, name in wl.items():
        try:
            r = _analyze(code, name)
        except Exception as exc:
            logger.warning("blade1 scan %s failed: %s", code, exc)
            continue
        if r.ok and r.red_date and "可考慮進場" in r.status:
            if state.get(code) != r.red_date:  # 這支紅K還沒推過
                msgs.append(_fmt_alert(r))
                state[code] = r.red_date
                changed = True
    if changed:
        _save_json(STATE_PATH, state)
    return msgs


def list_signals(watchlist: dict[str, str] | None = None) -> list[str]:
    """列「現在所有有進場訊號」的(不去重、不寫 state),供手動查看。"""
    wl = watchlist if watchlist is not None else load_watchlist()
    out: list[str] = []
    for code, name in wl.items():
        try:
            r = _analyze(code, name)
        except Exception:
            continue
        if r.ok and r.red_date and "可考慮進場" in r.status:
            out.append(_fmt_alert(r))
    return out


def run_report() -> str:
    """手動指令用:列現在所有有進場訊號的(不影響排程去重)。"""
    wl = load_watchlist()
    if not wl:
        return "🗡️ 第一刀 watcher:觀察名單是空的(編輯 data/blade1_watchlist.json)"
    sigs = list_signals(wl)
    if sigs:
        return f"🗡️ 第一刀 watcher（{len(wl)} 檔觀察）— 現有進場訊號:\n\n" + "\n\n".join(sigs)
    return f"🗡️ 第一刀 watcher:{len(wl)} 檔觀察中,目前無進場訊號(都在等回檔)"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
    print(run_report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
