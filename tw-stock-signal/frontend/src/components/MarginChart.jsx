import { useMemo } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'

function getVal(row, ...keys) {
  for (const k of keys) {
    if (row[k] != null) return row[k]
  }
  return 0
}

export default function MarginChart({ data }) {
  const chartData = useMemo(() => {
    if (!data?.length) return []
    return data.slice(-60).map(d => ({
      date: d.date,
      融資餘額: Math.round(getVal(d, 'margin_balance', 'MarginPurchaseBalance') / 1000),
      融券餘額: Math.round(getVal(d, 'short_balance', 'ShortSaleBalance') / 1000),
    }))
  }, [data])

  const latest = chartData[chartData.length - 1]

  if (!chartData.length) {
    return <div className="text-center py-10" style={{ color: '#8b949e' }}>無融資融券資料</div>
  }

  return (
    <div>
      {latest && (
        <div className="flex gap-6 mb-4">
          <div>
            <div className="text-xs mb-1" style={{ color: '#8b949e' }}>最新融資餘額</div>
            <div className="text-base font-bold" style={{ color: '#ef5350' }}>
              {(latest.融資餘額 ?? 0).toLocaleString()} 千張
            </div>
          </div>
          <div>
            <div className="text-xs mb-1" style={{ color: '#8b949e' }}>最新融券餘額</div>
            <div className="text-base font-bold" style={{ color: '#26a69a' }}>
              {(latest.融券餘額 ?? 0).toLocaleString()} 千張
            </div>
          </div>
          <div>
            <div className="text-xs mb-1" style={{ color: '#8b949e' }}>券資比</div>
            <div className="text-base font-bold" style={{ color: '#ffd700' }}>
              {latest.融資餘額
                ? ((latest.融券餘額 / latest.融資餘額) * 100).toFixed(1) + '%'
                : 'N/A'}
            </div>
          </div>
        </div>
      )}

      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={chartData} margin={{ left: -10, right: 8, top: 4, bottom: 0 }}>
          <XAxis
            dataKey="date"
            tick={{ fill: '#8b949e', fontSize: 10 }}
            tickFormatter={d => d.slice(5)}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: '#8b949e', fontSize: 10 }}
            width={52}
            tickFormatter={v => `${v}`}
          />
          <Tooltip
            contentStyle={{ background: '#161b22', border: '1px solid #30363d', color: '#e6edf3', fontSize: 12 }}
            formatter={(v, name) => [`${v.toLocaleString()} 千張`, name]}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: '#8b949e' }} />
          <Line
            type="monotone"
            dataKey="融資餘額"
            stroke="#ef5350"
            dot={false}
            strokeWidth={1.5}
            activeDot={{ r: 3 }}
          />
          <Line
            type="monotone"
            dataKey="融券餘額"
            stroke="#26a69a"
            dot={false}
            strokeWidth={1.5}
            activeDot={{ r: 3 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
