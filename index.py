# Copyright Michael Mahoney April 2025

from __future__ import annotations

from datetime import datetime
import os

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

app = Flask(__name__)
application = app

# ---- Core config ----
app.config["SECRET_KEY"] = os.getenv("FLASK_KEY", "dev-only-change-me")

# For new project, set DATABASE_URL in .env (include sslmode if needed)
# app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
# app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
#
# db = SQLAlchemy(app)

# ---- DB model (disabled for now) ----
# class WayfinderSubmission(db.Model):
#     __tablename__ = "wayfinder_submission"
#
#     id = db.Column(db.Integer, primary_key=True)
#     created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
#
#     # Core traveler info
#     traveler_name = db.Column(db.String(200), nullable=False)
#     email = db.Column(db.String(200), nullable=True)
#
#     # Travel-specific fields
#     origin = db.Column(db.String(200), nullable=True)
#     desired_destination = db.Column(db.String(200), nullable=True)
#     travel_dates = db.Column(db.String(200), nullable=True)
#     budget = db.Column(db.String(100), nullable=True)
#
#     # Freeform input
#     preferences = db.Column(db.Text, nullable=True)
#     raw_request = db.Column(db.Text, nullable=False)
#
#     # AI pipeline fields
#     status = db.Column(db.String(50), nullable=False, default="pending")
#     agent_result = db.Column(db.Text, nullable=True)


@app.route("/", methods=["GET"])
def home():
    """Redirect root to travel request page."""
    return redirect(url_for("request_trip"))


@app.route("/request", methods=["GET", "POST"])
def request_trip():
    """
    Main Wayfinder request route.
    GET -> render travel form
    POST -> process travel request
    """
    if request.method == "POST":
        # ---- Get form data (matches HTML exactly) ----
        traveler_name = (request.form.get("traveler_name") or "").strip()
        email = (request.form.get("email") or "").strip().lower() or None
        origin = (request.form.get("origin") or "").strip() or None
        desired_destination = (request.form.get("desired_destination") or "").strip() or None
        travel_dates = (request.form.get("travel_dates") or "").strip() or None
        budget = (request.form.get("budget") or "").strip() or None
        preferences = (request.form.get("preferences") or "").strip() or None
        raw_request = (request.form.get("raw_request") or "").strip()

        # ---- Basic validation ----
        if not traveler_name or not raw_request:
            flash("Please include your name and trip description.", "danger")
            return redirect(url_for("request_trip"))

        # ---- Create submission (DB disabled for now) ----
        # submission = WayfinderSubmission(
        #     traveler_name=traveler_name,
        #     email=email,
        #     origin=origin,
        #     desired_destination=desired_destination,
        #     travel_dates=travel_dates,
        #     budget=budget,
        #     preferences=preferences,
        #     raw_request=raw_request,
        # )
        # db.session.add(submission)
        # db.session.commit()

        flash("Trip request submitted! Wayfinder is working on your plan.", "success")

        # Later: redirect to dashboard
        return redirect(url_for("request_trip"))

    return render_template("request.html")


if __name__ == "__main__":
    app.run(debug=True)