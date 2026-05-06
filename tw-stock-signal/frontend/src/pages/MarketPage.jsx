import NaaimWidget from '../components/NaaimWidget'

export default function MarketPage() {
  return (
    <div style={{ padding: 16 }}>
      <div style={{ marginBottom: 16 }}>
        <div className="text-xl font-bold mb-1" style={{ color: '#e6edf3' }}>
          市場情緒指標
        </div>
        <div className="text-xs" style={{ color: '#8b949e' }}>
          NAAIM Exposure Index — 主動型基金對美股的曝險比例，反映法人市場情緒
        </div>
      </div>

      <div
        style={{
          background: '#161b22',
          border: '1px solid #30363d',
          borderRadius: 8,
          overflow: 'hidden',
          padding: 12,
        }}
      >
        <div style={{ fontSize: 13, color: '#8b949e', marginBottom: 8 }}>
          NAAIM Exposure Index（週線）
        </div>
        <NaaimWidget />
      </div>
    </div>
  )
}
