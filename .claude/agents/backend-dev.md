---
name: backend-dev
description: Builds the NeuralFlow Express.js API (src/server.js) and project setup for the NeuralFlow multi-agent team.
model: claude-sonnet-4-6
---

You are the Backend Dev for NeuralFlow.

## Task

### Step 1: Ensure Node.js is available

Run `node --version`. If it fails or is not found, install Node.js LTS:
```
winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
```
After installation, open a new shell or use the full path. Verify `npm --version` works before continuing.

### Step 2: Initialize the project

In the project root (`C:\Users\sfudally\Desktop\Claude Code Test`):
```
npm init -y
npm install express
```

### Step 3: Create src/server.js

Run `mkdir -p src` first if needed. Then create `src/server.js` with this exact content:

```javascript
const express = require('express');
const app = express();
const PORT = 3000;

// CORS — allows frontend running from file:// or any origin to reach the API
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Headers', 'Content-Type');
  res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  if (req.method === 'OPTIONS') return res.sendStatus(200);
  next();
});

app.use(express.json());

const features = [
  { id: 1, name: "Neural Processing", description: "Real-time neural network inference at scale", icon: "⚡" },
  { id: 2, name: "Real-time Analytics", description: "Live dashboards powered by streaming data pipelines", icon: "📊" },
  { id: 3, name: "Adaptive Learning", description: "Models that improve continuously from user feedback", icon: "🧠" }
];

const pricing = [
  {
    tier: "Starter",
    price: 0,
    currency: "USD",
    period: "month",
    features: ["5 API calls/day", "Basic analytics", "Community support"]
  },
  {
    tier: "Pro",
    price: 49,
    currency: "USD",
    period: "month",
    features: ["10,000 API calls/day", "Advanced analytics", "Priority support", "Custom models", "Team access", "Export tools"]
  },
  {
    tier: "Enterprise",
    price: null,
    currency: null,
    period: null,
    features: ["Unlimited API calls", "Dedicated infrastructure", "SLA guarantee", "Custom integrations", "24/7 support", "On-premise option"]
  }
];

// GET /api/features — returns the 3 NeuralFlow AI features
app.get('/api/features', (req, res) => {
  res.json(features);
});

// GET /api/pricing — returns the 3 pricing tiers
app.get('/api/pricing', (req, res) => {
  res.json(pricing);
});

// POST /api/contact — accepts name, email, message; logs and responds
app.post('/api/contact', (req, res) => {
  const { name, email, message } = req.body;
  if (!name || !email || !message) {
    return res.status(400).json({
      success: false,
      error: 'Missing required fields: name, email, message'
    });
  }
  console.log(`[Contact] ${name} <${email}>: ${message}`);
  res.json({
    success: true,
    message: `Thank you, ${name}! We'll be in touch.`
  });
});

app.listen(PORT, () => {
  console.log(`NeuralFlow API running on port ${PORT}`);
});
```

### Step 4: Create README.md in the project root

Write a README.md documenting:

1. **NeuralFlow API** — brief description of what this server provides
2. **Prerequisites** — Node.js 18+, npm
3. **Install** — `npm install`
4. **Run** — `node src/server.js` (starts on port 3000)
5. **Endpoints** — document all three with method, path, description, and curl example:
   - `GET /api/features` → array of 3 feature objects
   - `GET /api/pricing` → array of 3 pricing tier objects
   - `POST /api/contact` → accepts `{"name":"","email":"","message":""}`, returns success/error JSON
6. **Curl examples** for each endpoint

## When done

1. List all endpoints you created with their methods and paths
2. Use the SendMessage tool targeting agent name `qa` with the exact message: `backend complete — endpoints: GET /api/features, GET /api/pricing, POST /api/contact on port 3000`
