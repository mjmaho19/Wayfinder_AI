# Copyright Michael Mahoney April 2025

from __future__ import annotations

from datetime import datetime
import os

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

app = Flask(__name__)
application = app  # keeps compatibility with some hosting setups

# ---- Core config ----
app.config["SECRET_KEY"] = os.getenv("FLASK_KEY", "dev-only-change-me") #change for new project
# # For new project, set DATABASE_URL in .env (include sslmode if needed)
# app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
# app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
#
# db = SQLAlchemy(app)


# # ---- DB model for submissions ----
# class Submission(db.Model):
#     __tablename__ = "submission"
#
#     id = db.Column(db.Integer, primary_key=True)
#     created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
#
#     name = db.Column(db.String(200), nullable=False)
#     company = db.Column(db.String(200), nullable=True)
#     email = db.Column(db.String(200), nullable=True)
#     phone = db.Column(db.String(50), nullable=True)
#     message = db.Column(db.Text, nullable=False)
#
#     status = db.Column(db.String(50), nullable=False, default="pending")  # for the agentic pipeline
#     agent_result = db.Column(db.Text, nullable=True)  # optional


@app.context_processor
def inject_globals():
    # needed the footer: {{ current_year }}
    return {"current_year": datetime.now().year}

@app.route("/", methods=["GET"])
def home():
    # Changed to new landing (contact)
    return redirect(url_for("contact"))


@app.route("/contact", methods=["GET", "POST"])
def contact():
    """
    Reused contact-form route:
    - GET renders template
    - POST writes submission to DB
    """
    if request.method == "POST":

        # Get form fields (match your template input names)
        name = (request.form.get("name") or "").strip()
        company = (request.form.get("company") or "").strip() or None
        email = (request.form.get("email") or "").strip().lower() or None
        phone = (request.form.get("phone") or "").strip() or None
        message = (request.form.get("message") or "").strip()

        # Basic validation (adjust as needed)
        if not name or not message:
            flash("Please include your name and a message.", "danger")
            return redirect(url_for("contact"))

        submission = Submission(
            name=name,
            company=company,
            email=email,
            phone=phone,
            message=message,
        )
        # db.session.add(submission)
        # db.session.commit()

        # If you want agentic AI to pick it up, you can return JSON or redirect
        # For now we’ll redirect and show a success flash:
        flash("Submitted successfully!", "success")
        return redirect(url_for("contact"))

    # IMPORTANT: keep this filename aligned with the template you copied
    return render_template("contacts-v1.html")


@app.route("/api/submissions/<int:submission_id>", methods=["GET"])
def get_submission(submission_id: int):
    """Optional helper endpoint for your agentic service to fetch a submission."""
    submission = Submission.query.get_or_404(submission_id)
    return jsonify(
        {
            "id": submission.id,
            "created_at": submission.created_at.isoformat(),
            "name": submission.name,
            "company": submission.company,
            "email": submission.email,
            "phone": submission.phone,
            "message": submission.message,
            "status": submission.status,
            "agent_result": submission.agent_result,
        }
    )


if __name__ == "__main__":
    app.run(debug=True)
