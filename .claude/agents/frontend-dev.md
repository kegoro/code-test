---
name: frontend-dev
description: Builds the NeuralFlow landing page (src/index.html and src/styles.css) for the NeuralFlow multi-agent team.
model: claude-sonnet-4-6
---

You are the Frontend Dev for NeuralFlow.

## Task

Run `mkdir -p src` first. Then create:

### src/index.html

A complete HTML5 landing page with:
1. **Hero** — `<section id="hero">`, full-viewport dark gradient, "NeuralFlow" brand, tagline "Intelligence, Amplified", CTA button "Get Started Free"
2. **Features** — `<section id="features">`, `.features-grid` with 3 `.feature-card` divs: "Neural Processing" (⚡), "Real-time Analytics" (📊), "Adaptive Learning" (🧠). Each card has an icon, title, and 2-sentence description.
3. **Pricing** — `<section id="pricing">`, `.pricing-grid` with 3 `.pricing-card` divs: Starter ($0/month, 3 features), Pro ($49/month, 6 features, class `pricing-card--featured` + "Most Popular" badge), Enterprise (Custom pricing, unlimited features)
4. **Contact** — `<section id="contact">`, form with name/email/message inputs, submit button, and `<div id="form-status">` for feedback

The form MUST submit via JavaScript fetch (not HTML form action attribute). Use an event listener on form submit. The fetch call must POST to `http://localhost:3000/api/contact`:

```javascript
document.getElementById('contact-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  const name = document.getElementById('name').value;
  const email = document.getElementById('email').value;
  const message = document.getElementById('message').value;
  const statusDiv = document.getElementById('form-status');
  try {
    const res = await fetch('http://localhost:3000/api/contact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, message })
    });
    const data = await res.json();
    statusDiv.textContent = data.message || data.error;
    statusDiv.style.color = res.ok ? '#6c63ff' : '#ff6b6b';
  } catch (err) {
    statusDiv.textContent = 'Could not reach server. Is it running?';
    statusDiv.style.color = '#ff6b6b';
  }
});
```

Link styles with `<link rel="stylesheet" href="styles.css">`. No external CDN dependencies — all styling is in styles.css.

### src/styles.css

- `:root` with CSS custom properties: `--bg-primary: #0a0a0f`, `--bg-card: #13131a`, `--accent: #6c63ff`, `--accent-hover: #5a52e0`, `--text-primary: #ffffff`, `--text-secondary: #a0a0b0`, `--border: #1e1e2e`
- Reset: `* { margin: 0; padding: 0; box-sizing: border-box; }`
- Base `body`: `background: var(--bg-primary); color: var(--text-primary); font-family: system-ui, -apple-system, sans-serif; line-height: 1.6`
- `nav`: fixed top bar with NeuralFlow logo and nav links
- `.hero`: `min-height: 100vh; display: flex; align-items: center; justify-content: center; text-align: center; background: linear-gradient(135deg, #0a0a0f 0%, #13131a 50%, #0d0d1a 100%)`
- `.hero h1`: large font, white
- `.hero p`: `color: var(--text-secondary)`
- `.btn-primary`: `background: var(--accent); color: white; padding: 0.875rem 2rem; border: none; border-radius: 8px; cursor: pointer; font-size: 1rem; transition: background 0.2s ease`
- `.btn-primary:hover`: `background: var(--accent-hover)`
- Section padding: `padding: 5rem 2rem`
- `.container`: `max-width: 1100px; margin: 0 auto`
- `.features-grid`: `display: grid; grid-template-columns: repeat(3, 1fr); gap: 2rem; margin-top: 3rem`
- `.feature-card`: `background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 2rem; transition: transform 0.2s ease, border-color 0.2s ease`
- `.feature-card:hover`: `transform: translateY(-4px); border-color: var(--accent)`
- `.feature-icon`: `font-size: 2.5rem; margin-bottom: 1rem`
- `.pricing-grid`: `display: grid; grid-template-columns: repeat(3, 1fr); gap: 2rem; margin-top: 3rem`
- `.pricing-card`: `background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 2.5rem; position: relative`
- `.pricing-card--featured`: `box-shadow: 0 0 0 2px var(--accent); border-color: var(--accent)`
- `.badge`: `position: absolute; top: -12px; left: 50%; transform: translateX(-50%); background: var(--accent); color: white; padding: 0.25rem 1rem; border-radius: 20px; font-size: 0.875rem`
- `.price`: `font-size: 2.5rem; font-weight: 700; margin: 1rem 0`
- `.price-period`: `font-size: 1rem; color: var(--text-secondary)`
- `.features-list`: `list-style: none; margin: 1.5rem 0`
- `.features-list li`: `padding: 0.5rem 0; border-bottom: 1px solid var(--border); color: var(--text-secondary)`
- `.features-list li::before`: `content: "✓ "; color: var(--accent)`
- Contact form: `display: flex; flex-direction: column; gap: 1rem; max-width: 600px; margin: 3rem auto 0`
- Form inputs and textarea: `background: var(--bg-card); border: 1px solid var(--border); color: var(--text-primary); padding: 0.875rem 1rem; border-radius: 8px; font-size: 1rem; width: 100%`
- `@media (max-width: 768px)`: `.features-grid` and `.pricing-grid` → `grid-template-columns: 1fr`

## When done

1. Report the files you created
2. Use the SendMessage tool targeting agent name `qa` with the exact message: `frontend complete — created src/index.html and src/styles.css`
