import { useParams, useNavigate } from 'react-router-dom'
import { useState, useEffect, useCallback } from 'react'
import {
  fetchOHLCV,
  fetchInstitutional,
  fetchMargin,
  fetchFundamentals,
  fetchShareholding,
  fetchBroker,
} from '../api/client'
import KLineChart from '../components/KLineChart'
import InstitutionalChart from '../components/InstitutionalChart'
import MarginChart from '../components/MarginChart'
import ChipSummary from '../components/ChipSummary'
import FundamentalPanel from '../components/FundamentalPanel'
import MarketSummary from '../components/MarketSummary'
import BrokerReport from '../components/BrokerReport'
import HolderChart from '../components/HolderChart'

const TABS = ['籌碼總覽', '籌碼日報', '大戶散戶', '三大法人', '融資融券', '基本面分析']
const DAYS_OPTIONS = [30, 60, 90, 120, 240]

const MA_LEGEND = [
  ['MA5',  '#ff6b35'],
  ['MA10', '#ffd700'],
  ['MA20', '#00bcd4'],
  ['MA60', '#e91e63'],
  ['MA120','#9c27b0'],
]

export default function StockPage() {
  const { symbol } = useParams()
  const navigate = useNavigate()
  const [ohlcv, setOhlcv] = useState([])
  const [institutional, setInstitutional] = useState([])
  const [margin, setMargin] = useState([])
  const [shareholding, setShareholding] = useState([])
  const [broker, setBroker] = useState([])
  const [fundamentals, setFundamentals] = useState(null)
  const [fundamentalsLoaded, setFundamentalsLoaded] = useState(false)
  const [activeTab, setActiveTab] = useState('籌碼總覽')
  const [days, setDays] = useState(120)
  const [brokerDays, setBrokerDays] = useState(60)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const loadData = useCallback(async () => {
    if (!symbol) return
    setLoading(true)
    setError(null)
    try {
      const [ohlcvData, instData, marginData, shareholdingData] = await Promise.all([
        fetchOHLCV(symbol, days),
        fetchInstitutional(symbol, days),
        fetchMargin(symbol, days),
        fetchShareholding(symbol, 365),
      ])
      setOhlcv(Array.isArray(ohlcvData) ? ohlcvData : [])
      setInstitutional(Array.isArray(instData) ? instData : [])
      setMargin(Array.isArray(marginData) ? marginData : [])
      setShareholding(Array.isArray(shareholdingData) ? shareholdingData : [])
    } catch (e) {
      setError(`查詢 ${symbol} 失敗：${e.response?.data?.detail ?? e.message}`)
      setOhlcv([])
    } finally {
      setLoading(false)
    }
  }, [symbol, days])

  const loadBroker = useCallback(async () => {
    if (!symbol) return
    try {
      const data = await fetchBroker(symbol, brokerDays)
      setBroker(Array.isArray(data) ? data : [])
    } catch {
      setBroker([])
    }
  }, [symbol, brokerDays])

  useEffect(() => {
    setFundamentals(null)
    setFundamentalsLoaded(false)
    loadData()
  }, [loadData])

  useEffect(() => {
    if (activeTab === '籌碼日報') loadBroker()
  }, [activeTab, loadBroker])

  useEffect(() => {
    if (activeTab === '基本面分析' && !fundamentalsLoaded) {
      setFundamentalsLoaded(true)
      fetchFundamentals(symbol)
        .then(setFundamentals)
        .catch(() => setFundamentals(null))
    }
  }, [activeTab, symbol, fundamentalsLoaded])

  const latest = ohlcv[ohlcv.length - 1]
  const prev = ohlcv[ohlcv.length - 2]
  const change = latest && prev ? +(latest.close - prev.close).toFixed(2) : 0
  const changePct = prev ? +((change / prev.close) * 100).toFixed(2) : 0
  const isUp = change >= 0

  return (
    <div>
      {/* ── Price header ── */}
      <div className="flex items-start gap-4 mb-4 flex-wrap">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold">{symbol}</span>
            {latest && (
              <span className="text-3xl font-bold" style={{ color: isUp ? '#ef5350' : '#26a69a' }}>
                {latest.close.toFixed(2)}
              </span>
            )}
            {latest && prev && (
              <span className="text-sm font-semibold" style={{ color: isUp ? '#ef5350' : '#26a69a' }}>
                {isUp ? '▲' : '▼'} {Math.abs(change)} ({isUp ? '+' : ''}{changePct}%)
              </span>
            )}
          </div>
          {latest && (
            <div className="flex gap-4 mt-1 text-xs" style={{ color: '#8b949e' }}>
              <span>開 {latest.open}</span>
              <span>高 <span style={{ color: '#ef5350' }}>{latest.high}</span></span>
              <span>低 <span style={{ color: '#26a69a' }}>{latest.low}</span></span>
              <span>量 {latest.volume?.toLocaleString()} 張</span>
              <span>{latest.date}</span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-3 ml-auto flex-wrap">
          <MarketSummary />
          <div className="flex gap-1">
            {DAYS_OPTIONS.map(d => (
              <button
                key={d}
                onClick={() => setDays(d)}
                style={{
                  padding: '3px 10px',
                  borderRadius: 4,
                  fontSize: 12,
                  background: days === d ? '#1f6feb' : '#21262d',
                  color: days === d ? '#fff' : '#8b949e',
                  border: '1px solid #30363d',
                  cursor: 'pointer',
                }}
              >
                {d}日
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Error ── */}
      {error && (
        <div className="mb-4 p-3 rounded text-sm" style={{ background: '#3d1f1f', border: '1px solid #f85149', color: '#f85149' }}>
          {error}
        </div>
      )}

      {/* ── K-line chart ── */}
      <div style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 8 }} className="mb-2 p-2">
        {loading ? (
          <div className="flex items-center justify-center" style={{ height: 420, color: '#8b949e' }}>
            載入中...
          </div>
        ) : ohlcv.length ? (
          <KLineChart data={ohlcv} />
        ) : (
          <div className="flex items-center justify-center" style={{ height: 420, color: '#8b949e' }}>
            無K線資料
          </div>
        )}
      </div>

      {/* ── MA legend ── */}
      <div className="flex gap-4 mb-4 flex-wrap" style={{ padding: '0 2px' }}>
        {MA_LEGEND.map(([label, color]) => (
          <span key={label} className="flex items-center gap-1 text-xs" style={{ color: '#8b949e' }}>
            <span style={{ width: 16, height: 2, background: color, display: 'inline-block' }} />
            {label}
          </span>
        ))}
        <span className="flex items-center gap-1 text-xs" style={{ color: '#8b949e' }}>
          <span style={{ width: 12, height: 12, background: '#ef535055', display: 'inline-block', borderRadius: 2 }} />
          成交量
        </span>
      </div>

      {/* ── Tabs ── */}
      <div className="flex mb-0" style={{ borderBottom: '1px solid #30363d' }}>
        {TABS.map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              padding: '8px 16px',
              fontSize: 13,
              color: activeTab === tab ? '#58a6ff' : '#8b949e',
              borderBottom: activeTab === tab ? '2px solid #58a6ff' : '2px solid transparent',
              background: 'none',
              border: 'none',
              borderBottom: activeTab === tab ? '2px solid #58a6ff' : '2px solid transparent',
              cursor: 'pointer',
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* ── Tab content ── */}
      <div
        style={{ background: '#161b22', border: '1px solid #30363d', borderTop: 'none', borderRadius: '0 0 8px 8px' }}
        className="p-4"
      >
        {activeTab === '籌碼總覽' && (
          <ChipSummary institutional={institutional} margin={margin} />
        )}
        {activeTab === '籌碼日報' && (
          <BrokerReport
            data={broker}
            selectedDays={brokerDays}
            onDaysChange={d => setBrokerDays(d)}
          />
        )}
        {activeTab === '大戶散戶' && (
          <HolderChart shareholding={shareholding} ohlcv={ohlcv} />
        )}
        {activeTab === '三大法人' && (
          <InstitutionalChart data={institutional} />
        )}
        {activeTab === '融資融券' && (
          <MarginChart data={margin} />
        )}
        {activeTab === '基本面分析' && (
          <FundamentalPanel data={fundamentals} />
        )}
      </div>
    </div>
  )
}
