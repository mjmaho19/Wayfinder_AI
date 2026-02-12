# Contributing to Wayfinder AI

Thanks for helping build Wayfinder AI!  
This document describes how to work on the project safely and collaboratively.

---

## Branch Workflow

### Main Rules

- `main` branch must always be runnable  
- Create feature branches for changes  
- Use pull requests before merging to main

### Create a feature branch

```bash
git checkout -b feature/contact-db
```

### Commit style

Use clear, descriptive messages:

```
Add in-memory submission store  
Remove recaptcha dependency  
Prepare SQLAlchemy model (commented)  
```

---

## Running Locally

```bash
source .venv/bin/activate
flask --app index run --debug
```

---

## Code Style Guidelines

- Keep routes simple and focused  
- Avoid business logic in templates  
- Follow existing naming conventions:
  - `Submission` model  
  - `/api/submissions/<id>` endpoint  
- Use flash messages for user feedback  
- Do not commit secrets or real credentials

---

## Database (Upcoming)

When database support is enabled:

1. Un-comment SQLAlchemy configuration  
2. Enable the `Submission` model  
3. Configure `DATABASE_URL` in `.env`  
4. Add migrations if needed

---

## Pull Request Checklist

Before submitting a PR:

- Application runs without errors  
- No secrets or credentials in code  
- `.venv` not committed  
- Form POST tested locally  
- Clear commit messages  
- README updated if behavior changed

---

## Communication

- Small changes → open a PR directly  
- Large architectural changes → discuss first  
- Keep documentation updated

---

Thanks for contributing 🚀
