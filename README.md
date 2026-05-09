# Wayfinder AI

An AI-powered travel planning app built with Flask. Users submit a trip request and an agentic backend pipeline assembles a full curated itinerary — including lodging, meals, activities, weather, transit routes, local events, and cultural facts — displayed on a live dashboard.

## Project Status

- ✅ Trip submission form
- ✅ Agentic worker pipeline (weather, places, transit, culture, events)
- ✅ AI supervisor (Groq / LLaMA 3.3) — generates and updates trip plans
- ✅ Live dashboard with Google Maps, itinerary panel, and chat assistant
- ✅ Postgres database (Render)
- ✅ Email alerts for high-severity travel warnings

---

## Tech Stack

- Python 3.12
- Flask + Flask-SQLAlchemy
- Groq API (LLaMA 3.3 70B) — AI supervisor
- Google Maps JavaScript API — dashboard map
- Google Places API — nearby locations
- Google Routes API — transit directions
- Open-Meteo API — weather (no key required)
- Render Postgres — production database
- python-dotenv — configuration

---

## Local Setup — macOS

### 1. Clone the repo

```bash
git clone git@github.com:mjmaho19/Wayfinder_AI.git
cd Wayfinder_AI
```

### 2. Create and activate virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your own API keys:

```
GROQ_API_KEY=your-groq-api-key
FLASK_KEY=your-secret-key
DATABASE_URL=your-database-url
GOOGLE_PLACES_API_KEY=your-google-places-api-key
OPENAI_API_KEY=your-groq-api-key
NEWS_API_KEY=news-api-key
RESEND_API_KEY=resend-api-key
EMAIL_ENABLED=true
EMAIL_FROM=application-name <onboarding@resend.dev>
MY_EMAIL=your-resend-email
ROUTES_API_KEY=your-google-routes-api-key
GOOGLE_MAPS_API_KEY=google-maps-api-key
```

### 5. Run the Flask app

```bash
python -m flask --app index run --debug
```

### 6. In a second terminal, run the worker

```bash
PYTHONPATH=. python workers/run_worker.py
```

Open in browser:
👉 http://127.0.0.1:5000

---

## Local Setup — Windows (PowerShell)

### 1. Clone the repo

```powershell
git clone https://github.com/mjmaho19/Wayfinder_AI.git
cd Wayfinder_AI
```

### 2. Create and activate virtual environment

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

If PowerShell blocks the script with an execution policy error, run this first:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env` and fill in your own API keys:

```
GROQ_API_KEY=your-groq-api-key
FLASK_KEY=your-secret-key
DATABASE_URL=your-database-url
GOOGLE_PLACES_API_KEY=your-google-places-api-key
OPENAI_API_KEY=your-groq-api-key
NEWS_API_KEY=news-api-key
RESEND_API_KEY=resend-api-key
EMAIL_ENABLED=true
EMAIL_FROM=application-name <onboarding@resend.dev>
MY_EMAIL=your-resend-email
ROUTES_API_KEY=your-google-routes-api-key
GOOGLE_MAPS_API_KEY=google-maps-api-key
```

### 5. Run the Flask app

```powershell
python -m flask --app index run --debug
```

### 6. In a second terminal, run the worker

```powershell
$env:PYTHONPATH="."; python workers/run_worker.py
```

Open in browser:
👉 http://127.0.0.1:5000

---

## How It Works

1. User submits a trip request (origin, destination, dates, budget, preferences)
2. The worker picks up the submission and dispatches tool tasks (weather, places, transit, culture, events)
3. After each tool result arrives, a supervisor task runs — the AI supervisor reads all available data and produces or updates the curated itinerary
4. The dashboard polls `/api/latest` every 3 seconds and renders the plan live as it assembles
5. Users can chat with the travel assistant or request plan edits directly from the dashboard

---

## API Keys

Each team member or contributor needs to obtain their own API keys and add them to a local `.env` file. Keys are never committed to the repo.

| Key | Where to get it |
|---|---|
| `GROQ_API_KEY` | https://console.groq.com |
| `GOOGLE_PLACES_API_KEY` | https://console.cloud.google.com |
| `ROUTES_API_KEY` | https://console.cloud.google.com (Routes API) |
| `DATABASE_URL` | Your Render Postgres instance, or a local Postgres URL |

---

## Team

- **Michael Mahoney** — maintainer
- **Edgar Falfan** — contributor

---

## License

Private project – all rights reserved.
