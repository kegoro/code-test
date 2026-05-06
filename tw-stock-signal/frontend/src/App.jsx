import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import StockPage from './pages/StockPage'
import ScreenerPage from './pages/ScreenerPage'
import CuratedPage from './pages/CuratedPage'
import MarketPage from './pages/MarketPage'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/curated" replace />} />
        <Route path="/stock/:symbol" element={<StockPage />} />
        <Route path="/screener" element={<ScreenerPage />} />
        <Route path="/curated" element={<CuratedPage />} />
        <Route path="/market" element={<MarketPage />} />
      </Routes>
    </Layout>
  )
}
