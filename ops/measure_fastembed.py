"""Measure local FastEmbed first-query and warm-query RSS/latency offline."""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TRACING_ENABLED"] = "0"
os.environ["EMBEDDING_PROVIDER"] = "fastembed"
os.environ["EMBEDDING_MODEL"] = "BAAI/bge-small-en-v1.5"
os.environ["EMBEDDING_DIM"] = "384"
os.environ["APP_ENV"] = "test"
os.environ["PERSISTENCE_ENABLED"] = "0"
os.environ["SAFETY_MODEL_URL"] = ""
os.environ["SAFETY_PROVIDER"] = "disabled"
os.environ["ANSWER_MODE"] = "extractive"
os.environ["GEMINI_FALLBACK_ENABLED"] = "0"
os.environ["LLM_PROVIDER"] = "groq"

from support_agent.config import get_settings
from support_agent.guardrails.pii import PIIRedactor
from support_agent.kb.embed import Embedder
from support_agent.server import app


def rss_bytes():
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

        value = MemoryCounters()
        value.cb = ctypes.sizeof(value)
        current_process = ctypes.windll.kernel32.GetCurrentProcess
        current_process.restype = ctypes.c_void_p
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = [ctypes.c_void_p, ctypes.POINTER(MemoryCounters), ctypes.c_ulong]
        get_memory.restype = ctypes.c_int
        process = current_process()
        if not get_memory(process, ctypes.byref(value), value.cb):
            raise OSError("GetProcessMemoryInfo failed")
        return value.WorkingSetSize
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if os.uname().sysname == "Darwin" else peak * 1024)


def main():
    get_settings.cache_clear()
    _ = app
    redactor = PIIRedactor()
    if not redactor._presidio:
        raise RuntimeError("Presidio did not initialize in the local resource measurement.")
    baseline = rss_bytes()
    peak = [baseline]
    finished = threading.Event()

    def monitor():
        while not finished.wait(0.05):
            peak[0] = max(peak[0], rss_bytes())

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    embedder = Embedder()
    started = time.perf_counter()
    first = embedder.embed_one("What is the return policy?")
    first_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    warm = embedder.embed_one("What is the shipping policy?")
    warm_ms = (time.perf_counter() - started) * 1000

    class MockClassifierClient:
        messages = None

        def __init__(self):
            self.messages = self

        def create(self, **_kwargs):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"intent":"social","phone_requested":false,"reason":"offline memory probe"}',
                    )
                ],
                usage=SimpleNamespace(
                    model="openai/gpt-oss-20b",
                    input_tokens=0,
                    output_tokens=0,
                    cache_read_input_tokens=0,
                    cache_creation_input_tokens=0,
                ),
            )

    # Exercise actual FastAPI lifespan, middleware, Presidio, and /chat route with
    # a mocked classifier so the probe cannot call a hosted model or database.
    from fastapi.testclient import TestClient

    from support_agent.guardrails import conversation

    with (
        patch.object(conversation, "get_client", return_value=MockClassifierClient()),
        TestClient(app) as client,
    ):
        health = client.get("/healthz")

        def mock_chat(index: int) -> int:
            return client.post(
                "/chat",
                json={"conversation_id": str(uuid4()), "message": f"hello {index}"},
            ).status_code

        with ThreadPoolExecutor(max_workers=4) as executor:
            chat_statuses = list(executor.map(mock_chat, range(4)))
        if health.status_code != 200 or chat_statuses != [200] * 4:
            raise RuntimeError(
                f"Local FastAPI memory-probe returned health={health.status_code}, "
                f"chat_statuses={chat_statuses}."
            )

    finished.set()
    monitor_thread.join(timeout=1)
    peak[0] = max(peak[0], rss_bytes())
    print(
        json.dumps(
            {
                "mode": "offline FastAPI plus model-cache and mocked chat measurement",
                "model": "BAAI/bge-small-en-v1.5",
                "dimensions": len(first),
                "warm_dimensions": len(warm),
                "first_query_ms": round(first_ms, 1),
                "warm_query_ms": round(warm_ms, 1),
                "process_rss_before_bytes": baseline,
                "process_peak_rss_bytes": peak[0],
                "incremental_peak_rss_bytes": max(0, peak[0] - baseline),
                "render_free_memory_bytes": 512 * 1024 * 1024,
                "includes_app_import_and_presidio": True,
                "includes_fastapi_testclient_lifespan_and_mocked_chat": True,
                "includes_database_pool": False,
                "includes_hosted_inference": False,
                "includes_concurrent_requests": True,
                "concurrent_mocked_chat_requests": 4,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
