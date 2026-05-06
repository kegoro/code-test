import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useState } from 'react'

export default function Layout({ children }) {
  const [search, setSearch] = useState('')
  const navigate = useNavigate()
  const location = useLocation()

  const handleSearch = (e) => {
    e.preventDefault()
    const sym = search.trim()
    if (sym) {
      navigate(`/stock/${sym}`)
      setSearch('')
    }
  }

  const isCurated = location.pathname === '/curated'
  const isScreener = location.pathname === '/screener'

  const navItems = [
    { path: '/curated',  label: '精選' },
    { path: '/screener', label: '選股工具' },
    { path: '/market',   label: '市場情緒' },
  ]

  return (
    <div className="min-h-screen flex flex-col" style={{ background: '#0d1117' }}>
      <header
        style={{ background: '#161b22', borderBottom: '1px solid #30363d' }}
        className="px-4 py-2 flex items-center gap-4 flex-wrap"
      >
        <Link to="/curated" className="text-lg font-bold" style={{ color: '#58a6ff', textDecoration: 'none' }}>
          📊 籌碼K線
        </Link>

        <form onSubmit={handleSearch} className="flex gap-2">
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="輸入股票代碼，如 2330"
            className="px-3 py-1 rounded text-sm"
            style={{
              background: '#0d1117',
              border: '1px solid #30363d',
              color: '#e6edf3',
              width: 220,
              outline: 'none',
            }}
          />
          <button
            type="submit"
            className="px-3 py-1 rounded text-sm font-medium"
            style={{ background: '#238636', color: '#fff', border: 'none', cursor: 'pointer' }}
          >
            查詢
          </button>
        </form>

        <nav className="flex gap-1 ml-2">
          {navItems.map(({ path, label }) => {
            const active = location.pathname === path
            return (
              <Link
                key={path}
                to={path}
                className="px-3 py-1 rounded text-sm"
                style={{
                  color: active ? '#e6edf3' : '#8b949e',
                  background: active ? '#21262d' : 'transparent',
                  textDecoration: 'none',
                }}
              >
                {label}
              </Link>
            )
          })}
        </nav>
      </header>

      <main
        className="flex-1 max-w-screen-2xl mx-auto w-full"
        style={{ padding: isCurated ? 0 : '16px' }}
      >
        {children}
      </main>
    </div>
  )
}
