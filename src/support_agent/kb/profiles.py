"""Retrieval boundaries for curated documents; transaction rows are never RAG."""

from urllib.parse import urlparse

PROFILES = ("olist_transaction_profile", "brazil_consumer_law", "olist_demo_policy", "office_store")
LEGAL_URLS = {
    "https://www2.camara.leg.br/legin/fed/lei/1990/lei-8078-11-setembro-1990-365086-normaatualizada-pl.pdf",
    "https://www2.camara.leg.br/legin/fed/decret/2013/decreto-7962-15-marco-2013-775557-publicacaooriginal-139266-pe.html",
}
LEGAL_FIELDS = (
    "title",
    "authority",
    "url",
    "section",
    "retrieved_at",
    "jurisdiction",
    "status",
    "content_version",
    "source_kind",
)


def validate_document(profile: str, meta: dict) -> None:
    if profile not in PROFILES:
        raise ValueError(
            "Choose a supported retrieval profile; legacy olist_demo must be re-ingested explicitly."
        )
    if profile != "office_store" and meta.get("profile") != profile:
        raise ValueError("Document profile metadata must match the requested profile.")
    if meta.get("source_kind") in {"transaction", "review", "customer_feedback"}:
        raise ValueError("Transaction and review records cannot be ingested as policy documents.")
    if profile == "brazil_consumer_law":
        if any(not meta.get(f) for f in LEGAL_FIELDS):
            raise ValueError("Legal documents require complete provenance metadata.")
        if (
            meta["url"] not in LEGAL_URLS
            or meta["jurisdiction"] != "BR"
            or meta["source_kind"] != "official_legal_source"
        ):
            raise ValueError("Legal sources must be verified official Brazilian sources.")
    elif (
        profile == "olist_transaction_profile"
        and meta.get("source_kind") != "dataset_documentation"
    ):
        raise ValueError(
            "The transaction retrieval profile accepts dataset documentation only, never rows."
        )
    elif profile == "olist_demo_policy" and meta.get("source_kind") != "demonstration_assumption":
        raise ValueError("Demo procedures must be labeled demonstration assumptions.")
    elif profile == "office_store" and (
        meta.get("profile", profile) != profile
        or urlparse(meta.get("url", "")).hostname in {"www2.camara.leg.br", "www.planalto.gov.br"}
    ):
        raise ValueError("Office Store documents must remain in their own profile.")
