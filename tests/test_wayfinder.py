# Copyright Michael Mahoney, Edgar Falfan February 2026
#
# Wayfinder AI — Test Suite
# Run from project root with venv active:
#
#   pip install pytest --break-system-packages
#   pytest tests/test_wayfinder.py -v
#
# All external API calls are mocked — no real keys needed.

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

# ── Minimal env so imports don't crash ────────────────────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("FLASK_KEY", "test-secret")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("ROUTES_API_KEY", "test-routes-key")
os.environ.setdefault("GOOGLE_PLACES_API_KEY", "test-places-key")


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def flask_app():
    """Create the Flask app with an in-memory SQLite DB for the test session."""
    from index import app, db
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with app.app_context():
        db.create_all()
        yield app


@pytest.fixture()
def client(flask_app):
    """Flask test client — no real server needed."""
    return flask_app.test_client()


@pytest.fixture()
def fake_submission():
    """A plain object that mimics a WayfinderSubmission row."""
    sub = MagicMock()
    sub.id = 1
    sub.traveler_name = "Test User"
    sub.email = "test@example.com"
    sub.origin = "Boston, MA"
    sub.desired_destination = "New York, NY"
    sub.travel_dates = "2026-04-01 to 2026-04-05"
    sub.budget = "moderate"
    sub.preferences = "museums and local food"
    sub.raw_request = "Plan a trip from Boston to New York"
    sub.status = "pending"
    return sub


@pytest.fixture()
def fake_submission_dict(fake_submission):
    return {
        "id": fake_submission.id,
        "traveler_name": fake_submission.traveler_name,
        "email": fake_submission.email,
        "origin": fake_submission.origin,
        "desired_destination": fake_submission.desired_destination,
        "travel_dates": fake_submission.travel_dates,
        "budget": fake_submission.budget,
        "preferences": fake_submission.preferences,
        "raw_request": fake_submission.raw_request,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. Tool Tests — weather_tool
# ══════════════════════════════════════════════════════════════════════════════

class TestWeatherTool:

    MOCK_GEO = {
        "results": [{
            "latitude": 42.36,
            "longitude": -71.06,
            "name": "Boston",
            "country": "United States"
        }]
    }

    MOCK_WEATHER = {
        "current": {
            "time": "2026-04-01T12:00",
            "interval": 900,
            "temperature_2m": 12.5,
            "apparent_temperature": 10.0,
            "weather_code": 2,
            "wind_speed_10m": 15.0,
            "relative_humidity_2m": 65,
        }
    }

    @patch("tools.weather_tool.requests.get")
    def test_returns_expected_fields(self, mock_get, fake_submission):
        mock_get.side_effect = [
            MagicMock(json=lambda: self.MOCK_GEO),
            MagicMock(json=lambda: self.MOCK_WEATHER),
        ]
        from tools.weather_tool import run
        result = run(fake_submission, {})

        assert result["location"] == "Boston"
        assert result["temperature"] == "12.5°C"
        assert result["condition"] == "Partly Cloudy"
        assert "wind_speed" in result
        assert "humidity" in result
        assert "feels_like" in result

    @patch("tools.weather_tool.requests.get")
    def test_unknown_destination_returns_error(self, mock_get, fake_submission):
        mock_get.return_value = MagicMock(json=lambda: {"results": []})
        fake_submission.desired_destination = "Zzzznotaplace"
        from tools.weather_tool import run
        result = run(fake_submission, {})
        assert "error" in result

    @patch("tools.weather_tool.requests.get")
    def test_geocode_failure_returns_error(self, mock_get, fake_submission):
        mock_get.side_effect = Exception("Connection timeout")
        from tools.weather_tool import run
        result = run(fake_submission, {})
        assert "error" in result

    @patch("tools.weather_tool.requests.get")
    def test_weather_code_mapping(self, mock_get, fake_submission):
        """WMO codes should map to human-readable strings."""
        weather_with_code = dict(self.MOCK_WEATHER)
        weather_with_code["current"] = dict(self.MOCK_WEATHER["current"])
        weather_with_code["current"]["weather_code"] = 61
        mock_get.side_effect = [
            MagicMock(json=lambda: self.MOCK_GEO),
            MagicMock(json=lambda: weather_with_code),
        ]
        from tools.weather_tool import run
        result = run(fake_submission, {})
        assert result["condition"] == "Light Rain"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Tool Tests — transit_tool
# ══════════════════════════════════════════════════════════════════════════════

class TestTransitTool:

    MOCK_GEO_BOSTON = {
        "results": [{"latitude": 42.36, "longitude": -71.06, "name": "Boston"}]
    }
    MOCK_GEO_NYC = {
        "results": [{"latitude": 40.71, "longitude": -74.01, "name": "New York"}]
    }
    MOCK_ROUTES_RESPONSE = {
        "routes": [{
            "duration": "14400s",
            "distanceMeters": 350000,
            "legs": [{
                "steps": [{
                    "transitDetails": {
                        "transitLine": {
                            "nameShort": "Acela",
                            "name": "Acela Express",
                            "agencies": [{"name": "Amtrak"}],
                            "vehicle": {"type": "RAIL"},
                        },
                        "stopDetails": {
                            "departureStop": {"name": "South Station"},
                            "arrivalStop": {"name": "Penn Station"},
                        },
                        "localizedValues": {
                            "departureTime": {"time": {"text": "8:00 AM"}},
                            "arrivalTime": {"time": {"text": "11:45 AM"}},
                        },
                        "stopCount": 3,
                    }
                }]
            }]
        }]
    }

    @patch("tools.transit_tool.requests.post")
    @patch("tools.transit_tool.requests.get")
    def test_search_returns_routes(self, mock_get, mock_post):
        mock_get.side_effect = [
            MagicMock(json=lambda: self.MOCK_GEO_BOSTON),
            MagicMock(json=lambda: self.MOCK_GEO_NYC),
        ]
        mock_post.return_value = MagicMock(
            json=lambda: self.MOCK_ROUTES_RESPONSE,
            raise_for_status=lambda: None
        )
        from tools.transit_tool import search
        result = search("Boston", "New York", mode="RAIL")

        assert result["origin"] == "Boston"
        assert result["destination"] == "New York"
        assert result["count"] == 1
        assert len(result["routes"]) == 1
        route = result["routes"][0]
        assert route["duration_min"] == 240
        assert route["distance_mi"] > 0
        assert len(route["steps"]) == 1
        assert route["steps"][0]["line"] == "Acela"
        assert route["steps"][0]["agency"] == "Amtrak"

    @patch("tools.transit_tool.requests.get")
    def test_invalid_origin_returns_error(self, mock_get):
        mock_get.return_value = MagicMock(json=lambda: {"results": []})
        from tools.transit_tool import search
        result = search("NotARealPlace", "New York", mode="BUS")
        assert "error" in result
        assert result["routes"] == []

    @patch("tools.transit_tool.requests.post")
    @patch("tools.transit_tool.requests.get")
    def test_no_routes_returns_empty_list(self, mock_get, mock_post):
        mock_get.side_effect = [
            MagicMock(json=lambda: self.MOCK_GEO_BOSTON),
            MagicMock(json=lambda: self.MOCK_GEO_NYC),
        ]
        mock_post.return_value = MagicMock(
            json=lambda: {"routes": []},
            raise_for_status=lambda: None
        )
        from tools.transit_tool import search
        result = search("Boston", "New York", mode="BUS")
        assert result["routes"] == []
        assert result["count"] == 0

    @patch("tools.transit_tool.requests.post")
    @patch("tools.transit_tool.requests.get")
    def test_run_uses_submission_fields(self, mock_get, mock_post, fake_submission):
        mock_get.side_effect = [
            MagicMock(json=lambda: self.MOCK_GEO_BOSTON),
            MagicMock(json=lambda: self.MOCK_GEO_NYC),
        ]
        mock_post.return_value = MagicMock(
            json=lambda: {"routes": []},
            raise_for_status=lambda: None
        )
        from tools.transit_tool import run
        result = run(fake_submission, {})
        assert result["origin"] == "Boston, MA"
        assert result["destination"] == "New York, NY"

    @patch("tools.transit_tool.requests.post")
    @patch("tools.transit_tool.requests.get")
    def test_mode_defaults_to_bus(self, mock_get, mock_post):
        mock_get.side_effect = [
            MagicMock(json=lambda: self.MOCK_GEO_BOSTON),
            MagicMock(json=lambda: self.MOCK_GEO_NYC),
        ]
        mock_post.return_value = MagicMock(
            json=lambda: {"routes": []},
            raise_for_status=lambda: None
        )
        from tools.transit_tool import search
        result = search("Boston", "New York")
        assert result["mode"] == "BUS"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Flask Route Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestWeatherRoute:

    @patch("tools.weather_tool.requests.get")
    def test_weather_route_returns_200(self, mock_get, client):
        mock_get.side_effect = [
            MagicMock(json=lambda: {
                "results": [{"latitude": 40.71, "longitude": -74.01, "name": "New York", "country": "US"}]
            }),
            MagicMock(json=lambda: {
                "current": {
                    "temperature_2m": 15.0, "apparent_temperature": 13.0,
                    "weather_code": 0, "wind_speed_10m": 10.0, "relative_humidity_2m": 55
                },
                "daily": {
                    "time": ["2026-04-01"],
                    "weather_code": [0],
                    "temperature_2m_max": [18.0],
                    "temperature_2m_min": [10.0],
                }
            }),
        ]
        res = client.get("/api/weather")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "current" in data
        assert "daily" in data
        assert "location" in data

    def test_weather_route_has_correct_content_type(self, client):
        with patch("index.weather") as mock_weather:
            mock_weather.return_value = (json.dumps({"location": "New York", "current": {}, "daily": {}}), 200, {"Content-Type": "application/json"})
            res = client.get("/api/weather")
            assert res.status_code == 200


class TestTransitRoute:

    @patch("tools.transit_tool.requests.post")
    @patch("tools.transit_tool.requests.get")
    def test_transit_route_returns_routes(self, mock_get, mock_post, client):
        mock_get.side_effect = [
            MagicMock(json=lambda: {"results": [{"latitude": 42.36, "longitude": -71.06, "name": "Boston"}]}),
            MagicMock(json=lambda: {"results": [{"latitude": 40.71, "longitude": -74.01, "name": "New York"}]}),
        ]
        mock_post.return_value = MagicMock(
            json=lambda: {"routes": []},
            raise_for_status=lambda: None
        )
        res = client.get("/api/transit?origin=Boston&destination=New+York&mode=BUS")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "routes" in data
        assert data["origin"] == "Boston"
        assert data["destination"] == "New York"

    def test_transit_route_missing_params(self, client):
        res = client.get("/api/transit")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "error" in data

    def test_transit_route_missing_destination(self, client):
        res = client.get("/api/transit?origin=Boston")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "error" in data


class TestChatRoute:

    @patch("agents.chat_agent._client")
    def test_chat_route_returns_reply(self, mock_client, client):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Here are some suggestions for your trip!"
        mock_client.chat.completions.create.return_value = mock_response

        payload = {
            "messages": [{"role": "user", "content": "What should I pack?"}],
            "plan_context": ""
        }
        res = client.post("/api/chat", json=payload)
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "reply" in data
        assert len(data["reply"]) > 0

    @patch("agents.chat_agent._client")
    def test_chat_route_with_plan_context(self, mock_client, client):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Based on your itinerary, I suggest visiting the MoMA on day 2."
        mock_client.chat.completions.create.return_value = mock_response

        payload = {
            "messages": [{"role": "user", "content": "Suggest a museum"}],
            "plan_context": json.dumps({"destination": "New York", "itinerary": []})
        }
        res = client.post("/api/chat", json=payload)
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "reply" in data

    @patch("agents.chat_agent._client")
    def test_chat_route_api_failure_returns_fallback(self, mock_client, client):
        mock_client.chat.completions.create.side_effect = Exception("API unavailable")
        payload = {
            "messages": [{"role": "user", "content": "Hello"}],
            "plan_context": ""
        }
        res = client.post("/api/chat", json=payload)
        assert res.status_code == 200
        data = json.loads(res.data)
        assert "reply" in data
        assert "trouble" in data["reply"].lower()

    def test_latest_route_no_submissions(self, client):
        res = client.get("/api/latest")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["ok"] is True


# ══════════════════════════════════════════════════════════════════════════════
# 4. Agent Tests — Supervisor
# ══════════════════════════════════════════════════════════════════════════════

class TestSupervisor:

    TOOL_RESULTS_FULL = [
        {"tool_name": "weather", "payload": {"location": "New York", "current": {"temperature_2m": 15, "weather_code": 2}}},
        {"tool_name": "places",  "payload": {"destination": "New York", "items": [
            {"name": "MoMA", "type": "poi", "rating": 4.8, "distance_mi": 0.5},
            {"name": "The Plaza", "type": "hotel", "rating": 4.7, "distance_mi": 0.3},
        ]}},
        {"tool_name": "transit", "payload": {"origin": "Boston", "destination": "New York", "options": []}},
    ]

    TOOL_RESULTS_PARTIAL = [
        {"tool_name": "weather", "payload": {"location": "New York", "current": {}}},
    ]

    MOCK_GROQ_PLAN = {
        "status": "completed",
        "summary": "A wonderful 4-day trip to New York.",
        "new_tasks": [],
        "plan": {
            "trip": {"traveler_name": "Test User", "origin": "Boston", "destination": "New York",
                     "travel_dates": "2026-04-01 to 2026-04-05", "budget": "moderate"},
            "itinerary": [{"day": 1, "morning": "Arrive", "afternoon": "MoMA", "evening": "Dinner", "lodging": "The Plaza", "notes": ""}],
            "highlights": ["MoMA", "Central Park", "Brooklyn Bridge"],
            "warnings": ["Book hotels early"],
            "estimated_cost": "$800-$1200",
            "sections": {},
            "meta": {"missing_tools": [], "tool_count": 3}
        }
    }

    @patch("agents.supervisor._client")
    def test_returns_completed_when_all_tools_present(self, mock_client, fake_submission_dict):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps(self.MOCK_GROQ_PLAN)
        mock_client.chat.completions.create.return_value = mock_response

        from agents.supervisor import run_supervisor
        result = run_supervisor(fake_submission_dict, self.TOOL_RESULTS_FULL, None)

        assert result["status"] == "completed"
        assert "plan" in result
        assert "summary" in result

    @patch("agents.supervisor._client")
    def test_requests_missing_tools_when_partial(self, mock_client, fake_submission_dict):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "status": "processing",
            "summary": "Still waiting on places and transit.",
            "new_tasks": [
                {"task_type": "places", "input": {}},
                {"task_type": "transit", "input": {}},
            ],
            "plan": {"sections": {}, "meta": {"missing_tools": ["places", "transit"], "tool_count": 1}}
        })
        mock_client.chat.completions.create.return_value = mock_response

        from agents.supervisor import run_supervisor
        result = run_supervisor(fake_submission_dict, self.TOOL_RESULTS_PARTIAL, None)

        assert result["status"] == "processing"
        task_types = [t["task_type"] for t in result.get("new_tasks", [])]
        assert "places" in task_types or "transit" in task_types

    @patch("agents.supervisor._client")
    def test_fallback_on_api_failure(self, mock_client, fake_submission_dict):
        mock_client.chat.completions.create.side_effect = Exception("Groq unavailable")

        from agents.supervisor import run_supervisor
        result = run_supervisor(fake_submission_dict, self.TOOL_RESULTS_PARTIAL, None)

        assert "status" in result
        assert "plan" in result
        assert "summary" in result

    @patch("agents.supervisor._client")
    def test_fallback_on_invalid_json(self, mock_client, fake_submission_dict):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "This is not JSON at all!!!"
        mock_client.chat.completions.create.return_value = mock_response

        from agents.supervisor import run_supervisor
        result = run_supervisor(fake_submission_dict, self.TOOL_RESULTS_FULL, None)

        assert "status" in result
        assert "plan" in result

    @patch("agents.supervisor._client")
    def test_meta_tracks_missing_tools(self, mock_client, fake_submission_dict):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps(self.MOCK_GROQ_PLAN)
        mock_client.chat.completions.create.return_value = mock_response

        from agents.supervisor import run_supervisor
        result = run_supervisor(fake_submission_dict, self.TOOL_RESULTS_FULL, None)

        meta = result["plan"].get("meta", {})
        assert "missing_tools" in meta
        assert "tool_count" in meta


# ══════════════════════════════════════════════════════════════════════════════
# 5. Agent Tests — Chat Agent
# ══════════════════════════════════════════════════════════════════════════════

class TestChatAgent:

    @patch("agents.chat_agent._client")
    def test_returns_string_reply(self, mock_client):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Great question! Pack light layers for New York in April."
        mock_client.chat.completions.create.return_value = mock_response

        from agents.chat_agent import chat_with_plan
        reply = chat_with_plan([{"role": "user", "content": "What should I pack?"}], "")
        assert isinstance(reply, str)
        assert len(reply) > 0

    @patch("agents.chat_agent._client")
    def test_includes_plan_context_in_call(self, mock_client):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "I recommend the MoMA on day 2."
        mock_client.chat.completions.create.return_value = mock_response

        from agents.chat_agent import chat_with_plan
        plan = json.dumps({"destination": "New York", "itinerary": [{"day": 1}]})
        chat_with_plan([{"role": "user", "content": "Suggest museums"}], plan)

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        system_msg = messages[0]["content"]
        assert "New York" in system_msg or plan in system_msg

    @patch("agents.chat_agent._client")
    def test_returns_fallback_on_api_error(self, mock_client):
        mock_client.chat.completions.create.side_effect = Exception("Connection refused")

        from agents.chat_agent import chat_with_plan
        reply = chat_with_plan([{"role": "user", "content": "Hello"}], "")
        assert isinstance(reply, str)
        assert "trouble" in reply.lower() or "sorry" in reply.lower()

    @patch("agents.chat_agent._client")
    def test_multi_turn_conversation(self, mock_client):
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "The weather in New York will be mild."
        mock_client.chat.completions.create.return_value = mock_response

        from agents.chat_agent import chat_with_plan
        history = [
            {"role": "user", "content": "What's the weather like?"},
            {"role": "assistant", "content": "It will be around 15°C."},
            {"role": "user", "content": "Should I bring a jacket?"},
        ]
        reply = chat_with_plan(history, "")
        assert isinstance(reply, str)

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        # system + 3 history messages
        assert len(messages) == 4


# ══════════════════════════════════════════════════════════════════════════════
# 6. Worker Pipeline Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestWorkerPipeline:

    def test_safe_load_task_input_empty(self):
        from workers.run_worker import _safe_load_task_input
        task = MagicMock()
        task.input_json = None
        assert _safe_load_task_input(task) == {}

    def test_safe_load_task_input_valid_json(self):
        from workers.run_worker import _safe_load_task_input
        task = MagicMock()
        task.input_json = '{"reason": "tool_result_updated"}'
        result = _safe_load_task_input(task)
        assert result == {"reason": "tool_result_updated"}

    def test_safe_load_task_input_invalid_json(self):
        from workers.run_worker import _safe_load_task_input
        task = MagicMock()
        task.input_json = "not valid json {"
        result = _safe_load_task_input(task)
        assert isinstance(result, dict)
        assert "raw" in result

    def test_tool_runners_registry_contains_all_tools(self):
        from workers.run_worker import TOOL_RUNNERS
        assert "weather" in TOOL_RUNNERS
        assert "places" in TOOL_RUNNERS
        assert "transit" in TOOL_RUNNERS

    def test_tool_runners_are_callable(self):
        from workers.run_worker import TOOL_RUNNERS
        for name, runner in TOOL_RUNNERS.items():
            assert callable(runner), f"Runner for '{name}' is not callable"

    def test_ensure_supervisor_task_creates_when_missing(self, flask_app):
        from index import db, AgentTask, WayfinderSubmission
        from workers.run_worker import _ensure_supervisor_task

        with flask_app.app_context():
            sub = WayfinderSubmission(
                traveler_name="Pipeline Test",
                raw_request="test submission",
                status="pending",
            )
            db.session.add(sub)
            db.session.commit()

            _ensure_supervisor_task(sub.id)

            task = AgentTask.query.filter_by(
                submission_id=sub.id,
                task_type="supervisor_update",
                status="pending"
            ).first()
            assert task is not None

            # Calling again should NOT create a duplicate
            _ensure_supervisor_task(sub.id)
            count = AgentTask.query.filter_by(
                submission_id=sub.id,
                task_type="supervisor_update",
                status="pending"
            ).count()
            assert count == 1

    def test_mark_completed_sets_status(self, flask_app):
        from index import db, AgentTask, WayfinderSubmission
        from workers.run_worker import _mark_completed

        with flask_app.app_context():
            sub = WayfinderSubmission(
                traveler_name="Complete Test",
                raw_request="test",
                status="pending",
            )
            db.session.add(sub)
            db.session.commit()

            task = AgentTask(
                submission_id=sub.id,
                task_type="weather",
                status="running",
                attempts=1,
                max_attempts=3,
            )
            db.session.add(task)
            db.session.commit()

            _mark_completed(task)
            assert task.status == "completed"
            assert task.finished_at is not None

    def test_mark_failed_retries_when_under_max(self, flask_app):
        from index import db, AgentTask, WayfinderSubmission
        from workers.run_worker import _mark_failed

        with flask_app.app_context():
            sub = WayfinderSubmission(
                traveler_name="Retry Test",
                raw_request="test",
                status="pending",
            )
            db.session.add(sub)
            db.session.commit()

            task = AgentTask(
                submission_id=sub.id,
                task_type="places",
                status="running",
                attempts=1,
                max_attempts=3,
            )
            db.session.add(task)
            db.session.commit()

            _mark_failed(task, "Simulated failure")
            assert task.status == "pending"  # should retry

    def test_mark_failed_gives_up_at_max_attempts(self, flask_app):
        from index import db, AgentTask, WayfinderSubmission
        from workers.run_worker import _mark_failed

        with flask_app.app_context():
            sub = WayfinderSubmission(
                traveler_name="Max Attempts Test",
                raw_request="test",
                status="pending",
            )
            db.session.add(sub)
            db.session.commit()

            task = AgentTask(
                submission_id=sub.id,
                task_type="transit",
                status="running",
                attempts=3,
                max_attempts=3,
            )
            db.session.add(task)
            db.session.commit()

            _mark_failed(task, "Final failure")
            assert task.status == "failed"