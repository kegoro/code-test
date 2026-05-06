import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchScreener } from '../api/client'

export default function ScreenerPage() {
  const navigate = useNavigate()
  const [params, setParams] = useState({
    min_price: 10,
    max_price: 2000,
    min_volume: 0,
    limit: 50,
  })
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const [error, setError] = useState(null)

  const set = (key, val) => setParams(p => ({ ...p, [key]: val }))

  const handleSearch = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchScreener(params)
      if (data?.error) {
        setError(data.error)
        setResults([])
      } else {
        setResults(Array.isArray(data) ? data : [])
      }
    } catch (e) {
      setError(e.message)
      setResults([])
    } finally {
      setLoading(false)
      setSearched(true)
    }
  }

  return (
    <div>
      <div className="text-xl font-bold mb-1">選股工具</div>
      <div className="text-xs mb-5" style={{ color: '#8b949e' }}>
        從本地資料庫篩選股票（需先完成過一次全市場掃描）
      </div>

      {/* ── Filters ── */}
      <div
        style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 8 }}
        className="p-4 mb-5"
      >
        <div className="flex gap-6 flex-wrap items-end">
          <Field label="最低股價 (元)">
            <NumberInput value={params.min_price} onChange={v => set('min_price', v)} />
          </Field>
          <Field label="最高股價 (元)">
            <NumberInput value={params.max_price} onChange={v => set('max_price', v)} />
          </Field>
          <Field label="最低成交量 (張)">
            <NumberInput value={params.min_volume} onChange={v => set('min_volume', v)} />
          </Field>
          <Field label="顯示筆數">
            <select
              value={params.limit}
              onChange={e => set('limit', Number(e.target.value))}
              style={{ background: '#0d1117', border: '1px solid #30363d', color: '#e6edf3', padding: '5px 8px', borderRadius: 4, fontSize: 13 }}
            >
              {[20, 50, 100, 200].map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          </Field>
          <div className="flex items-end pb-0.5">
            <button
              onClick={handleSearch}
              disabled={loading}
              style={{
                padding: '6px 18px',
                background: loading ? '#21262d' : '#238636',
                color: loading ? '#8b949e' : '#fff',
                border: 'none',
                borderRadius: 5,
                fontSize: 13,
                cursor: loading ? 'not-allowed' : 'pointer',
                fontWeight: 600,
              }}
            >
              {loading ? '篩選中...' : '開始篩選'}
            </button>
          </div>
        </div>
      </div>

      {/* ── Error ── */}
      {error && (
        <div className="mb-4 p-3 rounded text-sm" style={{ background: '#3d1f1f', border: '1px solid #f85149', color: '#f85149' }}>
          {error}
        </div>
      )}

      {/* ── Results ── */}
      {results.length > 0 && (
        <div style={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 8, overflow: 'hidden' }}>
          <div className="px-4 py-2 text-xs" style={{ borderBottom: '1px solid #30363d', color: '#8b949e' }}>
            共 {results.length} 筆結果
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #30363d', background: '#0d1117' }}>
                  {['股票代碼', '收盤價', '成交量 (張)', '資料日期', ''].map(h => (
                    <th key={h} style={{ padding: '8px 14px', textAlign: 'left', color: '#8b949e', fontWeight: 500 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {results.map((row, i) => (
                  <tr
                    key={i}
                    style={{ borderBottom: '1px solid #21262d', cursor: 'pointer', transition: 'background 0.1s' }}
                    onMouseEnter={e => { e.currentTarget.style.background = '#1c2128' }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
                    onClick={() => navigate(`/stock/${row.symbol}`)}
                  >
                    <td style={{ padding: '8px 14px', color: '#58a6ff', fontWeight: 700 }}>{row.symbol}</td>
                    <td style={{ padding: '8px 14px' }}>{row.close ?? '—'}</td>
                    <td style={{ padding: '8px 14px' }}>{row.volume?.toLocaleString() ?? '—'}</td>
                    <td style={{ padding: '8px 14px', color: '#8b949e' }}>{row.date}</td>
                    <td style={{ padding: '8px 14px' }}>
                      <span style={{ color: '#58a6ff', fontSize: 12 }}>查看 →</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {searched && results.length === 0 && !error && (
        <div className="text-center py-12" style={{ color: '#8b949e' }}>
          <div className="text-3xl mb-2">🔍</div>
          <div>沒有符合條件的股票（或資料庫尚未有資料）</div>
          <div className="text-xs mt-1">請先執行一次全市場掃描後再使用選股功能</div>
        </div>
      )}

      {!searched && (
        <div className="text-center py-12" style={{ color: '#8b949e' }}>
          <div className="text-3xl mb-2">📊</div>
          <div>設定篩選條件後按「開始篩選」</div>
        </div>
      )}
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div>
      <label className="block text-xs mb-1" style={{ color: '#8b949e' }}>{label}</label>
      {children}
    </div>
  )
}

function NumberInput({ value, onChange }) {
  return (
    <input
      type="number"
      value={value}
      onChange={e => onChange(Number(e.target.value))}
      style={{
        background: '#0d1117',
        border: '1px solid #30363d',
        color: '#e6edf3',
        padding: '5px 8px',
        borderRadius: 4,
        fontSize: 13,
        width: 100,
        outline: 'none',
      }}
    />
  )
}
