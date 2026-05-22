"""Diagnose Trendline Break signals from latest BTC backtest CSV."""
import csv
from collections import Counter
from statistics import mean, median

with open('reports/smc_backtest_BTC_USDT.csv', encoding='utf-8') as fh:
    rows = list(csv.DictReader(fh))

tl = [r for r in rows if r['setup_name'] == 'Trendline Break + Shift']
print(f'=== Trendline Break + Shift: {len(tl)} signals ===\n')

scores = Counter(int(r['score']) for r in tl)
print(f'  scores: {dict(sorted(scores.items()))}')

rrs = [float(r['risk_reward']) for r in tl]
print(f'  R:R median={median(rrs):.1f}  mean={mean(rrs):.1f}  min={min(rrs):.1f}  max={max(rrs):.1f}')

by_outcome = Counter(r['outcome'] for r in tl)
print(f'  outcomes: {dict(by_outcome)}')

by_dir = {'long': Counter(), 'short': Counter()}
for r in tl:
    by_dir[r['direction']][r['outcome']] += 1
for d, c in by_dir.items():
    print(f'  {d:5s}: {dict(c)}')

stops_pct = [abs(float(r['entry']) - float(r['stop'])) / float(r['entry']) * 100 for r in tl]
print(f'  stop dist %: median={median(stops_pct):.2f}  mean={mean(stops_pct):.2f}  min={min(stops_pct):.3f}  max={max(stops_pct):.2f}')

losses = [r for r in tl if r['outcome'] == 'loss']
wins = [r for r in tl if r['outcome'] == 'win']
opens = [r for r in tl if r['outcome'] == 'open']
if losses:
    bars_l = [int(r['bars_to_resolve']) for r in losses]
    print(f'  loss bars_to_resolve: median={median(bars_l)}  mean={mean(bars_l):.1f}  min={min(bars_l)}  max={max(bars_l)}')
if wins:
    bars_w = [int(r['bars_to_resolve']) for r in wins]
    print(f'  win  bars_to_resolve: median={median(bars_w)}  mean={mean(bars_w):.1f}  min={min(bars_w)}  max={max(bars_w)}')

# Score vs WR
print()
print('  score → outcome:')
buckets: dict[int, Counter] = {}
for r in tl:
    s = int(r['score'])
    buckets.setdefault(s, Counter())[r['outcome']] += 1
for s, c in sorted(buckets.items()):
    w = c['win']; l = c['loss']; o = c['open']
    wr = w / max(1, w + l) * 100
    print(f'    score={s:2d}  n={w+l+o:3d}  W{w} L{l} O{o}  WR={wr:5.1f}%')

# Tightest-stop losses — are they instant?
print()
print('  10 tightest-stop signals:')
tl_sorted = sorted(tl, key=lambda r: abs(float(r['entry']) - float(r['stop'])) / float(r['entry']))
for r in tl_sorted[:10]:
    e = float(r['entry']); s = float(r['stop'])
    pct = abs(e - s) / e * 100
    print(f"    {r['timestamp']}  {r['direction']:5s}  entry={e:.2f}  stop={s:.2f}  ({pct:.3f}%)  → {r['outcome']} in {r['bars_to_resolve']} bars")
