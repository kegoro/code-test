const VERDICT_STYLE = {
  PASS:  { bg: '#1a3328', color: '#26a69a' },
  WATCH: { bg: '#332b00', color: '#ffd700' },
  AVOID: { bg: '#3d1f1f', color: '#ef5350' },
}

function Badge({ verdict }) {
  const style = VERDICT_STYLE[verdict] ?? { bg: '#21262d', color: '#8b949e' }
  return (
    <span style={{ background: style.bg, color: style.color, padding: '2px 10px', borderRadius: 4, fontSize: 11, fontWeight: 600 }}>
      {verdict ?? '—'}
    </span>
  )
}

function Row({ label, value, unit = '', decimals = 2, highlight }) {
  if (value == null) return null
  const display = typeof value === 'number' ? value.toFixed(decimals) : String(value)
  return (
    <div className="flex justify-between py-2" style={{ borderBottom: '1px solid #21262d' }}>
      <span style={{ color: '#8b949e', fontSize: 13 }}>{label}</span>
      <span style={{ fontSize: 13, color: highlight ?? '#e6edf3' }}>{display}{unit}</span>
    </div>
  )
}

function Section({ title, verdict, children }) {
  return (
    <div style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 8 }} className="p-4">
      <div className="flex justify-between items-center mb-3">
        <div className="font-semibold text-sm">{title}</div>
        <Badge verdict={verdict} />
      </div>
      {children}
    </div>
  )
}

export default function FundamentalPanel({ data }) {
  if (!data) {
    return (
      <div className="text-center py-12" style={{ color: '#8b949e' }}>
        <div className="text-4xl mb-3">📊</div>
        <div>無財務資料（可能為 ETF 或資料尚未載入）</div>
      </div>
    )
  }

  const { health, moat, valuation } = data

  return (
    <div className="grid gap-4" style={{ maxWidth: 640 }}>
      <Section title="第一層：財務健康度" verdict={health?.verdict}>
        <Row label="流動比率" value={health?.current_ratio}
          highlight={health?.current_ratio >= 2 ? '#26a69a' : health?.current_ratio >= 1 ? '#ffd700' : '#ef5350'} />
        <Row label="淨負債 / EBITDA" value={health?.debt_ebitda}
          highlight={health?.debt_ebitda <= 3 ? '#26a69a' : health?.debt_ebitda <= 5 ? '#ffd700' : '#ef5350'} />
        <Row label="自由現金流利潤率" value={health?.fcf_margin} unit="%"
          highlight={(health?.fcf_margin ?? 0) > 0 ? '#26a69a' : '#ef5350'} />
        <Row label="應收帳款趨勢" value={health?.ar_trend} />
        {health?.flags?.length > 0 && (
          <div className="mt-2">
            {health.flags.map((f, i) => (
              <div key={i} className="text-xs mt-1 flex items-start gap-1" style={{ color: '#ffd700' }}>
                <span>⚠</span><span>{f}</span>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="第二層：護城河競爭力" verdict={moat?.verdict}>
        <div className="flex items-center justify-between py-2" style={{ borderBottom: '1px solid #21262d' }}>
          <span style={{ color: '#8b949e', fontSize: 13 }}>護城河綜合評分</span>
          <div className="flex items-center gap-2">
            <div style={{ width: 80, height: 6, background: '#21262d', borderRadius: 3 }}>
              <div style={{
                width: `${Math.min(moat?.score ?? 0, 100)}%`,
                height: '100%',
                background: (moat?.score ?? 0) >= 60 ? '#26a69a' : (moat?.score ?? 0) >= 40 ? '#ffd700' : '#ef5350',
                borderRadius: 3,
              }} />
            </div>
            <span style={{ fontSize: 13, fontWeight: 700,
              color: (moat?.score ?? 0) >= 60 ? '#26a69a' : (moat?.score ?? 0) >= 40 ? '#ffd700' : '#ef5350' }}>
              {(moat?.score ?? 0).toFixed(0)} / 100
            </span>
          </div>
        </div>
        <Row label="毛利率趨勢 (斜率)" value={moat?.gm_trend} decimals={4} />
        <Row label="ROIC vs WACC (8%)" value={moat?.roic_vs_wacc} decimals={4}
          highlight={(moat?.roic_vs_wacc ?? 0) > 0 ? '#26a69a' : '#ef5350'} />
        <Row label="營收品質" value={moat?.revenue_quality} decimals={4} />
      </Section>

      {valuation && (
        <Section title="第三層：DCF 合理估值" verdict={valuation?.verdict}>
          <div className="grid grid-cols-3 gap-2 mt-2">
            {[
              ['空頭情境', valuation.bear, '#26a69a'],
              ['基本情境', valuation.base, '#ffd700'],
              ['多頭情境', valuation.bull, '#ef5350'],
            ].map(([label, val, color]) => (
              <div key={label} style={{ background: '#161b22', borderRadius: 6 }} className="p-3 text-center">
                <div className="text-xs mb-1" style={{ color: '#8b949e' }}>{label}</div>
                <div className="text-xl font-bold" style={{ color }}>
                  {val != null ? val.toFixed(0) : '—'}
                </div>
                <div className="text-xs" style={{ color: '#8b949e' }}>元</div>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  )
}
