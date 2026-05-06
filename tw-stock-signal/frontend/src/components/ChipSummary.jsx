const INST_NAMES = ['外資', '投信', '自營商']
const INST_COLORS = { '外資': '#2196F3', '投信': '#FF9800', '自營商': '#CE93D8' }

function Card({ label, value, color, sub }) {
  return (
    <div
      style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 8 }}
      className="p-4"
    >
      <div className="text-xs mb-1" style={{ color: '#8b949e' }}>{label}</div>
      <div className="text-xl font-bold" style={{ color }}>{value}</div>
      {sub && <div className="text-xs mt-1" style={{ color: '#8b949e' }}>{sub}</div>}
    </div>
  )
}

function getVal(row, ...keys) {
  for (const k of keys) {
    if (row[k] != null) return row[k]
  }
  return 0
}

export default function ChipSummary({ institutional, margin }) {
  const instSums = {}
  if (institutional?.length) {
    INST_NAMES.forEach(name => {
      const rows = institutional.filter(d => d.name === name).slice(-5)
      instSums[name] = rows.reduce((s, d) => s + (d.net || 0), 0)
    })
  }

  const totalForeign = institutional
    ?.filter(d => d.name === '外資')
    .slice(-20)
    .reduce((s, d) => s + (d.net || 0), 0) ?? 0

  const latest = margin?.slice(-1)[0]
  const marginBal = latest ? getVal(latest, 'margin_balance', 'MarginPurchaseBalance') : 0
  const shortBal = latest ? getVal(latest, 'short_balance', 'ShortSaleBalance') : 0
  const marginRatio = marginBal > 0 ? ((shortBal / marginBal) * 100).toFixed(1) + '%' : 'N/A'

  return (
    <div>
      <div className="text-sm font-semibold mb-3" style={{ color: '#8b949e' }}>法人籌碼概覽</div>
      <div className="grid grid-cols-2 gap-3 mb-6" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))' }}>
        {INST_NAMES.map(name => {
          const val = instSums[name] ?? 0
          const isPos = val > 0
          const color = isPos ? '#ef5350' : '#26a69a'
          return (
            <Card
              key={name}
              label={`${name} 近5日累積`}
              value={`${isPos ? '+' : ''}${(val / 1000).toFixed(1)} 千張`}
              color={color}
            />
          )
        })}
        <Card
          label="外資 近20日累積"
          value={`${totalForeign >= 0 ? '+' : ''}${(totalForeign / 1000).toFixed(1)} 千張`}
          color={totalForeign >= 0 ? '#ef5350' : '#26a69a'}
        />
        {latest && (
          <>
            <Card
              label="融資餘額"
              value={`${(marginBal / 1000).toFixed(0)} 千張`}
              color="#ffd700"
            />
            <Card
              label="融券餘額"
              value={`${(shortBal / 1000).toFixed(0)} 千張`}
              color="#ab47bc"
            />
            <Card
              label="券資比"
              value={marginRatio}
              color="#8b949e"
              sub="融券 ÷ 融資"
            />
          </>
        )}
      </div>

      {institutional?.length > 0 && (
        <div>
          <div className="text-sm font-semibold mb-2" style={{ color: '#8b949e' }}>最近5筆法人買賣紀錄</div>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #30363d' }}>
                {['日期', '機構', '買進', '賣出', '買賣超'].map(h => (
                  <th key={h} style={{ padding: '6px 8px', textAlign: 'left', color: '#8b949e', fontWeight: 500 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {institutional.slice(-15).reverse().map((row, i) => {
                const net = row.net ?? 0
                return (
                  <tr key={i} style={{ borderBottom: '1px solid #21262d' }}>
                    <td style={{ padding: '5px 8px', color: '#8b949e' }}>{row.date}</td>
                    <td style={{ padding: '5px 8px', color: INST_COLORS[row.name] ?? '#e6edf3' }}>{row.name}</td>
                    <td style={{ padding: '5px 8px' }}>{(row.buy / 1000).toFixed(0)} 千</td>
                    <td style={{ padding: '5px 8px' }}>{(row.sell / 1000).toFixed(0)} 千</td>
                    <td style={{ padding: '5px 8px', color: net >= 0 ? '#ef5350' : '#26a69a', fontWeight: 600 }}>
                      {net >= 0 ? '+' : ''}{(net / 1000).toFixed(0)} 千
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
