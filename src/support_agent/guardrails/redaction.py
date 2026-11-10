"""Deterministic secret protection and conservative public-document URL validation."""

import ipaddress
import re
from urllib.parse import urlsplit

from support_agent.config import get_settings

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_CREDENTIAL = re.compile(
    r"\b(?:authorization\s*[:=]\s*(?:bearer|basic)\s+\S+|"
    r"bearer\s+[A-Za-z0-9._~+/-]+=*|"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret|"
    r"client[_-]?secret)[\"']?\s*(?:[:=]\s*|\bis\s+)[\"']?[^\s,;<>\"']+)",
    re.IGNORECASE,
)
_TOKEN = re.compile(
    r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{8,}|[ps]k-lf-[A-Za-z0-9-]{8,}|"
    r"gh[pousr]_[A-Za-z0-9_]{16,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b"
)


def public_document_url(value: str | None) -> bool:
    """Validate syntax for an approved public document, without fetching its URL.

    Approval/provenance is a separate requirement. Reject ambiguous encodings,
    credentials, queries, fragments, private hosts, and token-like path segments.
    """
    if not value or not value.isascii() or re.search(r"[\s\\<>]", value):
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 80, 443}
            or parsed.query
            or parsed.fragment
            or "?" in value
            or "#" in value
            or "%" in value
            or not re.fullmatch(r"[a-zA-Z0-9.-]+", host)
            or "." not in host
            or any(
                not label or label.startswith("-") or label.endswith("-")
                for label in host.split(".")
            )
        ):
            return False
        try:
            ipaddress.ip_address(host)
            return False  # Citation documents must use approved DNS names.
        except ValueError:
            pass
        if any(
            label.lower() in {"localhost", "local", "internal", "private", "intranet", "test"}
            for label in host.split(".")
        ):
            return False
        segments = parsed.path.strip("/").split("/")
        return all(
            len(segment) <= 48
            and re.fullmatch(r"[A-Za-z0-9_.-]*", segment)
            and segment not in {".", ".."}
            and segment.lower()
            not in {"admin", "login", "auth", "oauth", "token", "account", "reset", "api"}
            and not re.search(r"[A-Za-z0-9_-]{24,}", segment)
            and not re.search(
                r"(?:^|[-_.])(?:token|secret|password|credential|session|key)(?:$|[-_.])",
                segment,
                re.IGNORECASE,
            )
            for segment in segments
        )
    except ValueError:
        return False


def redact_secrets(text: str) -> str:
    settings = get_settings()
    for name in (
        "anthropic_api_key",
        "groq_api_key",
        "gemini_api_key",
        "openai_api_key",
        "langfuse_secret_key",
        "langfuse_public_key",
        "ticketing_api_key",
        "hugging_face_hub_token",
        "database_url",
        "admin_api_key",
        "service_api_key",
    ):
        secret = getattr(settings, name)
        if secret and len(secret) >= 8:
            text = text.replace(secret, "<SECRET>")
    # Mask the entire URL, rather than leaving private parameters in the text.
    text = URL_PATTERN.sub(lambda m: m[0] if public_document_url(m[0]) else "<URL>", text)
    text = re.sub(r"\b(?:postgres(?:ql)?|redis)://[^\s<>]+", "<SECRET>", text)
    text = re.sub(r"\b[a-z][a-z0-9+.-]*://[^\s<>]*@[^\s<>]+", "<SECRET>", text, flags=re.IGNORECASE)
    return _TOKEN.sub("<SECRET>", _CREDENTIAL.sub("<SECRET>", text))
