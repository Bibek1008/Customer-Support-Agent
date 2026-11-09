"""Real-browser customer chat tests; app APIs are mocked to avoid cloud calls."""

from __future__ import annotations

import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

playwright = pytest.importorskip(
    "playwright.sync_api", reason="install .[e2e] to run browser tests"
)
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
WEBSITE = ROOT / "website"
CHROME_CANDIDATES = [
    Path(os.environ["CHROME_PATH"]) if os.environ.get("CHROME_PATH") else None,
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
]
CHROME = next((path for path in CHROME_CANDIDATES if path and path.is_file()), None)


@pytest.fixture(scope="module")
def web_origin():
    from support_agent.http_api import browser_page

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(WEBSITE), **kwargs)

        def end_headers(self):
            page_name = (
                "staff.html"
                if self.path.split("?", 1)[0] in {"/staff.html", "/admin/inbox"}
                else "chat.html"
            )
            policy = browser_page(page_name).headers["content-security-policy"]
            self.send_header("Content-Security-Policy", policy)
            super().end_headers()

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def browser_page(web_origin):
    if CHROME is None:
        pytest.skip("Install Chrome/Brave or set CHROME_PATH to run browser tests")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright_context:
        browser = playwright_context.chromium.launch(
            headless=True,
            executable_path=str(CHROME),
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
        page.set_default_timeout(5000)

        def mock_api(route):
            request = route.request
            path = request.url.removeprefix(web_origin).split("?", 1)[0]
            if path == "/api/session" and request.method == "POST":
                route.fulfill(
                    json={
                        "conversations": [],
                        "business_name": "Demo Office Store",
                        "business_mode": "demo",
                    }
                )
            elif path == "/api/conversations" and request.method == "POST":
                route.fulfill(json={"conversation_id": "browser-test-conversation"})
            elif path == "/api/olist/accounts":
                route.fulfill(
                    json={
                        "status": "ready",
                        "message": "Historical accounts available.",
                        "accounts": [{"alias": "demo-customer-01", "label": "Sample account 01"}],
                    }
                )
            elif path == "/api/session" and request.method == "DELETE":
                route.fulfill(status=204, body="")
            elif path.endswith("/demo-account") and request.method == "PUT":
                selected = json.loads(request.post_data or "{}")
                if selected.get("account_alias") != "demo-customer-01":
                    route.fulfill(status=404, json={"detail": "Unknown sample account."})
                else:
                    route.fulfill(
                        json={
                            "profile": "olist_demo",
                            "account": "demo-customer-01",
                            "orders": [
                                {
                                    "reference": "demo-order-000001",
                                    "recorded_status": "delivered",
                                    "purchase_date": "2018-01-01",
                                }
                            ],
                            "disclosure": "Historical sample data only.",
                        }
                    )
            elif path.startswith("/api/admin/"):
                if request.headers.get("authorization") != "Bearer browser-test-key":
                    route.fulfill(status=401, json={"detail": "Staff authentication required."})
                elif path == "/api/admin/tickets":
                    route.fulfill(
                        json=[
                            {
                                "id": "tkt-browser-demo",
                                "subject": "Return request",
                                "body": "Synthetic customer message.",
                                "status": "open",
                                "created_at": "2026-01-01T00:00:00Z",
                                "messages": [],
                                "replies": [],
                            }
                        ]
                    )
                elif path.endswith("/replies") and request.method == "POST":
                    route.fulfill(json={"saved": True})
                elif request.method == "PATCH":
                    route.fulfill(json={"status": "resolved"})
                else:
                    route.fulfill(json=[])
            elif path.startswith("/api/conversations/"):
                route.fulfill(json={"messages": []})
            elif path == "/chat":
                request_body = json.loads(request.post_data or "{}")
                if request_body.get("message") == "simulate unavailable service":
                    route.fulfill(
                        status=503,
                        json={"detail": "The assistant could not complete the response."},
                    )
                else:
                    route.fulfill(
                        json={
                            "conversation_id": request_body.get("conversation_id"),
                            "answer": "General Brazilian consumer law provides a seven-day withdrawal period for qualifying purchases; this is not Olist company policy.",
                            "confidence": 0.91,
                            "threshold": 0.65,
                            "handoff": False,
                            "citations": [
                                {
                                    "source_id": "returns-policy",
                                    "source_title": "Brazilian Consumer Defense Code",
                                    "chunk": "Article 49: seven-day withdrawal period for qualifying off-premises purchases.",
                                    "url": "https://www2.camara.leg.br/",
                                    "provenance": "official_legal_source",
                                    "metadata": {"jurisdiction": "BR", "section": "Article 49"},
                                }
                            ],
                        }
                    )
            else:
                route.fulfill(status=404, json={"detail": "Not found"})

        page.route("**/api/**", mock_api)
        page.route("**/chat", mock_api)
        page.goto(web_origin + "/chat.html")
        expect(page.locator("#status-text")).to_contain_text("Historical dataset ready")
        yield page
        browser.close()


def test_mobile_customer_can_send_and_open_cited_answer(browser_page):
    page = browser_page
    expect(page.get_by_role("button", name="End session")).to_be_visible()
    expect(page.get_by_role("button", name="New chat")).to_be_visible()
    page.get_by_role("textbox").fill("What is your return policy?")
    page.get_by_role("button", name="Send").click()
    expect(
        page.get_by_text("General Brazilian consumer law provides", exact=False).first
    ).to_be_visible()
    expect(page.get_by_text("Answered")).to_be_visible()
    page.get_by_text("View sources (1)").click()
    expect(page.get_by_text("Brazilian Consumer Defense Code")).to_be_visible()
    expect(page.get_by_text("Official legal source", exact=False).last).to_be_visible()


def test_chat_failure_keeps_message_for_retry(browser_page):
    page = browser_page
    question = "simulate unavailable service"
    page.get_by_role("textbox").fill(question)
    page.get_by_role("button", name="Send").click()
    expect(page.get_by_text("The assistant could not complete the response.")).to_be_visible()
    expect(page.get_by_role("textbox")).to_have_value(question)


def test_ending_session_clears_local_conversation_and_disables_compose(browser_page):
    page = browser_page
    page.wait_for_function("localStorage.getItem('support_conversation') !== null")
    page.get_by_role("button", name="End session").click()
    expect(page.locator("#status-text")).to_contain_text("Session ended")
    expect(page.get_by_role("textbox")).to_be_disabled()
    assert page.evaluate("localStorage.getItem('support_conversation')") is None


def test_customer_can_select_only_the_mocked_olist_demo_account(browser_page):
    page = browser_page
    select = page.get_by_label("Choose a historical customer profile")
    expect(select.locator("option").nth(1)).to_have_text("Sample account 01")
    select.select_option("demo-customer-01")
    page.get_by_role("button", name="Explore this profile").click()
    expect(page.get_by_text("Sample account 01 selected.", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="demo-order-000001", exact=False)).to_be_visible()
    assert (
        page.evaluate("localStorage.getItem('support_conversation')") == "browser-test-conversation"
    )


def test_uninitialized_dataset_has_no_successful_connection_or_office_fallback(browser_page):
    page = browser_page
    page.route(
        "**/api/olist/accounts",
        lambda route: route.fulfill(
            json={
                "status": "not_initialized",
                "accounts": [],
                "message": "Olist dataset has not been initialized. Complete the approved data import before account selection.",
            }
        ),
    )
    page.reload()
    expect(page.locator("#status-text")).to_contain_text("Dataset not initialized")
    expect(page.get_by_role("button", name="Explore this profile")).to_be_disabled()
    expect(page.locator("#dataset-message")).to_contain_text("data import")
    expect(page.locator("#business-note")).to_contain_text("Independent application")
    expect(page.get_by_role("button", name="View order history", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Ask about return rights")).to_be_enabled()


def test_office_store_is_explicit_and_separate(browser_page):
    page = browser_page
    page.get_by_role("button", name="Open separate Office Store").click()
    expect(page.locator("#business-note")).to_contain_text("Separate Office Store")
    expect(page.locator(".topics")).to_be_hidden()
    expect(page.locator(".olist-demo")).to_be_hidden()
    page.get_by_role("button", name="Return to historical records").click()
    expect(page.locator("#business-note")).to_contain_text("Independent application")
    expect(page.locator(".olist-demo")).to_be_visible()


def test_layout_mobile_and_desktop(browser_page):
    page = browser_page
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path=str(ROOT / ".cache" / "olist-mobile.png"), full_page=True)
    page.set_viewport_size({"width": 1440, "height": 1050})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path=str(ROOT / ".cache" / "olist-desktop.png"), full_page=True)


def test_staff_inbox_requires_key_and_keeps_key_in_memory(browser_page):
    page = browser_page
    page.goto(page.url.replace("/chat.html", "/staff.html"))
    page.get_by_label("Staff access key").fill("wrong-key")
    page.get_by_role("button", name="Unlock inbox").click()
    expect(page.get_by_role("alert")).to_contain_text("Staff authentication required")
    expect(page.locator("#login")).to_be_visible()

    page.get_by_label("Staff access key").fill("browser-test-key")
    page.get_by_role("button", name="Unlock inbox").click()
    expect(page.get_by_role("heading", name="Return request")).to_be_visible()
    expect(page.get_by_role("button", name="Sign out")).to_be_visible()
    expect(page.locator("#key")).to_have_value("")

    reply = page.get_by_label("Reply for tkt-browser-demo")
    reply.fill("Synthetic staff reply")
    page.get_by_role("button", name="Send reply").click()
    expect(page.get_by_text("Reply saved.")).to_be_visible()
    page.get_by_role("button", name="Sign out").click()
    expect(page.locator("#login")).to_be_visible()
    expect(page.locator("#list")).to_be_empty()
