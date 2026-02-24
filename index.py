# Copyright Michael Mahoney February 2026

from __future__ import annotations

from datetime import datetime
import os
import json

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

load_dotenv()

app = Flask(__name__)
application = app

# Config
app.config["SECRET_KEY"] = os.getenv("FLASK_KEY", "dev-only-change-me")

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is not set. Add it to your .env file.")

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["FLASK_APP"] = "index.py"

db = SQLAlchemy(app)
migrate = Migrate(app, db)


# Models

class WayfinderSubmission(db.Model):
    __tablename__ = "wayfinder_submission"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Core traveler info
    traveler_name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=True)

    # Travel-specific fields
    origin = db.Column(db.String(200), nullable=True)
    desired_destination = db.Column(db.String(200), nullable=True)
    travel_dates = db.Column(db.String(200), nullable=True)
    budget = db.Column(db.String(100), nullable=True)

    # Freeform input
    preferences = db.Column(db.Text, nullable=True)
    raw_request = db.Column(db.Text, nullable=False)

    # AI pipeline fields
    status = db.Column(db.String(50), nullable=False, default="pending")
    agent_result = db.Column(db.Text, nullable=True)


class AgentTask(db.Model):
    __tablename__ = "agent_task"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    submission_id = db.Column(db.Integer, db.ForeignKey("wayfinder_submission.id"), nullable=False, index=True)
    task_type = db.Column(db.String(50), nullable=False)  # e.g., "weather", "places", "lodging", "transit"
    status = db.Column(db.String(50), nullable=False, default="pending")  # pending/running/completed/failed

    input_json = db.Column(db.Text, nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=3)
    worker_id = db.Column(db.String(200), nullable=True)

    # fields for debugging / workers
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    error = db.Column(db.Text, nullable=True)

    submission = db.relationship("WayfinderSubmission", backref=db.backref("tasks", lazy=True))


class ToolResult(db.Model):
    __tablename__ = "tool_result"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    submission_id = db.Column(db.Integer, db.ForeignKey("wayfinder_submission.id"), nullable=False, index=True)
    tool_name = db.Column(db.String(50), nullable=False)  # e.g., "weather_api", "places_api"
    # Keep it as TEXT for now; store JSON as a string (simple & works everywhere)
    result_json = db.Column(db.Text, nullable=False)

    submission = db.relationship("WayfinderSubmission", backref=db.backref("tool_results", lazy=True))


class TripPlan(db.Model):
    __tablename__ = "trip_plan"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    submission_id = db.Column(db.Integer, db.ForeignKey("wayfinder_submission.id"), nullable=False, unique=True)
    # store the current best plan as JSON string for now
    plan_json = db.Column(db.Text, nullable=True)
    summary = db.Column(db.Text, nullable=True)

    submission = db.relationship("WayfinderSubmission", backref=db.backref("trip_plan", uselist=False))


# App routes
@app.route("/", methods=["GET"])
def home():
    """Redirect root to travel request page."""
    return redirect(url_for("request_trip"))


@app.route("/request", methods=["GET", "POST"])
def request_trip():
    """
    Main Wayfinder request route.
    GET -> render travel form
    POST -> store travel request + seed initial tasks, then redirect to dashboard
    """
    if request.method == "POST":
        traveler_name = (request.form.get("traveler_name") or "").strip()
        email = (request.form.get("email") or "").strip().lower() or None
        origin = (request.form.get("origin") or "").strip() or None
        desired_destination = (request.form.get("desired_destination") or "").strip() or None
        travel_dates = (request.form.get("travel_dates") or "").strip() or None
        budget = (request.form.get("budget") or "").strip() or None
        preferences = (request.form.get("preferences") or "").strip() or None
        raw_request = (request.form.get("raw_request") or "").strip()

        if not traveler_name or not raw_request:
            flash("Please include your name and trip description.", "danger")
            return redirect(url_for("request_trip"))

        # Create submission
        submission = WayfinderSubmission(
            traveler_name=traveler_name,
            email=email,
            origin=origin,
            desired_destination=desired_destination,
            travel_dates=travel_dates,
            budget=budget,
            preferences=preferences,
            raw_request=raw_request,
            status="pending",
        )
        db.session.add(submission)
        db.session.commit()

        starter_tasks = ["weather", "places", "lodging", "transit"]
        for t in starter_tasks:
            db.session.add(
                AgentTask(
                    submission_id=submission.id,
                    task_type=t,
                    status="pending",
                    input_json=None,
                    attempts=0,
                    max_attempts=3,
                )
            )

        # Add supervisor_update so the plan starts forming immediately
        db.session.add(
            AgentTask(
                submission_id=submission.id,
                task_type="supervisor_update",
                status="pending",
                input_json=json.dumps({"reason": "new_submission"}),
                attempts=0,
                max_attempts=3,
            )
        )

        db.session.commit()

        flash("Trip request submitted! View the dashboard for updates.", "success")
        return redirect(url_for("dashboard"))

    return render_template("request.html")


@app.route("/dashboard", methods=["GET"])
def dashboard():
    """Render the Wayfinder dashboard."""
    return render_template("wayfinder_dashboard.html")


# helps with the dashboard JS later
@app.route("/api/latest", methods=["GET"])
def api_latest():
    latest = WayfinderSubmission.query.order_by(WayfinderSubmission.created_at.desc()).first()
    if not latest:
        return jsonify({"ok": True, "latest": None})

    tasks = AgentTask.query.filter_by(submission_id=latest.id).order_by(AgentTask.created_at.asc()).all()
    plan = TripPlan.query.filter_by(submission_id=latest.id).first()
    results = ToolResult.query.filter_by(submission_id=latest.id).order_by(ToolResult.created_at.asc()).all()

    return jsonify(
        {
            "ok": True,
            "latest": {
                "id": latest.id,
                "created_at": latest.created_at.isoformat(),
                "traveler_name": latest.traveler_name,
                "email": latest.email,
                "origin": latest.origin,
                "desired_destination": latest.desired_destination,
                "travel_dates": latest.travel_dates,
                "budget": latest.budget,
                "preferences": latest.preferences,
                "raw_request": latest.raw_request,
                "status": latest.status,
                "agent_result": latest.agent_result,
                "tasks": [
                    {"id": t.id, "task_type": t.task_type, "status": t.status}
                    for t in tasks
                ],
                "plan": None if not plan else {
                    "summary": plan.summary,
                    "plan_json": plan.plan_json,
                    "updated_at": plan.updated_at.isoformat(),
                },
                "tool_results": [
                    {"id": r.id, "tool_name": r.tool_name, "result_json": r.result_json}
                    for r in results
                ],
            },
        }
    )


if __name__ == "__main__":
    # Create tables (commented out because tables already exist, do NOT run again)
    # with app.app_context():
    #     db.create_all()

    app.run(debug=True)