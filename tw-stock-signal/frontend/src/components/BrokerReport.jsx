import { useState, useMemo } from 'react'

const DAYS_BTN = [1, 3, 5, 10, 20, 60, 120, 240]

function BrokerTable({ rows, side }) {
  const isBuy = side === 'buy'
  return (
    <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
      <thead>
        <tr style={{ borderBottom: '1px solid #30363d' }}>
          <th style={{ padding: '6px 8px', textAlign: 'left', color: '#8b949e', fontWeight: 500 }}>券商</th>
          <th style={{ padding: '6px 8px', textAlign: 'right', color: '#8b949e', fontWeight: 500 }}>
            {isBuy ? '買超(張)' : '賣超(張)'}
          </th>
          <th style={{ padding: '6px 8px', textAlign: 'right', color: '#8b949e', fontWeight: 500 }}>
            {isBuy ? '賣均價' : '買均價'}
          </th>
          <th style={{ padding: '6px 8px', textAlign: 'right', color: '#8b949e', fontWeight: 500 }}>損益(萬)</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => {
          const netAbs = Math.abs(row.net)
          const avgPrice = isBuy ? row.sell_price : row.buy_price
          const pnl = isBuy
            ? (row.sell_price - row.buy_price) * row.buy / 1000
            : (row.buy_price - row.sell_price) * row.sell / 1000
          const pnlColor = pnl >= 0 ? '#ef5350' : '#26a69a'
          const netColor = isBuy ? '#ef5350' : '#26a69a'
          return (
            <tr key={i} style={{ borderBottom: '1px solid #21262d' }}>
              <td style={{ padding: '6px 8px', color: '#e6edf3' }}>{row.broker_name}</td>
              <td style={{ padding: '6px 8px', textAlign: 'right', color: netColor, fontWeight: 600 }}>
                {netAbs.toLocaleString()}
              </td>
              <td style={{ padding: '6px 8px', textAlign: 'right', color: '#8b949e' }}>
                {avgPrice > 0 ? avgPrice.toFixed(2) : '-'}
              </td>
              <td style={{ padding: '6px 8px', textAlign: 'right', color: pnlColor, fontWeight: 600 }}>
                {avgPrice > 0 ? `${pnl >= 0 ? '+' : ''}${pnl.toFixed(1)}` : '-'}
              </td>
            </tr>
          )
        })}
        {rows.length === 0 && (
          <tr>
            <td colSpan={4} style={{ padding: '16px 8px', textAlign: 'center', color: '#8b949e' }}>
              無資料
            </td>
          </tr>
        )}
      </tbody>
    </table>
  )
}

export default function BrokerReport({ data, selectedDays, onDaysChange }) {
  const [activeTab, setActiveTab] = useState('buy')

  const { latestDate, buyTop15, sellTop15, stats } = useMemo(() => {
    if (!data?.length) return { latestDate: null, buyTop15: [], sellTop15: [], stats: {} }

    const dates = [...new Set(data.map(d => d.date))].sort()
    const latestDate = dates[dates.length - 1]

    const brokerMap = {}
    data.forEach(row => {
      const key = row.broker_id || row.broker_name
      if (!brokerMap[key]) {
        brokerMap[key] = {
          broker_id: row.broker_id,
          broker_name: row.broker_name,
          buy: 0, sell: 0, net: 0,
          buy_price_sum: 0, buy_count: 0,
          sell_price_sum: 0, sell_count: 0,
        }
      }
      brokerMap[key].buy += row.buy
      brokerMap[key].sell += row.sell
      brokerMap[key].net += row.net
      if (row.buy_price > 0) {
        brokerMap[key].buy_price_sum += row.buy_price * row.buy
        brokerMap[key].buy_count += row.buy
      }
      if (row.sell_price > 0) {
        brokerMap[key].sell_price_sum += row.sell_price * row.sell
        brokerMap[key].sell_count += row.sell
      }
    })

    const brokers = Object.values(brokerMap).map(b => ({
      ...b,
      buy_price: b.buy_count > 0 ? b.buy_price_sum / b.buy_count : 0,
      sell_price: b.sell_count > 0 ? b.sell_price_sum / b.sell_count : 0,
    }))

    const buyers = brokers.filter(b => b.net > 0).sort((a, b) => b.net - a.net).slice(0, 15)
    const sellers = brokers.filter(b => b.net < 0).sort((a, b) => a.net - b.net).slice(0, 15)

    const totalBuy = buyers.reduce((s, b) => s + b.net, 0)
    const totalSell = sellers.reduce((s, b) => s + Math.abs(b.net), 0)

    return {
      latestDate,
      buyTop15: buyers,
      sellTop15: sellers,
      stats: { totalBuy, totalSell },
    }
  }, [data])

  const tabStyle = (t) => ({
    padding: '8px 20px',
    fontSize: 13,
    fontWeight: 600,
    color: activeTab === t ? '#e6edf3' : '#8b949e',
    background: activeTab === t ? '#21262d' : 'transparent',
    border: 'none',
    borderRadius: '6px 6px 0 0',
    cursor: 'pointer',
    borderBottom: activeTab === t ? '2px solid #58a6ff' : '2px solid transparent',
  })

  return (
    <div>
      {/* 統計天數選擇 */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <span style={{ fontSize: 12, color: '#8b949e' }}>統計天數</span>
        <div className="flex gap-1 flex-wrap">
          {DAYS_BTN.map(d => (
            <button
              key={d}
              onClick={() => onDaysChange(d)}
              style={{
                padding: '3px 10px',
                borderRadius: 4,
                fontSize: 12,
                background: selectedDays === d ? '#1f6feb' : '#21262d',
                color: selectedDays === d ? '#fff' : '#8b949e',
                border: '1px solid #30363d',
                cursor: 'pointer',
              }}
            >
              {d}
            </button>
          ))}
        </div>
        {latestDate && (
          <span style={{ fontSize: 11, color: '#8b949e', marginLeft: 'auto' }}>
            最新資料：{latestDate}
          </span>
        )}
      </div>

      {/* 摘要卡片 */}
      {data?.length > 0 && (
        <div className="flex gap-3 mb-4 flex-wrap">
          <div style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 8, padding: '10px 16px', flex: 1, minWidth: 140 }}>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>買超合計（前15）</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: '#ef5350' }}>
              +{(stats.totalBuy / 1000).toFixed(1)} 千張
            </div>
          </div>
          <div style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 8, padding: '10px 16px', flex: 1, minWidth: 140 }}>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>賣超合計（前15）</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: '#26a69a' }}>
              -{(stats.totalSell / 1000).toFixed(1)} 千張
            </div>
          </div>
        </div>
      )}

      {/* 買方/賣方 Tab */}
      <div style={{ borderBottom: '1px solid #30363d', marginBottom: 0 }}>
        <button style={tabStyle('buy')} onClick={() => setActiveTab('buy')}>買方 Top15</button>
        <button style={tabStyle('sell')} onClick={() => setActiveTab('sell')}>賣方 Top15</button>
      </div>

      <div style={{ background: '#0d1117', border: '1px solid #21262d', borderTop: 'none', borderRadius: '0 0 8px 8px', padding: '8px 0' }}>
        {!data?.length ? (
          <div style={{ textAlign: 'center', color: '#8b949e', padding: 32, fontSize: 13 }}>
            無券商資料（FinMind 需付費方案）
          </div>
        ) : activeTab === 'buy' ? (
          <BrokerTable rows={buyTop15} side="buy" />
        ) : (
          <BrokerTable rows={sellTop15} side="sell" />
        )}
      </div>
    </div>
  )
}
