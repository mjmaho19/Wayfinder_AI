# Wayfinder AI – Contact Intake App

A lightweight Flask application that collects user submissions via a styled contact form and prepares them for processing by an agentic AI workflow.

## Project Status

Current phase:
- ✅ Contact form + styling fully functional  
- ✅ Submissions stored temporarily in memory  
- 🔜 Database integration (SQLite → Render Postgres)  
- 🔜 Agentic AI processing pipeline

---

## Tech Stack

- Python 3.12  
- Flask  
- Bootstrap-based UI (Around theme)  
- Flask-SQLAlchemy (database integration pending)  
- python-dotenv for configuration

---

## Local Setup

### 1. Clone the repo

```bash
git clone git@github.com:mjmaho19/Wayfinder_AI.git
cd Wayfinder_AI
```

### 2. Create virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install flask python-dotenv flask-sqlalchemy
```

### 4. Environment variables

Copy the example file:

```bash
cp .env.example .env
```

Edit `.env` and set:

```
FLASK_KEY=your-secret-key
# DATABASE_URL=sqlite:///app.db   (future)
```

### 5. Run the app

```bash
flask --app index run --debug
```

Open in browser:  
👉 http://127.0.0.1:5000/contact

---

## Current Behavior

- Form POST → stored in memory  
- Flash messages for success/validation  
- API endpoint available:

```
GET /api/submissions/<id>
```

---

## Next Milestones

1. Enable SQLAlchemy + Submission model  
2. Migrate to SQLite → Render Postgres  
3. Add AI agent consumer  
4. Add admin dashboard  
5. Remove unused theme assets
6. Change html text and layout

---

## Team

- **Michael Mahoney** – maintainer  
- **Edgar Barreto** – contributor

---

## License

Private project – all rights reserved.
