import { useEffect, useState } from 'react'
import { fetchMarketSummary } from '../api/client'

export default function MarketSummary() {
  const [data, setData] = useState(null)

  useEffect(() => {
    fetchMarketSummary()
      .then(setData)
      .catch(() => {})
  }, [])

  if (!data?.taiex_close) return null

  const pct = data.taiex_pct_change ?? 0
  const isUp = pct >= 0
  const color = isUp ? '#ef5350' : '#26a69a'

  return (
    <div
      className="flex items-center gap-3 px-3 py-1.5 rounded text-sm"
      style={{ background: '#161b22', border: '1px solid #30363d' }}
    >
      <span style={{ color: '#8b949e', fontSize: 12 }}>加權指數</span>
      <span className="font-bold">{data.taiex_close?.toLocaleString()}</span>
      <span style={{ color, fontWeight: 600 }}>
        {isUp ? '▲' : '▼'} {Math.abs(pct).toFixed(2)}%
      </span>
      <span className="text-xs" style={{ color: '#8b949e' }}>{data.date}</span>
    </div>
  )
}
