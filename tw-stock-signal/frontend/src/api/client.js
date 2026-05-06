import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export const fetchOHLCV = (symbol, days = 120) =>
  api.get(`/stock/${symbol}/ohlcv`, { params: { days } }).then(r => r.data)

export const fetchInstitutional = (symbol, days = 60) =>
  api.get(`/stock/${symbol}/institutional`, { params: { days } }).then(r => r.data)

export const fetchMargin = (symbol, days = 60) =>
  api.get(`/stock/${symbol}/margin`, { params: { days } }).then(r => r.data)

export const fetchShareholding = (symbol, days = 180) =>
  api.get(`/stock/${symbol}/shareholding`, { params: { days } }).then(r => r.data)

export const fetchFundamentals = (symbol) =>
  api.get(`/stock/${symbol}/fundamentals`).then(r => r.data)

export const fetchBroker = (symbol, days = 60) =>
  api.get(`/stock/${symbol}/broker`, { params: { days } }).then(r => r.data)

export const fetchMarketSummary = () =>
  api.get('/market/summary').then(r => r.data)

export const fetchScreener = (params) =>
  api.get('/screener', { params }).then(r => r.data)
