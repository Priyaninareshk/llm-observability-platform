from fastapi.testclient import TestClient
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from main import app


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"


def test_metrics_endpoint() -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    text = response.text
    assert "python_info" in text


def test_cost_report_endpoint() -> None:
    client.post("/chat", json={"prompt": "Cost report seed"})
    response = client.get("/reports/cost")
    assert response.status_code == 200
    payload = response.json()
    assert "total_requests" in payload
    assert "total_cost_usd" in payload
    assert "by_model" in payload
    assert "recent_records" in payload


def test_langsmith_status_endpoint() -> None:
    response = client.get("/observability/langsmith")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"enabled", "api_key_configured", "project"}


def test_chat_response_shape() -> None:
    response = client.post("/chat", json={"prompt": "Hello"})
    assert response.status_code == 200
    payload = response.json()
    assert "response" in payload
    assert "latency" in payload
    assert "token_usage" in payload
    assert "cost" in payload
    assert "trace_id" in payload
    assert set(payload["latency"].keys()) == {"total_ms", "llm_ms", "callback_ms", "middleware_ms"}
