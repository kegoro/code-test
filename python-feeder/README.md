# Tick Feeder

Mock WebSocket server for the Quant Terminal real-time microstructure pipeline.
Future: replace with a Shioaji / IB / Polygon adapter; the wire protocol
(`{symbol, price, volume, is_buy, timestamp}`) stays identical.

## Setup

```powershell
cd python-feeder
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Health check: <http://localhost:8000/health>
WebSocket:    `ws://localhost:8000/ws/ticks/2382`

## Wire format

Each frame is a single JSON object:

```json
{
  "symbol": "2382",
  "price": 285.42,
  "volume": 27,
  "is_buy": true,
  "timestamp": 1746540123456
}
```

- `price` — float, round to 2 decimals
- `volume` — int, lots / shares
- `is_buy` — boolean, taker side (true = aggressive buy / uptick)
- `timestamp` — int, ms epoch
