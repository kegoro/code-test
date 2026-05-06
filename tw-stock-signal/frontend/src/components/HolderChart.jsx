import { useMemo } from 'react'
import {
  ComposedChart, Line, YAxis, XAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from 'recharts'

function fmt(v) {
  if (v == null) return '-'
  return (v * 100).toFixed(2) + '%'
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: '#161b22', border: '1px solid #30363d',
      borderRadius: 6, padding: '8px 12px', fontSize: 12,
    }}>
      <div style={{ color: '#8b949e', marginBottom: 4 }}>{label}</div>
      {payload.map(p => (
        <div key={p.dataKey} style={{ color: p.color, marginBottom: 2 }}>
          {p.name}：{p.dataKey === 'price' ? p.value?.toFixed(2) : fmt(p.value)}
        </div>
      ))}
    </div>
  )
}

export default function HolderChart({ shareholding, ohlcv }) {
  const merged = useMemo(() => {
    if (!shareholding?.length) return []

    const priceMap = {}
    ohlcv?.forEach(row => { priceMap[row.date] = row.close })

    return shareholding.map(row => {
      const major = row.major_holder_ratio ?? 0
      const retail = Math.max(0, 1 - major)
      return {
        date: row.date,
        major,
        retail,
        price: priceMap[row.date] ?? null,
      }
    })
  }, [shareholding, ohlcv])

  const tableRows = useMemo(() => {
    if (!shareholding?.length) return []
    return [...shareholding].reverse().slice(0, 10).map((row, i, arr) => {
      const prev = arr[i + 1]
      const major = row.major_holder_ratio ?? 0
      const retail = Math.max(0, 1 - major)
      const prevMajor = prev?.major_holder_ratio ?? major
      const delta = major - prevMajor
      return { ...row, major, retail, delta }
    })
  }, [shareholding])

  const hasData = merged.length > 0 && merged.some(r => r.major > 0)

  return (
    <div>
      <div className="flex gap-4 mb-4 flex-wrap" style={{ fontSize: 12 }}>
        <span className="flex items-center gap-1" style={{ color: '#8b949e' }}>
          <span style={{ width: 16, height: 2, background: '#ef5350', display: 'inline-block' }} /> 大戶
        </span>
        <span className="flex items-center gap-1" style={{ color: '#8b949e' }}>
          <span style={{ width: 16, height: 2, background: '#26a69a', display: 'inline-block' }} /> 散戶
        </span>
        <span className="flex items-center gap-1" style={{ color: '#8b949e' }}>
          <span style={{ width: 16, height: 2, background: '#8b949e', display: 'inline-block', borderTop: '2px dashed #8b949e' }} /> 股價
        </span>
      </div>

      {!hasData ? (
        <div style={{
          background: '#0d1117', border: '1px solid #21262d', borderRadius: 8,
          height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#8b949e', fontSize: 13,
        }}>
          大戶持股資料需 FinMind 付費方案（持股分級 TaiwanStockShareholding）
        </div>
      ) : (
        <div style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 8, padding: '12px 4px 4px' }}>
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={merged} margin={{ top: 4, right: 40, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#21262d" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: '#8b949e' }}
                tickLine={false}
                interval="preserveStartEnd"
              />
              <YAxis
                yAxisId="pct"
                domain={[0, 1]}
                tickFormatter={v => (v * 100).toFixed(0) + '%'}
                tick={{ fontSize: 10, fill: '#8b949e' }}
                tickLine={false}
                axisLine={false}
                width={42}
              />
              <YAxis
                yAxisId="price"
                orientation="right"
                tick={{ fontSize: 10, fill: '#8b949e' }}
                tickLine={false}
                axisLine={false}
                width={44}
              />
              <Tooltip content={<CustomTooltip />} />
              <Line
                yAxisId="pct"
                type="monotone"
                dataKey="major"
                name="大戶持股"
                stroke="#ef5350"
                dot={false}
                strokeWidth={2}
              />
              <Line
                yAxisId="pct"
                type="monotone"
                dataKey="retail"
                name="散戶持股"
                stroke="#26a69a"
                dot={false}
                strokeWidth={2}
              />
              <Line
                yAxisId="price"
                type="monotone"
                dataKey="price"
                name="股價"
                stroke="#8b949e"
                dot={false}
                strokeWidth={1.5}
                strokeDasharray="4 2"
                connectNulls
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* 持股明細表格 */}
      {tableRows.length > 0 && (
        <div className="mt-4">
          <div style={{ fontSize: 13, fontWeight: 600, color: '#8b949e', marginBottom: 8 }}>持股分佈明細</div>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #30363d' }}>
                {['日期', '大戶持股(%)', '大戶增減(%)', '散戶持股(%)', '持股人數'].map(h => (
                  <th key={h} style={{ padding: '6px 8px', textAlign: 'right', color: '#8b949e', fontWeight: 500, ':first-child': { textAlign: 'left' } }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tableRows.map((row, i) => {
                const deltaColor = row.delta >= 0 ? '#ef5350' : '#26a69a'
                return (
                  <tr key={i} style={{ borderBottom: '1px solid #21262d' }}>
                    <td style={{ padding: '5px 8px', color: '#8b949e' }}>{row.date}</td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', color: '#ef5350', fontWeight: 600 }}>
                      {(row.major * 100).toFixed(2)}
                    </td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', color: deltaColor, fontWeight: 600 }}>
                      {row.delta >= 0 ? '+' : ''}{(row.delta * 100).toFixed(2)}
                    </td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', color: '#26a69a' }}>
                      {(row.retail * 100).toFixed(2)}
                    </td>
                    <td style={{ padding: '5px 8px', textAlign: 'right', color: '#8b949e' }}>
                      {row.shareholder_count ? row.shareholder_count.toLocaleString() : '-'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
