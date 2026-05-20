# Wayfinder AI

Wayfinder AI is an agentic travel planning application built with Flask, PostgreSQL, asynchronous workers, deterministic API tools, and large language model agents. A traveler submits a trip request, the backend gathers real-world travel data, and an AI supervisor progressively builds a grounded itinerary that can be refined through a chat assistant.

The system is designed around persistent workflow state, asynchronous execution, and agentic orchestration rather than a single blocking request-response pipeline.

---

## Project Status

- ✅ Trip submission form
- ✅ Agentic worker pipeline
- ✅ Deterministic tools for weather, places, transit, culture, events, and alerts
- ✅ AI supervisor (Groq / LLaMA 3.3) for itinerary generation and refinement
- ✅ Chat assistant for itinerary Q&A and trip edits
- ✅ Live dashboard with itinerary display, Google Maps, and progress updates
- ✅ PostgreSQL database with Flask-Migrate migrations
- ✅ Email alerts for significant destination-specific travel disruptions

---

## Core Features

- Submit a trip request with destination, dates, budget, and preferences
- Run tool tasks asynchronously without blocking the web app
- Store submissions, tasks, tool results, plans, and edits in PostgreSQL
- Generate grounded itineraries from real API/tool outputs
- Refine trips conversationally through the chat assistant
- Display itinerary progress live through the dashboard
- Enrich itineraries with culture and event information
- Monitor destination-specific travel alerts and send email notifications

---

## Tech Stack

- Python 3.12
- Flask
- Flask-SQLAlchemy
- Flask-Migrate
- PostgreSQL
- Groq API (LLaMA 3.3 70B) for AI supervisor / chat
- Open-Meteo API for weather
- Google Places API for points of interest
- Google Routes API for transit
- Google Maps JavaScript API for map display
- News API for destination alerts
- Ticketmaster Discovery API for events
- Resend for email notifications
- `python-dotenv` for local configuration

---

## Repository Structure

```text
Wayfinder_AI/
├── agents/              # AI supervisor and chat agent
├── tools/               # Weather, places, transit, culture, events, alerts, email alert tools
├── workers/             # Background worker
├── templates/           # Flask templates / dashboard UI
├── tests/               # Automated tests
├── migrations/          # Flask-Migrate / Alembic migrations
├── docs/                # Generated pydoc HTML documentation
├── index.py             # Flask app + models + routes
└── requirements.txt
````

---

## Environment Variables

Not every key is required for every feature. The table below explains what is needed for basic local development and what features depend on each variable.

| Variable                | Required for basic app startup? | Purpose                                     | What breaks if missing                                |
| ----------------------- | ------------------------------: | ------------------------------------------- | ----------------------------------------------------- |
| `FLASK_KEY`             |                             Yes | Flask secret key                            | App should not be run without it                      |
| `DATABASE_URL`          |                             Yes | PostgreSQL connection string                | App / worker cannot start                             |
| `GROQ_API_KEY`          |                             Yes | AI supervisor and chat agent                | Planning and chat will fail                           |
| `GOOGLE_PLACES_API_KEY` |                             Yes | Places tool                                 | Place recommendations / itinerary grounding will fail |
| `ROUTES_API_KEY`        |                             Yes | Transit tool                                | Transit planning will fail                            |
| `GOOGLE_MAPS_API_KEY`   |       Yes for full dashboard UI | Google Maps JavaScript map                  | Map will not load on dashboard                        |
| `NEWS_API_KEY`          |                        Optional | Alerts tool                                 | Destination alerts will fail or return empty          |
| `RESEND_API_KEY`        |                        Optional | Email sending                               | Email alerts will not send                            |
| `EMAIL_ENABLED`         |                        Optional | Enables email notifications                 | Email notifications stay disabled                     |
| `EMAIL_FROM`            |                        Optional | Sender identity for Resend                  | Email alerts will fail                                |
| `MY_EMAIL`              |      Optional / dev convenience | Test recipient address                      | Testing email flow may be harder                      |
| `TICKETMASTER_API_KEY`  |                        Optional | Events tool                                 | Event discovery will fail or return empty             |
| `OPENAI_API_KEY`        |                       Optional* | Legacy compatibility alias in some branches | Usually not needed if `GROQ_API_KEY` is used directly |

* Some branches or older code may still reference `OPENAI_API_KEY` as a compatibility variable for the Groq OpenAI-compatible client.

### Recommended minimum variables for basic testing

For a minimal working setup, start with:

```env
FLASK_KEY=change-me
DATABASE_URL=the-hosted-postgresql-url-provided-separately
GROQ_API_KEY=your-groq-api-key
GOOGLE_PLACES_API_KEY=your-google-places-api-key
ROUTES_API_KEY=your-google-routes-api-key
GOOGLE_MAPS_API_KEY=your-google-maps-api-key
```

### Optional event / alert / email variables

```env
NEWS_API_KEY=your-news-api-key
TICKETMASTER_API_KEY=your-ticketmaster-api-key
RESEND_API_KEY=your-resend-api-key
EMAIL_ENABLED=true
EMAIL_FROM=Wayfinder AI <onboarding@resend.dev>
MY_EMAIL=your-email@example.com
```
---
## Database Setup

Wayfinder AI was developed and tested using a **hosted PostgreSQL database on Render**, not a local database. The application is designed to connect to PostgreSQL through the `DATABASE_URL` environment variable in `.env`.

This means:

- the PostgreSQL **server** must already exist
- the PostgreSQL **database** must already exist
- `DATABASE_URL` tells Flask-SQLAlchemy and the worker which database to use
- `flask --app index db upgrade` applies the project schema to that database

The application does **not** create a PostgreSQL server by itself. Instead:

1. `index.py` defines the SQLAlchemy models for the application tables
2. `DATABASE_URL` tells Flask-SQLAlchemy which PostgreSQL database to connect to
3. Flask-Migrate / Alembic reads the migration files in the `migrations/` folder
4. `flask --app index db upgrade` creates or updates the corresponding tables in the target database

### How the database models in `index.py` relate to setup

The models in `index.py` define the application schema. These include tables such as:

- `WayfinderSubmission`
- `AgentTask`
- `ToolResult`
- `TripPlan`
- `PlanEdit`

Those classes describe the structure of the tables, but they do **not** create a PostgreSQL server on their own. The tables only become real PostgreSQL tables when migrations are run against the database referenced by `DATABASE_URL`.

In practical terms:

- `index.py` defines the tables
- `DATABASE_URL` points to the database
- `flask --app index db upgrade` initializes the tables in that database

### Database setup actually used for this project

The actual development setup for Wayfinder AI used a **hosted PostgreSQL database on Render**. That is the primary setup used during development and testing.

The development workflow was:

1. create a PostgreSQL database on Render
2. copy the database URL provided by Render
3. place that URL in `.env` as `DATABASE_URL`
4. run migrations with `flask --app index db upgrade`
5. run the Flask app
6. run the worker
7. make sure both the Flask app and worker use the same `.env` file so they connect to the same database

---

### Option 1 — Hosted PostgreSQL database on Render (the setup used for this project)

This is the setup that was actually used during development and testing.

#### 1. Create a PostgreSQL database on Render

1. Go to [https://render.com](https://render.com)
2. Sign in or create an account
3. Open the Render dashboard
4. Click **New**
5. Select **PostgreSQL**
6. Enter the required database information, such as:
   - database name
   - user
   - region
   - plan
7. Create the database

Once Render finishes provisioning the database, it will provide connection details.

#### 2. Copy the database connection URL from Render

In the Render PostgreSQL dashboard, locate the database connection information and copy the **External Database URL**.

That URL is what Wayfinder AI uses for `DATABASE_URL`.

#### 3. Copy `.env.example` to `.env`

macOS / Linux:

```bash
cp .env.example .env
````

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

#### 4. Open `.env` in a text editor

Paste the Render database URL into `.env` exactly as provided:

```env
DATABASE_URL=the-render-postgresql-url
```

Do not add extra quotes unless the URL itself requires them.

#### 5. Add the rest of the required environment variables

At minimum, add:

```env
FLASK_KEY=change-me
DATABASE_URL=the-render-postgresql-url
GROQ_API_KEY=your-groq-api-key
GOOGLE_PLACES_API_KEY=your-google-places-api-key
ROUTES_API_KEY=your-google-routes-api-key
GOOGLE_MAPS_API_KEY=your-google-maps-api-key
```

Optional values for events, alerts, and email:

```env
NEWS_API_KEY=your-news-api-key
TICKETMASTER_API_KEY=your-ticketmaster-api-key
RESEND_API_KEY=your-resend-api-key
EMAIL_ENABLED=true
EMAIL_FROM=Wayfinder AI <onboarding@resend.dev>
MY_EMAIL=your-email@example.com
```

#### 6. Activate the virtual environment

macOS / Linux:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

#### 7. Install dependencies if not already installed

```bash
pip install -r requirements.txt
```

#### 8. Run the migrations against the Render database

```bash
flask --app index db upgrade
```

What this does:

* connects to the PostgreSQL database in `DATABASE_URL`
* reads the migration files in `migrations/`
* creates or updates the Wayfinder AI tables inside that hosted database

This is the step that initializes the database schema on Render.

If the database is already up to date, this command should not make additional schema changes.

#### 9. Verify that migrations completed successfully

A successful migration step should finish without database connection errors. If there is a problem, it usually means:

* `DATABASE_URL` is wrong
* the Render database is unavailable
* network access is blocked
* credentials in the URL are invalid

#### 10. Start the Flask app

```bash
python -m flask --app index run --debug
```

#### 11. Start the worker in a second terminal

macOS / Linux:

```bash
PYTHONPATH=. python workers/run_worker.py
```

Windows PowerShell:

```powershell
$env:PYTHONPATH="."
python workers/run_worker.py
```

#### 12. Confirm both processes are using the same `.env`

This is important. The Flask app and the worker must both read the same `DATABASE_URL`. Otherwise:

* the web app may write to one database
* the worker may read from a different database
* tasks will appear to be stuck or missing

#### 13. Open the app in the browser

```text
http://127.0.0.1:5000
```

#### 14. Submit a test trip

A correct hosted-database setup should allow you to:

* submit a trip request
* create rows in the hosted PostgreSQL database
* have the worker pick up tasks
* see progress on the dashboard

---

### Option 2 — Local PostgreSQL database (supported as an alternative, but not the setup used for this project)

A local PostgreSQL database can also be used, but **this was not the setup used during development**. It is included here only so another developer can recreate the schema locally if desired.

#### 1. Install PostgreSQL locally

Install PostgreSQL on the machine and make sure the PostgreSQL service is running.

#### 2. Create a local database

Create a database named `wayfinder_ai`:

```bash
createdb wayfinder_ai
```

#### 3. Copy `.env.example` to `.env`

macOS / Linux:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

#### 4. Set `DATABASE_URL` in `.env`

Example:

```env
DATABASE_URL=postgresql://username:password@localhost:5432/wayfinder_ai
```

Replace:

* `username` with the local PostgreSQL username
* `password` with the local PostgreSQL password
* `localhost:5432` with the correct host and port if different
* `wayfinder_ai` with the actual local database name

#### 5. Add the rest of the required environment variables

At minimum:

```env
FLASK_KEY=change-me
DATABASE_URL=postgresql://username:password@localhost:5432/wayfinder_ai
GROQ_API_KEY=your-groq-api-key
GOOGLE_PLACES_API_KEY=your-google-places-api-key
ROUTES_API_KEY=your-google-routes-api-key
GOOGLE_MAPS_API_KEY=your-google-maps-api-key
```

Optional values for events, alerts, and email:

```env
NEWS_API_KEY=your-news-api-key
TICKETMASTER_API_KEY=your-ticketmaster-api-key
RESEND_API_KEY=your-resend-api-key
EMAIL_ENABLED=true
EMAIL_FROM=Wayfinder AI <onboarding@resend.dev>
MY_EMAIL=your-email@example.com
```

#### 6. Activate the virtual environment

macOS / Linux:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

#### 7. Install dependencies if not already installed

```bash
pip install -r requirements.txt
```

#### 8. Run migrations

```bash
flask --app index db upgrade
```

This creates the same Wayfinder AI tables in the local database.

#### 9. Start the Flask app

```bash
python -m flask --app index run --debug
```

#### 10. Start the worker in a second terminal

macOS / Linux:

```bash
PYTHONPATH=. python workers/run_worker.py
```

Windows PowerShell:

```powershell
$env:PYTHONPATH="."
python workers/run_worker.py
```

#### 11. Confirm both processes are using the same `.env`

As with the hosted setup, the Flask app and the worker must point to the same local `DATABASE_URL`.

#### 12. Open the app in the browser

```text
http://127.0.0.1:5000
```

#### 13. Submit a test trip

A correct local setup should allow you to:

* submit a trip request
* create rows in the local PostgreSQL database
* have the worker pick up tasks
* see progress on the dashboard

### Final clarification

To be explicit:

* **the actual project used a hosted PostgreSQL database on Render**
* **the local PostgreSQL setup was not the development setup**
* both setups rely on `DATABASE_URL`
* the models in `index.py` define the schema
* the migrations initialize that schema in the selected database
* the Flask app and worker must use the same `.env` file so they connect to the same database

---

## Local Setup — macOS / Linux

### 1. Clone the repo

```bash
git clone git@github.com:mjmaho19/Wayfinder_AI.git
cd Wayfinder_AI
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create `.env`

```bash
cp .env.example .env
```

### 5. Choose a database setup method

Choose **one** of the following:

* **Hosted PostgreSQL on Render**: paste the Render database URL into `DATABASE_URL`
* **Local PostgreSQL**: create a local PostgreSQL database and set `DATABASE_URL` to the local connection string

Examples:

Hosted:

```env
DATABASE_URL=the-render-postgresql-url
```

Local:

```env
DATABASE_URL=postgresql://username:password@localhost:5432/wayfinder_ai
```

### 6. Open `.env` and fill in the required values

At minimum:

```env
FLASK_KEY=change-me
DATABASE_URL=your-selected-postgresql-url
GROQ_API_KEY=your-groq-api-key
GOOGLE_PLACES_API_KEY=your-google-places-api-key
ROUTES_API_KEY=your-google-routes-api-key
GOOGLE_MAPS_API_KEY=your-google-maps-api-key
```

Optional values for events, alerts, and email:

```env
NEWS_API_KEY=your-news-api-key
TICKETMASTER_API_KEY=your-ticketmaster-api-key
RESEND_API_KEY=your-resend-api-key
EMAIL_ENABLED=true
EMAIL_FROM=Wayfinder AI <onboarding@resend.dev>
MY_EMAIL=your-email@example.com
```

### 7. Apply database migrations

```bash
flask --app index db upgrade
```

### 8. Start the Flask app

```bash
python -m flask --app index run --debug
```

### 9. In a second terminal, activate the environment again

```bash
source .venv/bin/activate
```

### 10. In that second terminal, run the worker

```bash
PYTHONPATH=. python workers/run_worker.py
```

### 11. Confirm both processes use the same `.env`

Both the Flask app and the worker must use the same `DATABASE_URL`.

### 12. Open the app

```text
http://127.0.0.1:5000
```

### 13. Verify the setup

A successful setup should allow you to:

* load the request form
* submit a trip request
* see the worker process tasks
* see the dashboard update
* see the itinerary appear progressively

---

## Local Setup — Windows (PowerShell)

### 1. Clone the repo

```powershell
git clone https://github.com/mjmaho19/Wayfinder_AI.git
cd Wayfinder_AI
```

### 2. Create a virtual environment

```powershell
python -m venv .venv
```

### 3. Activate the virtual environment

```powershell
.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then activate again:

```powershell
.venv\Scripts\Activate.ps1
```

### 4. Install dependencies

```powershell
pip install -r requirements.txt
```

### 5. Create `.env`

```powershell
Copy-Item .env.example .env
```

### 6. Choose a database setup method

Choose **one** of the following:

* **Hosted PostgreSQL on Render**: paste the Render database URL into `DATABASE_URL`
* **Local PostgreSQL**: create a local PostgreSQL database and set `DATABASE_URL` to the local connection string

Examples:

Hosted:

```env
DATABASE_URL=the-render-postgresql-url
```

Local:

```env
DATABASE_URL=postgresql://username:password@localhost:5432/wayfinder_ai
```

### 7. Open `.env` and fill in the required values

At minimum:

```env
FLASK_KEY=change-me
DATABASE_URL=your-selected-postgresql-url
GROQ_API_KEY=your-groq-api-key
GOOGLE_PLACES_API_KEY=your-google-places-api-key
ROUTES_API_KEY=your-google-routes-api-key
GOOGLE_MAPS_API_KEY=your-google-maps-api-key
```

Optional values for events, alerts, and email:

```env
NEWS_API_KEY=your-news-api-key
TICKETMASTER_API_KEY=your-ticketmaster-api-key
RESEND_API_KEY=your-resend-api-key
EMAIL_ENABLED=true
EMAIL_FROM=Wayfinder AI <onboarding@resend.dev>
MY_EMAIL=your-email@example.com
```

### 8. Apply database migrations

```powershell
python -m flask --app index db upgrade
```

### 9. Start the Flask app

```powershell
python -m flask --app index run --debug
```

### 10. Open a second PowerShell window

Activate the environment again:

```powershell
.venv\Scripts\Activate.ps1
```

### 11. Run the worker

```powershell
$env:PYTHONPATH="."
python workers/run_worker.py
```

### 12. Confirm both processes use the same `.env`

Both the Flask app and the worker must use the same `DATABASE_URL`.

### 13. Open the app

```text
http://127.0.0.1:5000
```

### 14. Verify the setup

A successful setup should allow you to:

* load the request form
* submit a trip request
* see the worker process tasks
* see the dashboard update
* see the itinerary appear progressively

---

## How It Works

1. A traveler submits a trip request through the Flask app.
2. The app stores the request in PostgreSQL as a `WayfinderSubmission`.
3. Initial tasks are seeded in `AgentTask` for tools such as weather, places, transit, culture, events, and alerts.
4. The background worker polls for pending tasks, claims one, runs the appropriate tool, and stores structured output in `ToolResult`.
5. After tool completion, a `supervisor_update` task is queued.
6. The AI supervisor reads the submission, tool results, and current plan, then builds or refines the itinerary.
7. The dashboard polls `/api/latest` and displays the evolving plan.
8. The chat assistant can answer trip questions, propose edits, and trigger replanning.
9. If important travel alerts are found, the system can enqueue an email alert task.

---

## Running Tests

The repo includes automated tests in the `tests/` folder.

Run tests from the **project root** with the virtual environment activated. Do **not** run them from inside the `tests/` folder.

Recommended command:

```bash
python -m pytest tests/test_wayfinder.py -v
````

You can also run the full test suite with:

```bash
python -m pytest
```

Or with more detail:

```bash
python -m pytest -v
```

Using `python -m pytest` is recommended instead of plain `pytest` because it helps ensure the tests run with the active virtual environment and the correct project import path.

### Important notes

* Run tests from the directory that contains `index.py`, `agents/`, `tools/`, `workers/`, and `tests/`
* Activate the virtual environment before running tests
* Install `pytest` in the virtual environment if it is not already installed
* Many external API calls in the test suite are mocked, so real API calls should not be required for those tests
* Some tests depend on minimal environment variables being present so imports do not fail

If needed, install pytest with:

```bash
pip install pytest
```

### Good basic verification steps

A successful setup should allow you to:

* run `flask --app index db upgrade` without database errors
* start the Flask app successfully
* start the worker successfully
* open the request form in the browser
* submit a trip request
* see tasks progress in the dashboard
* run `python -m pytest tests/test_wayfinder.py -v` successfully

---

## API Keys and External Service Setup

Each contributor is responsible for obtaining their own API keys and configuring them locally in `.env`. Keys should never be committed to the repository.

### Groq

Get a key from:

- https://console.groq.com

Used for:
- AI supervisor
- AI chat agent

### Google Cloud

Used for:
- Places API
- Routes API
- Maps JavaScript API

Google changes its console and documentation periodically, so the most reliable source of setup instructions is Google’s own documentation.

General process:

1. Go to the Google Cloud Console:
   - https://console.cloud.google.com
2. Create a new project or select an existing one
3. Make sure billing is enabled for that project if required by Google
4. Open the APIs & Services section
5. Enable the APIs needed by this project:
   - Places API
   - Routes API
   - Maps JavaScript API
6. Create an API key under APIs & Services → Credentials
7. Copy the key into `.env`
8. Apply appropriate API restrictions and application restrictions for development or deployment

Useful Google documentation starting points:

- Google Cloud Console: https://console.cloud.google.com
- API Library: https://console.cloud.google.com/apis/library
- Credentials page: https://console.cloud.google.com/apis/credentials
- Places API documentation: https://developers.google.com/maps/documentation/places/web-service
- Routes API documentation: https://developers.google.com/maps/documentation/routes
- Maps JavaScript API documentation: https://developers.google.com/maps/documentation/javascript

Notes:
- This README does not attempt to duplicate Google’s full setup documentation because Google may change the console workflow over time.
- If one of the Google-powered features is not working, first confirm that the correct API has been enabled in the Google Cloud project tied to the key being used.

### News API

Get a key from:

- https://newsapi.org

Used for:
- destination alert monitoring

### Ticketmaster

Get a key from:

- https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/

Used for:
- event discovery

### Resend

Get a key from:

- https://resend.com

Used for:
- email notifications
---

## Documentation

Generated documentation is available in the `docs/` folder as pydoc HTML files.

Use the docs when you want:

* a module-by-module reference
* generated documentation for project files
* a quick way to inspect available classes, functions, and routes

To use the docs:

1. open the `docs/` folder
2. locate the relevant HTML file
3. open it directly in a browser

If there is an `index.html` or a main landing page in the `docs/` folder, start there first.

---

## Troubleshooting

### `DATABASE_URL is not set`

Cause:

* `.env` is missing or not loaded
* `DATABASE_URL` was not added

Fix:

* create `.env`
* add the hosted PostgreSQL URL that was provided
* rerun the app

### Database connection failure

Common causes:

* the hosted PostgreSQL URL is incorrect
* credentials in the URL are wrong
* network access to the hosted database is blocked
* the database server is temporarily unavailable

Fix:

* verify the exact `DATABASE_URL`
* verify network access
* verify the hosted database is reachable
* rerun:

```bash
flask --app index db upgrade
```

### Migrations fail

Cause:

* invalid `DATABASE_URL`
* migrations have not been applied yet
* database permissions are insufficient

Fix:

* verify the URL
* make sure the same `.env` is being used
* rerun:

```bash
flask --app index db upgrade
```

### `GROQ_API_KEY` missing or supervisor/chat fails

Cause:

* missing or invalid Groq key

Fix:

* add a valid `GROQ_API_KEY`
* confirm the key works in the correct environment

### Worker is not doing anything

Cause:

* worker is not running
* no pending tasks were created
* database connection mismatch between app and worker

Fix:

* make sure the worker is running in a second terminal
* make sure app and worker use the same `.env`
* submit a new trip and check task rows / dashboard status

### Map is blank on the dashboard

Cause:

* `GOOGLE_MAPS_API_KEY` missing
* Maps JavaScript API not enabled
* browser console contains Google Maps errors

Fix:

* add `GOOGLE_MAPS_API_KEY`
* enable Maps JavaScript API in Google Cloud
* verify any domain restrictions on the key

### PowerShell activation still fails

Fix:

* run PowerShell as the current user
* use:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

* then reactivate the environment

### Events do not appear

Cause:

* `TICKETMASTER_API_KEY` missing
* Ticketmaster tool failed
* no matching events were returned for the query

Fix:

* verify `TICKETMASTER_API_KEY`
* confirm the events tool is enabled in the current branch
* inspect worker logs and `ToolResult` entries

### Email alerts do not send

Cause:

* `EMAIL_ENABLED` is false
* `RESEND_API_KEY` missing
* `EMAIL_FROM` missing or invalid
* no qualifying alerts were found

Fix:

* verify alert-related environment variables
* confirm the alerts tool is producing results
* confirm the worker is running

---

## Team

* **Michael Mahoney** — maintainer
* **Edgar Falfan** — contributor

---

## License

Private project – all rights reserved.