"""Check configured services without printing keys, database URLs, or customer data."""

import argparse
import json

from support_agent.config import get_settings
from support_agent.db import check_database, close_pool


def inspect(providers=False):
    from support_agent.guardrails.pii import get_redactor
    from support_agent.kb.store import get_store

    settings = get_settings()
    checks = {
        "business": settings.business_name,
        "business_mode": settings.business_mode,
        "answer_mode": settings.answer_mode,
        "persistence_enabled": settings.persistence_enabled,
        "pii": "presidio" if get_redactor()._presidio else "fallback",
        "tracing_enabled": settings.tracing_enabled,
        "safety_provider": settings.safety_provider,
        "gemini_fallback_enabled": settings.gemini_fallback_enabled,
        "gemini_fallback_model": settings.gemini_fallback_model,
    }
    check_database()
    checks["database"] = "connected"
    store = get_store()
    checks["knowledge_base"] = {"persistent": store._use_db, "chunks": store.count()}
    if providers:
        from support_agent.agent.models import get_client, reasoner_kwargs
        from support_agent.guardrails.safety import SafetyRole, get_classifier

        verdict = get_classifier().classify("Hello", SafetyRole.USER)
        checks["safety_probe"] = {
            "checked": verdict.checked,
            "safe": verdict.safe,
            "categories": verdict.categories,
        }
        response = get_client().messages.create(
            **reasoner_kwargs(),
            system="Reply with the word ready.",
            messages=[{"role": "user", "content": "Connection check"}],
        )
        checks["model_probe"] = "ok" if response.content else "empty"
    ready = (
        settings.persistence_enabled
        and checks["pii"] == "presidio"
        and store._use_db
        and store.count() > 0
    )
    if providers:
        ready = ready and verdict.checked and verdict.safe and checks["model_probe"] == "ok"
    checks["status"] = "ready" if ready else "not_ready"
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--providers", action="store_true", help="Make small real provider calls")
    args = parser.parse_args()
    try:
        checks = inspect(args.providers)
        print(json.dumps(checks, indent=2))
        if checks["status"] != "ready":
            raise SystemExit(1)
    except Exception as error:  # noqa: BLE001 - report the type without printing secrets from service errors
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        raise SystemExit(1) from None
    finally:
        close_pool()
        from support_agent.observability.tracing import flush_tracing

        flush_tracing()


if __name__ == "__main__":
    main()
