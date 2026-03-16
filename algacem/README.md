# AlgaCem — Pond Intelligence Dashboard

## Run Locally

```bash
# 1. Go into the project folder
cd algacem

# 2. Create a virtual environment
python3 -m venv venv
source venv/bin/activate        # Mac/Linux
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the server
python app.py
```

Then open http://localhost:5000 in your browser.

---

## Deploy to Render

1. Push this folder to a GitHub repository
2. Go to https://render.com → New → Web Service
3. Connect your GitHub repo
4. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Environment:** Python 3
5. Click Deploy

The PORT variable is automatically handled by Render via `os.environ.get("PORT", 5000)`.

---

## Project Structure

```
algacem/
├── app.py              ← Flask backend + simulation physics
├── requirements.txt    ← Python dependencies
├── Procfile            ← Render/Heroku start command
├── README.md
└── templates/
    └── index.html      ← Full dashboard (Three.js + Chart.js)
```

## Modules

| Module | Description |
|--------|-------------|
| Overview | 3D interactive raceway farm with day/night cycle |
| Live Monitor | All 8 ponds with 10+ live parameters |
| CO₂ Optimizer | AI allocation recommendations from kiln output |
| Harvest Predictor | Logistic growth model, confidence bands, harvest calendar |
| Simulation Lab | Interactive sliders — real-time effect on pH, growth, O₂ |
| Carbon Ledger | CO₂ capture tracking, Heidelberg export |
| AI Briefing | Daily summary, actions, forecasts |
