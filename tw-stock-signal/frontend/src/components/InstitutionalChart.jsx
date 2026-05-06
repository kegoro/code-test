import { useMemo } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Cell,
} from 'recharts'

const INST_COLORS = {
  '外資': '#2196F3',
  '投信': '#FF9800',
  '自營商': '#CE93D8',
}

const INST_ORDER = ['外資', '投信', '自營商']

export default function InstitutionalChart({ data }) {
  const grouped = useMemo(() => {
    if (!data?.length) return []
    const map = {}
    data.forEach(d => {
      if (!INST_ORDER.includes(d.name)) return
      if (!map[d.date]) map[d.date] = { date: d.date }
      map[d.date][d.name] = Math.round(d.net / 1000)
    })
    return Object.values(map)
      .sort((a, b) => a.date.localeCompare(b.date))
      .slice(-40)
  }, [data])

  const cumulative = useMemo(() => {
    if (!data?.length) return {}
    const sums = {}
    INST_ORDER.forEach(name => {
      const rows = data.filter(d => d.name === name).slice(-5)
      sums[name] = rows.reduce((s, d) => s + (d.net || 0), 0)
    })
    return sums
  }, [data])

  if (!grouped.length) {
    return <div className="text-center py-10" style={{ color: '#8b949e' }}>無三大法人資料</div>
  }

  return (
    <div>
      <div className="flex gap-6 mb-4 flex-wrap">
        {INST_ORDER.map(name => {
          const val = cumulative[name] ?? 0
          const isPos = val > 0
          return (
            <div key={name} className="flex flex-col">
              <span className="text-xs mb-1" style={{ color: '#8b949e' }}>{name} 近5日累積</span>
              <span className="text-base font-bold" style={{ color: isPos ? '#ef5350' : '#26a69a' }}>
                {isPos ? '+' : ''}{(val / 1000).toFixed(1)} 千張
              </span>
            </div>
          )
        })}
      </div>

      <div className="flex gap-4 text-xs mb-3">
        {INST_ORDER.map(name => (
          <span key={name} className="flex items-center gap-1">
            <span style={{ width: 10, height: 10, background: INST_COLORS[name], display: 'inline-block', borderRadius: 2 }} />
            <span style={{ color: '#8b949e' }}>{name}</span>
          </span>
        ))}
      </div>

      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={grouped} margin={{ left: -10, right: 8, top: 4, bottom: 0 }} barSize={6}>
          <XAxis
            dataKey="date"
            tick={{ fill: '#8b949e', fontSize: 10 }}
            tickFormatter={d => d.slice(5)}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: '#8b949e', fontSize: 10 }}
            tickFormatter={v => `${v}`}
            width={48}
          />
          <Tooltip
            contentStyle={{ background: '#161b22', border: '1px solid #30363d', color: '#e6edf3', fontSize: 12 }}
            formatter={(v, name) => [`${v > 0 ? '+' : ''}${v} 千張`, name]}
          />
          <ReferenceLine y={0} stroke="#30363d" strokeWidth={1} />
          {INST_ORDER.map(name => (
            <Bar key={name} dataKey={name} fill={INST_COLORS[name]}>
              {grouped.map((entry, i) => (
                <Cell
                  key={i}
                  fill={
                    (entry[name] ?? 0) >= 0
                      ? INST_COLORS[name]
                      : INST_COLORS[name] + '88'
                  }
                />
              ))}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
