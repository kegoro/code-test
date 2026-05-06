"""
B1指標：籌碼分析
- foreign_consecutive_buy_days: 外資連續買超天數（正=連買/負=連賣）
- net_foreign_5d: 外資近5日淨買超（張）
- net_trust_5d: 投信近5日淨買超
- margin_trend: 融資餘額趨勢 (rising / flat / falling)
- margin_chasing: 只有融資增加、外資未買 → 散戶追高，H4 硬性排除
- margin_confluence: 外資先買後融資跟進 → 合流，正面 +0.5
- major_holder_ratio: 大戶持股比例（0-1），< 0.40 觸發 H5 硬性排除
- shareholder_declining: 近3期股東人數持續下降 → B1 加分
- avg_volume_5d: 近5日均量（張）
- contrarian_on_weak_market: 大盤下跌>1%但外資仍買超 → 最強B1訊號
"""
from dataclasses import dataclass
import pandas as pd
import numpy as np

MAJOR_HOLDER_THRESHOLD = 0.40   # H5: hard exclusion if below
WEAK_MARKET_THRESHOLD = -0.01   # -1% daily index change
MIN_VOLUME_LOTS = 2000          # H6: min 5-day avg volume (張)
MARGIN_FAST_RISE = 0.05         # 5% rise in 5d = "fast"
CONFLUENCE_LOOKBACK = 5         # days to check if foreign was buying before margin rise


@dataclass
class ChipResult:
    foreign_consecutive_buy_days: int   # + = consecutive buy, - = consecutive sell
    net_foreign_5d: int                 # 張
    net_trust_5d: int
    margin_trend: str                   # "rising" | "flat" | "falling"
    margin_balance_latest: int
    friday_patch_needed: bool
    has_inst_buy_last5d: bool           # 硬性條件③：近5日至少1日外資或投信淨買超
    # Margin: split into two mutually exclusive signals
    margin_chasing: bool                # 散戶追高（H4 排除條件）
    margin_confluence: bool             # 外資帶頭融資跟進（合流，+0.5 加分）
    # Kept for backward compat — True if either chasing or confluence
    margin_rising_fast: bool
    # New fields
    major_holder_ratio: float           # 大戶持股比例 (0-1); -1 = unknown
    shareholder_declining: bool         # 近3期股東人數持續下降
    avg_volume_5d: float                # 近5日均量（張）; -1 = unknown
    contrarian_on_weak_market: bool     # 大盤弱勢仍買超


def analyze_chip(
    institutional: pd.DataFrame,
    margin: pd.DataFrame,
    shareholding: pd.DataFrame | None = None,
    market_index: pd.DataFrame | None = None,
    prices: pd.DataFrame | None = None,
) -> ChipResult:
    foreign = _filter_name(institutional, "外資")
    trust = _filter_name(institutional, "投信")

    consec = _consecutive_days(foreign)
    net_f5 = int(foreign.tail(5)["net"].sum()) if not foreign.empty else 0
    net_t5 = int(trust.tail(5)["net"].sum()) if not trust.empty else 0

    margin_trend, margin_latest = _margin_trend(margin)
    friday_needed = _is_friday_patch_needed(institutional)
    has_inst_buy = _has_inst_buy_last5d(foreign, trust)

    # Margin split: chasing vs confluence
    margin_fast = _margin_is_fast_rising(margin)
    margin_chasing, margin_confluence = _classify_margin(margin_fast, foreign)

    major_ratio, sh_declining = _shareholding_stats(shareholding)
    avg_vol = _avg_volume_5d(prices)
    contrarian = _contrarian_on_weak_market(foreign, market_index)

    return ChipResult(
        foreign_consecutive_buy_days=consec,
        net_foreign_5d=net_f5,
        net_trust_5d=net_t5,
        margin_trend=margin_trend,
        margin_balance_latest=margin_latest,
        friday_patch_needed=friday_needed,
        has_inst_buy_last5d=has_inst_buy,
        margin_chasing=margin_chasing,
        margin_confluence=margin_confluence,
        margin_rising_fast=margin_fast,
        major_holder_ratio=major_ratio,
        shareholder_declining=sh_declining,
        avg_volume_5d=avg_vol,
        contrarian_on_weak_market=contrarian,
    )


# ── Private helpers ─────────────────────────────────────────────────────────


def _filter_name(df: pd.DataFrame, name_substr: str) -> pd.DataFrame:
    if df.empty or "name" not in df.columns:
        return pd.DataFrame(columns=["date", "net"])
    mask = df["name"].str.contains(name_substr, na=False)
    return df[mask].sort_values("date").reset_index(drop=True)


def _consecutive_days(foreign: pd.DataFrame) -> int:
    if foreign.empty:
        return 0
    nets = foreign["net"].tolist()
    if not nets:
        return 0
    last_sign = 1 if nets[-1] >= 0 else -1
    count = 0
    for v in reversed(nets):
        if (v >= 0 and last_sign > 0) or (v < 0 and last_sign < 0):
            count += 1
        else:
            break
    return count * last_sign


def _margin_trend(margin: pd.DataFrame) -> tuple[str, int]:
    if margin.empty or "margin_balance" not in margin.columns:
        return "unknown", 0
    balances = margin["margin_balance"].dropna().values
    if len(balances) < 5:
        return "unknown", int(balances[-1]) if len(balances) else 0

    latest = int(balances[-1])
    slope = np.polyfit(np.arange(len(balances[-10:])), balances[-10:], 1)[0]
    if slope > balances[-1] * 0.001:
        return "rising", latest
    elif slope < -balances[-1] * 0.001:
        return "falling", latest
    return "flat", latest


def _has_inst_buy_last5d(foreign: pd.DataFrame, trust: pd.DataFrame) -> bool:
    for df in (foreign, trust):
        if not df.empty and "net" in df.columns:
            if (df.tail(5)["net"] > 0).any():
                return True
    return False


def _margin_is_fast_rising(margin: pd.DataFrame) -> bool:
    """Raw check: margin balance rose >5% over last 5 days."""
    if margin.empty or "margin_balance" not in margin.columns:
        return False
    balances = margin["margin_balance"].dropna().values
    if len(balances) < 5:
        return False
    base = balances[-5]
    latest = balances[-1]
    if base <= 0:
        return False
    return (latest - base) / base > MARGIN_FAST_RISE


def _classify_margin(
    margin_fast: bool,
    foreign: pd.DataFrame,
) -> tuple[bool, bool]:
    """
    Returns (margin_chasing, margin_confluence).

    Confluence: margin fast rising AND foreign was net-buying in the preceding window.
      → Foreign leads, retail follows. Positive signal.
    Chasing:    margin fast rising AND foreign was NOT net-buying.
      → Pure retail momentum chase. Negative, H4 exclusion.
    """
    if not margin_fast:
        return False, False

    # Check if foreign was net-buying in the recent CONFLUENCE_LOOKBACK days
    if foreign.empty or "net" not in foreign.columns:
        # No institutional data: treat as chasing (conservative)
        return True, False

    recent_foreign_net = foreign.tail(CONFLUENCE_LOOKBACK)["net"].sum()
    foreign_was_buying = recent_foreign_net > 0

    if foreign_was_buying:
        return False, True   # confluence — not a hard exclusion
    return True, False       # chasing — H4 exclusion


def _is_friday_patch_needed(institutional: pd.DataFrame) -> bool:
    if institutional.empty:
        return False
    import datetime
    today = datetime.date.today()
    weekday = today.weekday()
    if weekday not in (5, 6):
        return False
    latest_date = pd.to_datetime(institutional["date"].max()).date()
    days_behind = (today - latest_date).days
    return days_behind >= 1


def _shareholding_stats(
    shareholding: pd.DataFrame | None,
) -> tuple[float, bool]:
    if shareholding is None or shareholding.empty:
        return -1.0, False
    if "major_holder_ratio" not in shareholding.columns:
        return -1.0, False

    latest_ratio = float(shareholding["major_holder_ratio"].iloc[-1])

    declining = False
    if "shareholder_count" in shareholding.columns and len(shareholding) >= 3:
        counts = shareholding["shareholder_count"].values[-3:]
        declining = bool(int(counts[2]) < int(counts[1]) < int(counts[0]))

    return latest_ratio, declining


def _avg_volume_5d(prices: pd.DataFrame | None) -> float:
    if prices is None or prices.empty or "volume" not in prices.columns:
        return -1.0
    vols = prices["volume"].dropna().values
    if len(vols) < 1:
        return -1.0
    return float(np.mean(vols[-5:]))


def _contrarian_on_weak_market(
    foreign: pd.DataFrame,
    market_index: pd.DataFrame | None,
) -> bool:
    if foreign.empty or market_index is None or market_index.empty:
        return False
    if "taiex_pct_change" not in market_index.columns:
        return False

    f = foreign.tail(5).copy()
    mi = market_index.tail(10).copy()

    f["date"] = pd.to_datetime(f["date"])
    mi["date"] = pd.to_datetime(mi["date"])

    merged = f.merge(mi[["date", "taiex_pct_change"]], on="date", how="inner")
    if merged.empty:
        return False

    weak_days = merged["taiex_pct_change"] <= WEAK_MARKET_THRESHOLD
    foreign_buying = merged["net"] > 0
    return bool((weak_days & foreign_buying).any())
