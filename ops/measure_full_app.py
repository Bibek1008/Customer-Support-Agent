"""Measure local FastAPI, Presidio, FastEmbed, PostgreSQL, and mock-chat load.

This script migrates its database during FastAPI test startup. It accepts only a
dedicated loopback PostgreSQL database on port 5433 named
``support_agent_test``. Never point it at Neon or a database with user data.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import os
import sys
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4


def validate_test_database_url(value: str) -> tuple[str, int, str]:
    """Refuse anything except the dedicated disposable local test database."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Set SUPPORT_TEST_DATABASE_URL to the disposable local test DB.") from exc

    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == "localhost"

    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or not loopback
        or port != 5433
        or parsed.path != "/support_agent_test"
        or parsed.query
        or parsed.fragment
        or not parsed.username
        or parsed.password is None
    ):
        raise ValueError(
            "Refusing DB URL: use PostgreSQL on loopback port 5433, database "
            "support_agent_test, with no query parameters."
        )
    return host, port, parsed.path.removeprefix("/")


def _rss_bytes(*, peak: bool = False) -> int:
    if os.name == "nt":
        import ctypes

        class MemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process_fn = ctypes.windll.kernel32.GetCurrentProcess
        process_fn.restype = ctypes.c_void_p
        memory_fn = ctypes.windll.psapi.GetProcessMemoryInfo
        memory_fn.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(MemoryCounters),
            ctypes.c_ulong,
        ]
        memory_fn.restype = ctypes.c_int
        if not memory_fn(process_fn(), ctypes.byref(counters), counters.cb):
            raise OSError("GetProcessMemoryInfo failed")
        return counters.PeakWorkingSetSize if peak else counters.WorkingSetSize

    import resource

    max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if os.uname().sysname == "Darwin":
        return int(max_rss)
    return int(max_rss * 1024)


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)]


def main() -> int:
    raw_database_url = os.environ.get("SUPPORT_TEST_DATABASE_URL", "")
    if not raw_database_url:
        print(
            "Set SUPPORT_TEST_DATABASE_URL to the disposable local DB; "
            "expected loopback:5433/support_agent_test.",
            file=sys.stderr,
        )
        return 2
    try:
        db_host, db_port, db_name = validate_test_database_url(raw_database_url)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # Override any local .env values before importing the application. The
    # database guard above ensures this can never use a hosted database.
    os.environ.update(
        {
            "APP_ENV": "test",
            "PERSISTENCE_ENABLED": "1",
            "DATABASE_URL": raw_database_url,
            "DATABASE_POOL_SIZE": "2",
            "BUSINESS_MODE": "demo",
            "EMBEDDING_PROVIDER": "fastembed",
            "EMBEDDING_MODEL": "BAAI/bge-small-en-v1.5",
            "EMBEDDING_DIM": "384",
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "SAFETY_PROVIDER": "disabled",
            "SAFETY_MODEL_URL": "",
            "TRACING_ENABLED": "0",
            "GEMINI_FALLBACK_ENABLED": "0",
            "LLM_PROVIDER": "groq",
            "ANSWER_MODE": "extractive",
            "ADMIN_API_KEY": "local-load-test-staff-key-not-a-secret",
            "SERVICE_API_KEY": "local-load-test-service-key-not-a-secret",
            "RATE_LIMIT_PER_MINUTE": "1000",
        }
    )

    baseline_rss = _rss_bytes()
    peak_rss = [max(baseline_rss, _rss_bytes(peak=True))]
    stop_monitor = threading.Event()

    def monitor() -> None:
        while not stop_monitor.wait(0.025):
            peak_rss[0] = max(peak_rss[0], _rss_bytes(peak=True))

    monitor_thread = threading.Thread(target=monitor, name="rss-monitor", daemon=True)
    monitor_thread.start()

    from fastapi.testclient import TestClient

    from support_agent.config import get_settings
    from support_agent.guardrails.pii import PIIRedactor
    from support_agent.kb.embed import Embedder
    from support_agent.schemas import Decision, DecisionType, Message, Trace
    from support_agent.server import app

    get_settings.cache_clear()
    redactor = PIIRedactor()
    if not redactor._presidio:
        raise RuntimeError("Presidio did not initialize for the load test.")

    embedder = Embedder()
    started = time.perf_counter()
    vector = embedder.embed_one("What is the return window?")
    first_embedding_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    warm_vector = embedder.embed_one("How long does shipping take?")
    warm_embedding_ms = (time.perf_counter() - started) * 1000
    if len(vector) != 384 or len(warm_vector) != 384:
        raise RuntimeError("FastEmbed returned an unexpected vector dimension.")

    from support_agent import server

    def mocked_turn(conversation_id, user_message, customer_id=None, history=None):
        answer = "Local load-test response with a synthetic source."
        messages = [
            *(history or []),
            Message(role="user", content=user_message),
            Message(role="assistant", content=answer),
        ]
        return Trace(
            conversation_id=conversation_id,
            messages=messages,
            decision=Decision(
                type=DecisionType.ANSWER,
                answer=answer,
                confidence=0.9,
                threshold=0.6,
            ),
        )

    from unittest.mock import patch

    request_latencies_ms: list[float] = []
    concurrency = 4
    request_started = time.perf_counter()
    with patch.object(server, "run_turn", side_effect=mocked_turn), TestClient(app) as client:
        health = client.get("/healthz")
        ready = client.get("/readyz")
        if health.status_code != 200 or ready.status_code != 200:
            raise RuntimeError("FastAPI startup or local database readiness failed.")
        session = client.post("/api/session")
        session.raise_for_status()
        conversations = [
            client.post("/api/conversations").json()["conversation_id"] for _ in range(concurrency)
        ]

        def send_turn(index: int) -> tuple[int, float, str]:
            started = time.perf_counter()
            response = client.post(
                "/chat",
                json={
                    "conversation_id": conversations[index],
                    "request_id": str(uuid4()),
                    "message": f"Synthetic local load request {index}",
                },
            )
            elapsed = (time.perf_counter() - started) * 1000
            return response.status_code, elapsed, conversations[index]

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            results = list(executor.map(send_turn, range(concurrency)))
        request_wave_ms = (time.perf_counter() - request_started) * 1000
        request_latencies_ms = [row[1] for row in results]
        if any(row[0] != 200 for row in results):
            raise RuntimeError("At least one mocked concurrent /chat request failed.")
        for _, _, conversation_id in results:
            history = client.get(f"/api/conversations/{conversation_id}")
            history.raise_for_status()
            if len(history.json()["messages"]) != 2:
                raise RuntimeError("The local database did not persist both chat messages.")

    stop_monitor.set()
    monitor_thread.join(timeout=1)
    peak_rss[0] = max(peak_rss[0], _rss_bytes(peak=True))
    print(
        json.dumps(
            {
                "mode": "local FastAPI + Presidio + FastEmbed + disposable PostgreSQL; mocked run_turn",
                "database_target": f"{db_host}:{db_port}/{db_name}",
                "fastapi_startup_and_shutdown": "passed",
                "presidio_initialized": True,
                "fastembed_dimensions": len(vector),
                "first_embedding_ms": round(first_embedding_ms, 1),
                "warm_embedding_ms": round(warm_embedding_ms, 1),
                "readyz": "passed",
                "concurrent_mocked_chat_requests": concurrency,
                "chat_http_statuses": [row[0] for row in results],
                "chat_latency_ms": [round(value, 1) for value in request_latencies_ms],
                "chat_latency_p95_ms": round(_p95(request_latencies_ms), 1),
                "request_wave_ms": round(request_wave_ms, 1),
                "persisted_histories_verified": len(results),
                "process_baseline_rss_bytes": baseline_rss,
                "process_peak_working_set_bytes": peak_rss[0],
                "process_peak_working_set_mib": round(peak_rss[0] / (1024 * 1024), 1),
                "database_connections": True,
                "hosted_llm_safety_and_tracing": "disabled; agent turn mocked",
                "render_compatibility": "not established by local measurement",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
