"""當沖觀察清單持久化模組。

對應 LESSONS.md §2.7 當沖策略：
- 昨晚 / 盤前：使用者看 aistockmap AI 分析後手動把股號加進 watchlist
- 盤中：SMC scanner 只掃 watchlist 標的（不全市場）+ 隔日沖警告針對 watchlist

純函式 + frozen dataclass，沒有全域狀態，每次呼叫都重讀檔案以支援多 process。
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("watchlist")

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "day_trade_watchlist.json"


@dataclass(frozen=True)
class WatchlistEntry:
    """一檔 watchlist 標的。"""

    symbol: str
    note: str = ""
    added_at: str = ""

    @staticmethod
    def new(symbol: str, note: str = "") -> "WatchlistEntry":
        return WatchlistEntry(
            symbol=symbol.strip(),
            note=note.strip(),
            added_at=datetime.now().isoformat(timespec="seconds"),
        )


@dataclass(frozen=True)
class Watchlist:
    """全份 watchlist 快照（檔案內容的 in-memory 表示）。"""

    updated_at: str
    entries: tuple[WatchlistEntry, ...]

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(e.symbol for e in self.entries)

    def has(self, symbol: str) -> bool:
        return symbol in self.symbols


def load(path: Path = _DEFAULT_PATH) -> Watchlist:
    """讀檔。檔案不存在回空 Watchlist。"""
    if not path.exists():
        return Watchlist(updated_at="", entries=())
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = tuple(
        WatchlistEntry(
            symbol=e["symbol"],
            note=e.get("note", ""),
            added_at=e.get("added_at", ""),
        )
        for e in raw.get("entries", [])
    )
    return Watchlist(updated_at=raw.get("updated_at", ""), entries=entries)


def save(wl: Watchlist, path: Path = _DEFAULT_PATH) -> None:
    """寫檔。原子寫入（先寫 tmp 再 rename）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": wl.updated_at,
        "entries": [asdict(e) for e in wl.entries],
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    logger.info("watchlist saved: %d symbols → %s", len(wl.entries), path.name)


def add(
    symbols: Iterable[str], note: str = "", path: Path = _DEFAULT_PATH
) -> tuple[Watchlist, tuple[str, ...]]:
    """加入 symbols（去重，已存在的不會重複加）。

    內部會先用 parse_symbols_arg 拆分（支援逗號/空白），呼叫者不必預先 split。
    Returns (新 Watchlist, 真正新加的 symbol list)。
    """
    wl = load(path)
    existing = set(wl.symbols)
    new_entries = list(wl.entries)
    added: list[str] = []
    for s in parse_symbols_arg(symbols):
        if s in existing:
            continue
        new_entries.append(WatchlistEntry.new(s, note=note))
        existing.add(s)
        added.append(s)
    if not added:
        return wl, ()
    updated = Watchlist(
        updated_at=datetime.now().isoformat(timespec="seconds"),
        entries=tuple(new_entries),
    )
    save(updated, path)
    return updated, tuple(added)


def remove(
    symbols: Iterable[str], path: Path = _DEFAULT_PATH
) -> tuple[Watchlist, tuple[str, ...]]:
    """移除 symbols。內部會先 parse 拆分（支援逗號/空白）。

    Returns (新 Watchlist, 真正移除的 symbol list)。
    """
    wl = load(path)
    targets = set(parse_symbols_arg(symbols))
    removed = tuple(e.symbol for e in wl.entries if e.symbol in targets)
    if not removed:
        return wl, ()
    updated = Watchlist(
        updated_at=datetime.now().isoformat(timespec="seconds"),
        entries=tuple(e for e in wl.entries if e.symbol not in targets),
    )
    save(updated, path)
    return updated, removed


def clear(path: Path = _DEFAULT_PATH) -> int:
    """清空 watchlist。Returns 清掉的筆數。"""
    wl = load(path)
    n = len(wl.entries)
    if n == 0:
        return 0
    save(
        Watchlist(updated_at=datetime.now().isoformat(timespec="seconds"), entries=()),
        path,
    )
    return n


def parse_symbols_arg(args: Iterable[str]) -> tuple[str, ...]:
    """從 telegram 參數抽出 symbol list（支援逗號/空白分隔）。

    例：['2330', '2317,2454'] → ('2330', '2317', '2454')
    """
    out: list[str] = []
    for token in args:
        for piece in token.replace(",", " ").split():
            piece = piece.strip()
            if piece and piece not in out:
                out.append(piece)
    return tuple(out)
