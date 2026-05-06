import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { CURATED_CATEGORIES } from '../data/curatedCategories'

async function fetchBatchPrices(symbols) {
  try {
    const { data } = await axios.post('/api/batch-prices', symbols)
    return data
  } catch {
    return {}
  }
}

function PriceCell({ priceData }) {
  if (!priceData?.close) {
    return <span style={{ color: '#484f58' }}>—</span>
  }
  const { close, change_pct } = priceData
  const isUp = (change_pct ?? 0) >= 0
  const color = isUp ? '#ef5350' : '#26a69a'
  return (
    <span style={{ color, fontWeight: 600 }}>{close.toLocaleString()}</span>
  )
}

function ChangeCell({ priceData }) {
  if (!priceData?.change_pct) {
    return <span style={{ color: '#484f58' }}>—</span>
  }
  const { change, change_pct } = priceData
  const isUp = change_pct >= 0
  const color = isUp ? '#ef5350' : '#26a69a'
  const arrow = isUp ? '▲' : '▼'
  return (
    <span style={{ color, fontWeight: 600 }}>
      {arrow}{Math.abs(change).toFixed(2)}<br />
      <span style={{ fontSize: 11 }}>{isUp ? '+' : ''}{change_pct.toFixed(2)}%</span>
    </span>
  )
}

export default function CuratedPage() {
  const navigate = useNavigate()
  const [selectedId, setSelectedId] = useState(CURATED_CATEGORIES[0].id)
  const [prices, setPrices] = useState({})
  const [loading, setLoading] = useState(false)
  const cacheRef = useRef({})

  const category = CURATED_CATEGORIES.find(c => c.id === selectedId)

  const loadPrices = useCallback(async () => {
    if (!category) return
    const symbols = category.stocks.map(s => s.symbol)

    // Return cached data immediately if we have it
    const cached = symbols.every(s => cacheRef.current[s] !== undefined)
    if (cached) {
      const subset = {}
      symbols.forEach(s => { subset[s] = cacheRef.current[s] })
      setPrices(subset)
      return
    }

    setLoading(true)
    const data = await fetchBatchPrices(symbols)
    cacheRef.current = { ...cacheRef.current, ...data }
    setPrices(data)
    setLoading(false)
  }, [selectedId])

  useEffect(() => {
    loadPrices()
  }, [loadPrices])

  // Pre-fetch all categories in background
  useEffect(() => {
    const timer = setTimeout(async () => {
      for (const cat of CURATED_CATEGORIES) {
        if (cat.id === selectedId) continue
        const symbols = cat.stocks.map(s => s.symbol)
        const missing = symbols.filter(s => cacheRef.current[s] === undefined)
        if (missing.length > 0) {
          const data = await fetchBatchPrices(missing)
          cacheRef.current = { ...cacheRef.current, ...data }
        }
      }
    }, 1500)
    return () => clearTimeout(timer)
  }, [])

  return (
    <div className="flex h-full" style={{ minHeight: 'calc(100vh - 56px)', gap: 0 }}>
      {/* ── Left sidebar ── */}
      <div
        style={{
          width: 88,
          minWidth: 88,
          background: '#0d1117',
          borderRight: '1px solid #21262d',
          overflowY: 'auto',
        }}
      >
        {CURATED_CATEGORIES.map(cat => (
          <button
            key={cat.id}
            onClick={() => setSelectedId(cat.id)}
            style={{
              width: '100%',
              padding: '14px 8px',
              fontSize: 13,
              textAlign: 'center',
              lineHeight: 1.4,
              color: selectedId === cat.id ? '#e6edf3' : '#8b949e',
              background: selectedId === cat.id ? '#161b22' : 'transparent',
              borderLeft: selectedId === cat.id ? '3px solid #1f6feb' : '3px solid transparent',
              border: 'none',
              borderLeft: selectedId === cat.id ? '3px solid #1f6feb' : '3px solid transparent',
              cursor: 'pointer',
              wordBreak: 'break-all',
            }}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* ── Main table ── */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {/* Table header */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 120px 90px 90px',
            padding: '10px 16px',
            borderBottom: '1px solid #30363d',
            background: '#161b22',
          }}
        >
          {['股票', '產業類別', '股價', '漲跌幅'].map(h => (
            <span key={h} style={{ fontSize: 12, color: '#8b949e', fontWeight: 500 }}>{h}</span>
          ))}
        </div>

        {/* Rows */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {loading && (
            <div style={{ padding: 24, color: '#8b949e', fontSize: 13 }}>資料載入中...</div>
          )}
          {!loading && category?.stocks.map(stock => {
            const price = prices[stock.symbol]
            return (
              <div
                key={stock.symbol}
                onClick={() => navigate(`/stock/${stock.symbol}`)}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 120px 90px 90px',
                  padding: '12px 16px',
                  borderBottom: '1px solid #21262d',
                  cursor: 'pointer',
                  transition: 'background 0.1s',
                }}
                onMouseEnter={e => { e.currentTarget.style.background = '#1c2128' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
              >
                {/* Stock name + code */}
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: '#e6edf3' }}>{stock.name}</div>
                  <div style={{ fontSize: 11, color: '#8b949e', marginTop: 2 }}>{stock.symbol}</div>
                </div>

                {/* Industry */}
                <div style={{ fontSize: 12, color: '#8b949e', alignSelf: 'center' }}>
                  {stock.industry}
                </div>

                {/* Price */}
                <div style={{ fontSize: 15, alignSelf: 'center' }}>
                  <PriceCell priceData={price} />
                </div>

                {/* Change */}
                <div style={{ fontSize: 13, alignSelf: 'center', lineHeight: 1.4 }}>
                  <ChangeCell priceData={price} />
                </div>
              </div>
            )
          })}
        </div>

        {/* Footer */}
        <div style={{ padding: '8px 16px', borderTop: '1px solid #21262d', background: '#0d1117' }}>
          <span style={{ fontSize: 11, color: '#484f58' }}>
            股價來自本地資料庫（執行過掃描後才有資料）｜點擊股票查看K線
          </span>
        </div>
      </div>
    </div>
  )
}
