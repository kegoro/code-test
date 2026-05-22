# SMC Analyst — Architecture Doc

> Synthesized from ~20 articles, ICT/SMC playbooks, and the LuxAlgo source
> code. The goal is a `smc_analyst` Python module that turns the existing
> detection layer (`backend/smc_detector.py`) into **actionable trade ideas**
> with entry / stop / target / R:R / confidence — not just "I see a CHoCH".

---

## 0. Executive summary

We already have eight detection primitives implemented:
**BOS / CHoCH / Swing High-Low / Order Block / FVG / EQH-EQL / Strong-Weak / Trendline-Break / MTF levels**.
None of them, on their own, justify entering a trade. The analyst's job is to:

1. Gather context across **HTF → MTF → LTF** (TWSE Daily / 60m / 1m–5m).
2. Match the live state against a **fixed library of 9 trade setups**.
3. Score each match by **weighted confluence** (Tier 1 / 2 / 3).
4. Emit a `TradeIdea` with concrete **entry, stop, target, R:R, confidence,
   reasoning** — only if all hard gates pass.
5. Push to Telegram in a fixed, scannable format.

Hard gates (a failing trade idea is discarded silently):

- HTF bias must agree with the trade direction.
- R:R ≥ 1.5 against the nearest structural target.
- Confluence score ≥ 7 / 15.
- TWSE session is 09:00 – 13:30; no trades in the lunch chop (12:00 – 13:00 by default).

---

## 1. Conceptual foundation — why SMC works (the working hypothesis)

The SMC framework rests on one belief: **institutional flow drives the
market and they need liquidity to fill big orders**. Retail stops cluster at
visible swing highs / lows. Institutions therefore push price into those
clusters first (the "stop hunt" / liquidity sweep), absorb the resulting
fills, then reverse with size. Each detection primitive maps to one phase of
that cycle:

| Phase | What institutions are doing | What we detect |
|-------|-----------------------------|----------------|
| Accumulation / Distribution | Quietly building a position inside a range | Premium / Equilibrium / Discount zones; consolidation between swing extremes |
| Liquidity Grab | Forcing price through a known stop level | Sweep of EQH / EQL, PDH / PDL, prior swing high / low |
| Structure Shift | Position is filled, market reverses | CHoCH (first counter-trend break), then BOS (continuation) |
| Imbalance | They moved size, leaving an unfilled gap | Fair Value Gap |
| Order Block | The candle from which the move launched | Bullish / Bearish OB; later **Breaker** if it fails, **Mitigation** if it holds |
| Distribution to Retail | Price returns to OB / FVG, retail enters late | Retest, then continuation toward the next liquidity target |

The analyst's job is to recognize **which phase we are currently in** and
trade *with* the institutions, not against them.

---

## 2. The 5-step universal entry framework

Every concrete setup in §3 is a specialization of this five-step framework
(adapted from ICT's standard workflow):

```
┌────────────────────────────────────────────────────────────────────────┐
│ Step 1.  HTF BIAS              Daily structure → bullish / bearish /  │
│                                ranging. Sets which side of the market │
│                                we are allowed to trade.                │
│                                                                        │
│ Step 2.  LIQUIDITY TARGET      Where do retail stops sit?              │
│                                EQH/EQL clusters, PDH/PDL, swing        │
│                                high/low. This is the *bait*.           │
│                                                                        │
│ Step 3.  LIQUIDITY SWEEP       Price runs the target, briefly. Wick    │
│                                pokes through then closes back inside.  │
│                                **This is the buy/sell signal trigger.**│
│                                                                        │
│ Step 4.  MARKET STRUCTURE      LTF CHoCH or MSS confirms institutions  │
│          SHIFT (CHoCH)          have reversed. Without this, the sweep │
│                                was just noise.                         │
│                                                                        │
│ Step 5.  REFINED ENTRY         Wait for retest of the OB / FVG / OTE   │
│                                level that formed during the shift.     │
│                                Enter on confirmation candle.           │
└────────────────────────────────────────────────────────────────────────┘
```

Why this beats "just trade the CHoCH": a CHoCH without a prior liquidity
sweep is *retail noise*; a sweep without a CHoCH is *trend continuation*; the
two together are *institutional reversal*.

---

## 3. Setup library — the playbook (9 setups)

Each setup is a Python class with:

```python
class Setup:
    name: str
    bias: Literal["long", "short", "both"]
    required_htf_bias: Literal["bullish", "bearish", "any"]
    tier1_signals: list[str]      # 3 pts each, must have ≥1
    tier2_signals: list[str]      # 2 pts each
    tier3_signals: list[str]      # 1 pt each
    min_score: int                # default 7
    entry_rule: str               # which level to enter at
    stop_rule: str                # which level invalidates
    target_rule: str              # which liquidity to target

    def evaluate(self, ctx: AnalysisContext) -> Optional[SetupMatch]:
        ...
```

### Setup 3.1 — Liquidity-Sweep Reversal (★ flagship, highest probability)

**Trade idea**: price has just swept an obvious liquidity pool (EQH for
shorts, EQL for longs); LTF immediately printed a CHoCH against the sweep.

| Component | Requirement |
|-----------|-------------|
| HTF bias | any |
| Tier 1 — must have | EQH/EQL sweep within last N bars **AND** opposite-direction CHoCH |
| Tier 2 — booster | LTF FVG formed during the shift; OB formed by the shift candle |
| Tier 3 — booster | Sweep level coincides with PDH/PDL/PWH/PWL; Strong High/Low at the sweep |
| Entry | CE (50% midpoint) of the LTF FVG, **OR** OTE 70.5% of the swept leg |
| Stop | Beyond the sweep wick + 0.1× ATR |
| Target | Opposite Strong High/Low, **OR** next obvious liquidity (PDH/PDL/PWH/PWL) |
| Disqualifiers | LTF setup against HTF bias (counter-trend mode = score ÷ 2); no FVG present in the shift |

This is the "Liquidity Sweep + FVG Reclaim" model — the model with the
highest documented win rate in modern SMC literature.

### Setup 3.2 — Order-Block Retest Continuation (with-trend)

**Trade idea**: HTF in clear trend; recent BOS; price pulls back to the OB
that produced the displacement; OB still unmitigated.

| Component | Requirement |
|-----------|-------------|
| HTF bias | must match trade direction (long if HTF bullish, short if HTF bearish) |
| Tier 1 | Valid OB whose `formed_bar` was the candle before a BOS; OB still valid |
| Tier 2 | FVG inside or adjacent to the OB; price within 0.3× ATR of OB edge |
| Tier 3 | OB sits inside Discount Zone (long) or Premium Zone (short); MTF level overlap |
| Entry | OB top edge (long) or OB bottom edge (short), or CE of the overlapping FVG |
| Stop | Beyond the OB extreme + buffer |
| Target | Next swing high (long) / low (short), then PDH/PWH (long) / PDL/PWL (short) |
| Disqualifiers | OB body has been closed through; >1 OB cluster in same zone (ambiguity) |

### Setup 3.3 — Premium Fade (short)

**Trade idea**: price has run into the upper 5% (Premium) band; a Bearish OB
just formed there; we sell back into Equilibrium.

| Component | Requirement |
|-----------|-------------|
| HTF bias | bearish or ranging |
| Tier 1 | Price currently inside Premium Zone (≥ 0.95 of trailing range); Bearish OB or Bearish FVG formed at the touch |
| Tier 2 | CHoCH_DOWN on LTF; Weak High classification at the high; EQH sweep just above |
| Tier 3 | Down-trendline break confirmation pending; PDH or PWH coincides with Premium |
| Entry | OB bottom edge / FVG CE |
| Stop | Above Premium Zone top + buffer |
| Target | Equilibrium midpoint; then Discount Zone if HTF allows |
| Disqualifiers | HTF strongly bullish (BOS_UP within last 20 bars); ATR < daily mean × 0.5 (no volatility, mean reversion fails) |

### Setup 3.4 — Discount Rally (long) — mirror of 3.3

Same logic, opposite side. Buy in the bottom 5% (Discount) band when a
Bullish OB / FVG forms there and HTF is bullish or ranging.

### Setup 3.5 — Breaker Block (failed-OB reversal)

**Trade idea**: a previous OB was broken through (full body close past it),
then price swept liquidity beyond the structural high/low that the OB used
to defend, then returned to retest the broken OB — which now flips and acts
as resistance/support from the other side.

| Component | Requirement |
|-----------|-------------|
| HTF bias | any |
| Tier 1 | An OB has been broken (body close beyond its extreme); the previous swing high/low **has been swept** afterward |
| Tier 2 | LTF CHoCH formed inside the flipped OB zone on retest; FVG inside the breaker |
| Tier 3 | Strong/Weak tag agrees; MTF level overlap |
| Entry | Retest of the flipped OB edge |
| Stop | Beyond the outer edge of the breaker block |
| Target | Next draw on liquidity |
| Disqualifiers | No liquidity sweep before the reversal (= just a failed OB, not a breaker) |

### Setup 3.6 — Mitigation Block (with-trend continuation)

**Trade idea**: an OB delivered a clean displacement leg, was not broken,
and is being retested in the trend direction.

| Component | Requirement |
|-----------|-------------|
| HTF bias | must match trade direction |
| Tier 1 | OB has produced one full leg of displacement; OB still valid (no body close through); price tapping OB now |
| Tier 2 | LTF rejection candle / MSS at the OB tap |
| Tier 3 | MTF level overlap |
| Entry | At OB tap |
| Stop | Beyond OB extreme + small buffer |
| Target | Prior swing extreme; then next liquidity |
| Disqualifiers | OB has been mitigated by previous touches (counts touches via swing-low retracements); HTF bias not aligned |

### Setup 3.7 — FVG Fill at HTF Zone (precision)

**Trade idea**: HTF FVG is unmitigated; price is now filling it; LTF prints
a CHoCH inside the gap.

| Component | Requirement |
|-----------|-------------|
| HTF bias | match trade direction |
| Tier 1 | Valid HTF FVG (60m or higher) being touched right now; LTF CHoCH formed inside the gap |
| Tier 2 | OB formed by the LTF CHoCH; Premium/Discount alignment |
| Tier 3 | EQ liquidity at the boundary of the gap |
| Entry | CE (midpoint) of the LTF FVG that formed during the CHoCH |
| Stop | Opposite edge of the HTF FVG |
| Target | Next liquidity in trend direction |
| Disqualifiers | HTF FVG already mitigated; LTF structure still trending against the trade |

### Setup 3.8 — Unicorn (Breaker + FVG overlap) — ★ rare, high-conviction

**Trade idea**: a Breaker Block and an FVG occupy the same price range. The
LuxAlgo and ICT communities both treat this as the highest-conviction setup,
appearing roughly twice per week per liquid instrument.

Implementation: take §3.5 (Breaker) and require an additional check that an
FVG's `[bottom, top]` range overlaps the breaker's range by ≥ 50%. If yes,
boost the score by +3 (effectively forcing it into the highest tier).

### Setup 3.9 — Trendline Break + Structure Shift

**Trade idea**: an up-trendline (LuxAlgo Trendlines-with-Breaks) breaks
downward AND a CHoCH_DOWN fires on the same / adjacent bar — confirms a
character change rather than a fakeout.

| Component | Requirement |
|-----------|-------------|
| HTF bias | any |
| Tier 1 | Trendline break event + same-direction CHoCH within 5 bars |
| Tier 2 | OB or FVG formed at the break |
| Tier 3 | MTF level overlap; Strong/Weak alignment |
| Entry | Retest of the broken trendline (now flipped) |
| Stop | Beyond the most recent failed swing |
| Target | Next liquidity in the new direction |
| Disqualifiers | Trendline was very flat (slope ≈ 0); only one of {break, CHoCH} present |

---

## 4. Confluence scoring framework

Every detected primitive has a fixed weight. A `SetupMatch` accumulates
points; the threshold filters out noise.

```
TIER 1 — 3 pts each  ←  the "necessary" signals; setup requires ≥1
    • LTF CHoCH against the prevailing LTF structure
    • Liquidity sweep of EQH/EQL/PDH/PDL/PWH/PWL
    • Premium↔Discount alignment with trade direction
    • Valid OB present at the entry zone

TIER 2 — 2 pts each  ←  strong boosters
    • Valid FVG at the entry zone
    • Breaker block at the entry zone
    • EQH/EQL pair present (visible draw on liquidity)
    • LTF MSS / break of internal structure
    • MTF level (PDH/PDL/PWH/PWL) coincides with entry

TIER 3 — 1 pt each   ←  weak boosters
    • Trendline break in trade direction
    • Strong/Weak swing tag aligns with trade direction
    • OTE 70.5% level inside the entry zone
    • Session is "trend-friendly" (09:00–11:30 or 13:00–13:30 TWSE)
    • Price within 0.3× ATR of a Strong High/Low

SCORE        →  ACTION
≥ 10         →  HIGH CONVICTION — push as 🔥 alert
 7 –  9      →  STANDARD — push as 📐 alert
 4 –  6      →  WATCH — log only, no push
 < 4         →  IGNORE
```

**Counter-trend penalty**: if a setup direction disagrees with HTF bias,
final score is halved before threshold checks. This implements the cardinal
SMC rule ("never trade against the higher timeframe") without forbidding it
outright — a 14-point setup is still tradeable counter-trend, a 7-point one
is not.

---

## 5. HTF → LTF data workflow

```
        ┌────────────┐
        │ HTF: Daily │  ← structure, bias, MTF levels (PDH/PDL/PWH/PWL),
        └─────┬──────┘    HTF FVG, HTF OB
              │
              ▼
        ┌────────────┐
        │ MTF: 60m   │  ← zone identification: which OB / FVG / range
        └─────┬──────┘    is currently active? Premium/Discount levels.
              │
              ▼
        ┌────────────┐
        │ LTF: 1-5m  │  ← entry trigger: CHoCH, OB retest, MSS, sweep
        └────────────┘
```

For TWSE we use **Daily for HTF, 15m or 60m for MTF, 1m or 3m for LTF**. The
analyst pulls all three on demand:

```python
async def gather_context(symbol: str) -> AnalysisContext:
    htf_daily, mtf_60m, ltf_1m = await asyncio.gather(
        shioaji_fetch_daily(symbol, lookback=120),
        # 60m needs ~30 days of m1 source data (TWSE = 5 h-bars/day)
        _intraday_frame(symbol, "60", days=30),
        shioaji_fetch_m1(symbol, days=5),
    )
    return AnalysisContext(
        symbol=symbol,
        htf=Frame(daily=htf_daily, structure=detect_market_structure(htf_daily, n=5)),
        mtf=Frame(bars=mtf_60m, structure=detect_market_structure(mtf_60m, n=5)),
        ltf=Frame(bars=ltf_1m, structure=detect_market_structure(ltf_1m, n=10)),
        # Pre-compute all the things every setup needs to query:
        liquidity=_collect_liquidity(htf_daily, mtf_60m, ltf_1m),
        pd_zones=compute_premium_discount(...),
        mtf_levels=compute_mtf_levels(htf_daily),
        active_obs=find_order_blocks(ltf_1m, max_count=5),
        active_fvgs=[f for f in find_fair_value_gaps(ltf_1m) if f["valid"]],
        trendlines=compute_trendlines(ltf_1m, length=14),
    )
```

The context is **immutable** and **cached per (symbol, last_bar_timestamp)**
so multiple setups can share the same compute.

---

## 6. TWSE-specific adaptations (vs canonical ICT)

ICT's killzones (London Open 02:00–05:00 EST, NY AM 07:00–10:00 EST, NY PM
13:30–16:00 EST) target the **overlap of two FX sessions**. They don't apply
to TWSE. The TWSE-specific zones are:

| Local time | Behaviour | Setups to prefer | Setups to avoid |
|-----------|-----------|------------------|-----------------|
| 09:00 – 09:30 | Opening drive — gap fills, volatility expansion | Liquidity-sweep reversal, breaker | OB retest (too noisy) |
| 09:30 – 11:30 | Trend day continuation | OB retest, mitigation, trendline break | — |
| 11:30 – 12:30 | Lunch chop, low volume | none — **DO NOT TRADE** | all |
| 12:30 – 13:30 | Closing drive — squaring of positions | Liquidity sweep, FVG fill | mitigation (too late in session) |

The session check is a hard gate in §4: any setup firing in 11:30–12:30
gets its score forced to 0.

---

## 7. Anti-patterns / disqualifiers (hard nos)

These cause a setup to be discarded **before** scoring, not after:

1. **Against HTF bias by 2 grades** — e.g. HTF strongly bullish (BOS_UP in
   last 20 bars **AND** structure remains bullish) and the setup is short.
2. **R:R < 1.5** — calculated against the nearest structural target, not the
   trader's wish.
3. **OB cluster** — three or more order blocks within 0.5× ATR of each other.
   Indicates indecision; price will chop through them.
4. **Sweep without close-back** — wick poked the level but the bar didn't
   close back inside the prior range. That's continuation, not reversal.
5. **Recently mitigated zone** — OB/FVG that has already been touched twice
   has very low remaining edge.
6. **Lunch session** — 11:30–12:30 TWSE local.
7. **Bar count below MIN_BARS** — the underlying frame has too few bars for
   structure to be well-defined.

---

## 8. Module architecture (Python)

```
backend/
├── smc_detector.py          ← already done (detection primitives)
└── smc_analyst/
    ├── __init__.py
    ├── context.py           ← AnalysisContext + gather_context()
    ├── setups/
    │   ├── __init__.py      ← registry of all setups
    │   ├── base.py          ← Setup ABC, SetupMatch dataclass
    │   ├── sweep_reversal.py
    │   ├── ob_continuation.py
    │   ├── premium_fade.py
    │   ├── discount_rally.py
    │   ├── breaker.py
    │   ├── mitigation.py
    │   ├── fvg_at_htf_zone.py
    │   ├── unicorn.py
    │   └── trendline_break.py
    ├── scoring.py           ← ConfluenceScorer, weights, threshold logic
    ├── trade_idea.py        ← TradeIdea dataclass, Telegram formatter
    └── pipeline.py          ← orchestrator: gather → match → score → emit
```

### Core types

```python
@dataclass(frozen=True)
class SetupMatch:
    setup_name: str
    direction: Literal["long", "short"]
    confidence: int                  # 1..10, derived from score
    score: int
    score_breakdown: dict[str, int]  # signal → points contributed
    entry: float
    stop: float
    target: float
    risk_reward: float
    reasoning: list[str]             # human-readable evidence

@dataclass(frozen=True)
class TradeIdea:
    symbol: str
    timestamp: datetime
    match: SetupMatch
    htf_bias: str
    session_phase: str               # "open" / "trend" / "lunch" / "close"
    chart_png: bytes | None          # snapshot via smc_report.render_chart_png

    def telegram_text(self) -> str: ...
```

### Pipeline (the public entry-point)

```python
async def analyse(symbol: str) -> TradeIdea | None:
    ctx = await gather_context(symbol)
    if _session_is_lunch(ctx.now):
        return None
    matches = [s.evaluate(ctx) for s in SETUP_REGISTRY]
    matches = [m for m in matches if m is not None]
    matches = [m for m in matches if _passes_hard_gates(m, ctx)]
    if not matches:
        return None
    best = max(matches, key=lambda m: m.score)
    if best.score < MIN_SCORE:
        return None
    return TradeIdea(symbol=symbol, timestamp=ctx.now, match=best,
                    htf_bias=ctx.htf.structure["structure"],
                    session_phase=_session_phase(ctx.now),
                    chart_png=render_chart_png(...))
```

---

## 9. Telegram output format (fixed template)

```
🎯 2330 做空訊號 — Liquidity-Sweep Reversal
信心度 8/10  |  Score 11/15  |  R:R 3.4

📍 進場：2265.00 (CE of LTF FVG)
🛑 止損：2275.00 (sweep wick + buffer)
🎯 目標：2230.00 (PDL)

📊 依據
  ✓ 1m CHoCH_DOWN @ 12:44                    +3
  ✓ EQH sweep @ 2280 (12:38, 2 bars before)  +3
  ✓ Bearish FVG 2272–2278 formed in shift    +2
  ✓ Price entered Premium Zone (2278)        +2
  ✓ Trendline up-break @ 11:30               +1
  ✓ Strong High tag matches short bias       +1

⚠ HTF (Daily) bias: bullish — counter-trend mode
   (score halved from 22 → 11; still above threshold)

🔍 Chart: [PNG attached]
```

Compact mode (when ≥3 ideas fire simultaneously, summary only):

```
🎯 SMC ALERTS (3)
2330  SHORT  8/10  R:R 3.4   sweep-reversal
2317  LONG   7/10  R:R 2.1   ob-continuation
2382  SHORT  6/10  R:R 1.8   trendline-break
```

---

## 10. Implementation phases

| Phase | Scope | Time |
|-------|-------|------|
| **P0** | `AnalysisContext` + `gather_context()` + caching | 1 day |
| **P1** | `Setup` ABC, `ConfluenceScorer`, registry plumbing | 0.5 day |
| **P2** | 3 setups: `sweep_reversal`, `ob_continuation`, `premium_fade` | 1 day |
| **P3** | `TradeIdea` formatter + Telegram delivery (with PNG) | 0.5 day |
| **P4** | Remaining 6 setups | 1.5 days |
| **P5** | Backtest harness — replay last 30 days, count signals, compute hypothetical R:R | 1 day |
| **P6** | Tuning: weight calibration + threshold sweep based on P5 results | 0.5 day |

P0–P3 is the MVP — after 3 days we can fire alerts. P4–P6 turns it from a
toy into a measurable analyst.

---

## 11. Open questions / decisions deferred

These do not block the MVP but matter long-term:

- **Live streaming vs polling**: do we wait for new bars (subscribe via Shioaji)
  or run on a 1-minute cron? Polling is simpler; streaming is what makes the
  killzone-style entries possible.
- **Backtest semantics**: replaying historical bars and re-running
  `gather_context` is straightforward; the question is what "win/loss" means
  without intrabar simulation. Start with: signal hit target before stop = win.
- **Watchlist size**: TWSE has ~1700 symbols. Running 9 setups on each every
  minute is 15 300 evaluations/minute. The detector functions are fast
  (~5 ms per setup), but the data fetch is the bottleneck. Solve with a
  shared cache.
- **News-driven invalidation**: SMC's "institutional flow" model assumes a
  normal tape. Earnings days, MSCI rebalancing, half-day trading break the
  model. Optional manual flag for "no SMC alerts today".

---

## 12. Sources

Synthesized from these articles (read in full during research):

- [Smart Money Concepts (SMC): The Complete Guide to Trading Like Banks and Hedge Funds in 2026 — Mind Math Money](https://www.mindmathmoney.com/articles/smart-money-concepts-the-ultimate-guide-to-trading-like-institutional-investors-in-2025)
- [Top 30 Smart Money Trading Strategies for 2026 — Medium](https://medium.com/@smcTradingStrategies/top-30-smart-money-trading-strategies-for-2026-29b51e372284)
- [ICT Trading Strategy: Complete Guide (2026) — Quantum-Algo](https://www.quantum-algo.com/blog/ict-trading-strategy-complete-guide/)
- [ICT vs SMC: The Hybrid Roadmap to Master Price Action — FXNX](https://fxnx.com/en/blog/ict-vs-smc-hybrid-roadmap-mastering-price-action)
- [Order Blocks Trading: The Complete 2026 Guide — Quantum-Algo](https://www.quantum-algo.com/blog/guides/order-blocks-complete-trading-guide/)
- [What Is CHOCH in Trading? Change of Character Simplified — EBC](https://www.ebc.com/forex/what-is-choch-in-trading-change-of-character-explained)
- [SMC Trading: The "Liquidity Sweep + FVG Reclaim" Model — Medium](https://medium.com/@clydejnr7/smc-trading-the-liquidity-sweep-fvg-reclaim-model-todays-setup-guide-7f4251049ffb)
- [Liquidity Sweep Trading Strategy — Mind Math Money](https://www.mindmathmoney.com/articles/liquidity-sweep-trading-strategy-how-smart-money-hunts-stop-losses-for-profit)
- [What is ICT FVG — Fair Value Gap Explained Step by Step — InnerCircleTrader.net](https://innercircletrader.net/tutorials/fair-value-gap-trading-strategy/)
- [Fair Value Gap (FVG) Trading Guide — Alchemy Markets](https://alchemymarkets.com/education/strategies/fair-value-gap/)
- [ICT Inverse Fair Value Gap (IFVG) — InnerCircleTrader.net](https://innercircletrader.net/tutorials/ict-inversion-fair-value-gap/)
- [Master ICT Optimal Trade Entry (OTE) — InnerCircleTrader.net](https://innercircletrader.net/tutorials/ict-optimal-trade-entry-ote-pattern/)
- [ICT Mitigation Block Explained — InnerCircleTrader.net](https://innercircletrader.net/tutorials/ict-mitigation-block-explained/)
- [ICT Breaker Block Trading — InnerCircleTrader.net](https://innercircletrader.net/tutorials/ict-breaker-block-trading/)
- [ICT Unicorn Model — Breaker + FVG Overlap — InnerCircleTrader.net](https://innercircletrader.net/tutorials/ict-unicorn-model/)
- [The Power of Multi-Timeframe Analysis in Smart Money Concepts — ACY](https://acy.com/en/market-news/education/power-of-multi-timeframe-analysis-in-smart-money-concepts-j-o-134004/)
- [SMC HTF Bias + LTF Entry: A Precision Forex Trading Guide — FXNX](https://fxnx.com/en/blog/smc-htf-bias-ltf-entry-precision-guide)
- [Risk Management In ICT & SMC Trading — Trading Strategy Guides](https://tradingstrategyguides.com/day-17-risk-management-in-ict-smc-trading-position-sizing-stop-loss-drawdown/)
- [Lecture 14: Stop Loss And Take Profit In SMC — Trading Strategy Guides](https://tradingstrategyguides.com/lecture-14-stop-loss-and-take-profit-in-smart-money-concepts-smc-logical-placement-based-on-liquidity-structure/)
- [Lecture 15: Common Mistakes Beginners Make In SMC — Trading Strategy Guides](https://tradingstrategyguides.com/lecture-15-common-mistakes-beginners-make-in-smart-money-concepts-smc/)
- [Day 19: 7 Common ICT & SMC Trading Mistakes — Trading Strategy Guides](https://tradingstrategyguides.com/day-19-7-common-ict-smc-trading-mistakes-beginners-make-and-how-to-fix-them/)
- [Anatomy of a Valid Order Block in SMC — ACY](https://acy.com/en/market-news/education/anatomy-of-a-valid-order-block-j-o-20251110-092434/)
- [SMC & ICT Trading Guide 2026 — ForexTradeLab](https://forextradelab.com/blog/smart-money-concepts-ict-trading-guide/)
- [LuxAlgo Smart Money Concepts indicator source](../indicators/Smart%20Money%20Concepts.txt) — primary reference for our existing detectors
- [LuxAlgo Trendlines with Breaks indicator source](../indicators/Trendlines%20with%20breaks.txt)
