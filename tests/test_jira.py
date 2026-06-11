"""Tests for the OraFlow Jira integration.

These are local, fully-mocked unit tests. They do NOT hit Atlassian. The HTTP
client is exercised via ``httpx.MockTransport`` so the real wire format is
covered without network access.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from oraflow.jira import evidence as evidence_module
from oraflow.jira.adf import adf_to_text
from oraflow.jira.client import (
    DEFAULT_PER_FILE_MAX_BYTES,
    JiraClient,
    JiraError,
    normalize_issue_key,
    redact_token,
    sanitize_attachment_filename,
)
from oraflow.jira.config import (
    JiraCredentials,
    jira_credentials_doctor,
    load_jira_credentials,
)
from oraflow.jira.evidence import fetch_ticket, ticket_evidence_dir
from oraflow.jira.jql_help import KNOWN_JQL_HELP_TOPICS, jira_jql_help
from oraflow.jira.related import (
    derive_search_terms,
    extract_related_from_issue,
    fetch_related_tickets,
    find_similar_tickets,
    list_related_tickets,
    scan_text_references,
)

# -------------------------------- ADF ----------------------------------------


def test_adf_plain_paragraph_extracted():
    doc = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Hello world"}],
            }
        ],
    }
    text = adf_to_text(doc).strip()
    assert text == "Hello world"


def test_adf_handles_none_and_strings():
    assert adf_to_text(None) == ""
    assert adf_to_text("already a string") == "already a string"


def test_adf_list_and_hardbreak():
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "bulletList",
                "content": [
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "one"}]}]},
                    {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "two"}]}]},
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "before"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "after"},
                ],
            },
        ],
    }
    text = adf_to_text(doc)
    assert "- one" in text
    assert "- two" in text
    assert "before\nafter" in text


def test_adf_mention_and_codeblock():
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "hi "},
                    {"type": "mention", "attrs": {"text": "@Abdul", "displayName": "Abdul"}},
                ],
            },
            {
                "type": "codeBlock",
                "attrs": {"language": "sql"},
                "content": [{"type": "text", "text": "SELECT 1 FROM dual"}],
            },
        ],
    }
    text = adf_to_text(doc)
    assert "@@Abdul" in text or "@Abdul" in text
    assert "```sql" in text
    assert "SELECT 1 FROM dual" in text


# ---------------------------- issue key validation ---------------------------


def test_normalize_issue_key_accepts_lowercase_and_uppercase():
    assert normalize_issue_key("erxd-73437") == "ERXD-73437"
    assert normalize_issue_key("ERXD-73437") == "ERXD-73437"
    assert normalize_issue_key("  erxd-1  ") == "ERXD-1"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "ERXD",  # no number
        "73437",  # no project
        "ERXD--73437",  # bogus
        "../ERXD-73437",  # path injection attempt
        "ERXD-73437/extra",
        "DROP TABLE",
    ],
)
def test_normalize_issue_key_rejects_garbage(bad):
    with pytest.raises(ValueError):
        normalize_issue_key(bad)


# -------------------------------- redaction ---------------------------------


def test_redact_token_replaces_token_value():
    token = "ATATT3xFf-secret-123"
    assert redact_token(f"Bearer {token} found", token) == "Bearer *** found"
    assert redact_token("no token here", token) == "no token here"
    assert redact_token("", token) == ""


# ---------------------------- credentials loading ----------------------------


def test_load_jira_credentials_from_file(tmp_path: Path):
    cred_file = tmp_path / "jira.toml"
    cred_file.write_text(
        'base_url = "https://example.atlassian.net"\n'
        'email = "abdul@example.com"\n'
        'api_token = "ATATT_secret"\n'
        'timeout_s = 45\n',
        encoding="utf-8",
    )
    creds = load_jira_credentials(cred_file)
    assert creds.base_url == "https://example.atlassian.net"
    assert creds.email == "abdul@example.com"
    assert creds.api_token == "ATATT_secret"
    assert creds.timeout_s == 45
    redacted = creds.redacted()
    assert redacted["api_token"] == "***"
    assert "ATATT_secret" not in json.dumps(redacted)


def test_load_jira_credentials_accepts_nested_jira_table(tmp_path: Path):
    cred_file = tmp_path / "jira.toml"
    cred_file.write_text(
        "[jira]\n"
        'base_url = "https://example.atlassian.net"\n'
        'email = "x@example.com"\n'
        'api_token = "t"\n',
        encoding="utf-8",
    )
    creds = load_jira_credentials(cred_file)
    assert creds.base_url == "https://example.atlassian.net"
    assert creds.email == "x@example.com"


def test_load_jira_credentials_rejects_plain_http_base_url(tmp_path: Path):
    cred_file = tmp_path / "jira.toml"
    cred_file.write_text(
        'base_url = "http://example.atlassian.net"\nemail = "x@example.com"\napi_token = "t"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="https"):
        load_jira_credentials(cred_file)


def test_load_jira_credentials_env_overrides_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cred_file = tmp_path / "jira.toml"
    cred_file.write_text(
        'base_url = "https://file.example.com"\n'
        'email = "file@example.com"\n'
        'api_token = "from-file"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ORAFLOW_JIRA_BASE_URL", "https://env.example.com")
    monkeypatch.setenv("ORAFLOW_JIRA_EMAIL", "env@example.com")
    monkeypatch.setenv("ORAFLOW_JIRA_API_TOKEN", "from-env")
    creds = load_jira_credentials(cred_file)
    assert creds.base_url == "https://env.example.com"
    assert creds.email == "env@example.com"
    assert creds.api_token == "from-env"


def test_load_jira_credentials_missing_file_and_no_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for var in ("ORAFLOW_JIRA_BASE_URL", "ORAFLOW_JIRA_EMAIL", "ORAFLOW_JIRA_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(FileNotFoundError):
        load_jira_credentials(tmp_path / "missing.toml")


def test_jira_credentials_doctor_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for var in ("ORAFLOW_JIRA_BASE_URL", "ORAFLOW_JIRA_EMAIL", "ORAFLOW_JIRA_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    result = jira_credentials_doctor(tmp_path / "absent.toml")
    assert result["status"] == "MISSING_FILE"
    assert "id.atlassian.com" in result["hint"]


def test_jira_credentials_doctor_ok(tmp_path: Path):
    cred_file = tmp_path / "jira.toml"
    cred_file.write_text(
        'base_url = "https://x.atlassian.net"\nemail = "e@x"\napi_token = "t"\n',
        encoding="utf-8",
    )
    result = jira_credentials_doctor(cred_file)
    assert result["status"] == "OK"
    assert result["credentials"]["api_token"] == "***"


def test_jira_credentials_doctor_tool_verifies_auth(monkeypatch: pytest.MonkeyPatch):
    import oraflow.server as server

    class StubClient:
        def __init__(self, credentials: JiraCredentials):
            self.credentials = credentials

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get_myself(self) -> dict:
            return {"accountType": "atlassian", "active": True, "displayName": "Test User"}

    monkeypatch.setattr(server, "diagnose_jira_credentials", lambda: {"status": "OK", "credentials": {"api_token": "***"}})
    monkeypatch.setattr(server, "load_jira_credentials", _creds)
    monkeypatch.setattr(server, "JiraClient", StubClient)

    result = server.jira_credentials_doctor()

    assert result["status"] == "AUTH_OK"
    assert result["auth"] == {
        "ok": True,
        "account_type": "atlassian",
        "active": True,
        "display_name": "Test User",
    }


def test_jira_credentials_doctor_tool_reports_auth_failure(monkeypatch: pytest.MonkeyPatch):
    import oraflow.server as server

    class FailingClient:
        def __init__(self, credentials: JiraCredentials):
            self.credentials = credentials

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get_myself(self) -> dict:
            raise JiraError("Jira GET /rest/api/3/myself returned HTTP 401: Client must be authenticated")

    monkeypatch.setattr(server, "diagnose_jira_credentials", lambda: {"status": "OK", "credentials": {"api_token": "***"}})
    monkeypatch.setattr(server, "load_jira_credentials", _creds)
    monkeypatch.setattr(server, "JiraClient", FailingClient)

    result = server.jira_credentials_doctor()

    assert result["status"] == "AUTH_FAILED"
    assert result["auth"]["ok"] is False
    assert "401" in result["auth"]["error"]


# ------------------------------ HTTP client ---------------------------------


def _creds() -> JiraCredentials:
    return JiraCredentials(
        base_url="https://example.atlassian.net",
        email="abdul@example.com",
        api_token="ATATT_secret_token",
        timeout_s=10,
    )


def _make_client(handler) -> JiraClient:
    creds = _creds()
    transport = httpx.MockTransport(handler)
    http = httpx.Client(
        base_url=creds.base_url,
        transport=transport,
        auth=(creds.email, creds.api_token),
        headers={"Accept": "application/json", "User-Agent": "test"},
    )
    return JiraClient(creds, http_client=http)


def test_jira_client_uses_system_trust_verifier(monkeypatch: pytest.MonkeyPatch):
    import oraflow.jira.client as client_module

    captured: dict = {}
    verifier = object()

    class DummyHttpClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def close(self) -> None:
            return None

    monkeypatch.setattr(client_module, "_create_ssl_verify_context", lambda: verifier)
    monkeypatch.setattr(client_module.httpx, "Client", DummyHttpClient)

    client = JiraClient(_creds())
    client.close()

    assert captured["verify"] is verifier


def test_get_issue_json_happy_path():
    issue_payload = {
        "key": "ERXD-73437",
        "fields": {"summary": "Test ticket", "status": {"name": "Open"}, "attachment": []},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/rest/api/3/issue/ERXD-73437"
        assert "expand" in request.url.params
        return httpx.Response(200, json=issue_payload)

    with _make_client(handler) as client:
        result = client.get_issue_json("erxd-73437")
        assert result["key"] == "ERXD-73437"


def test_jira_error_redacts_token_from_message():
    def handler(request: httpx.Request) -> httpx.Response:
        # Return an error body that does NOT include the token; the test verifies
        # that even if the URL or body somehow leaked it, redaction would kick in.
        return httpx.Response(500, text="boom ATATT_secret_token leaked")

    with _make_client(handler) as client, pytest.raises(JiraError) as exc_info:
        client.get_issue_json("ERXD-1")
    assert "ATATT_secret_token" not in str(exc_info.value)
    assert "***" in str(exc_info.value)


def test_iter_comments_handles_pagination():
    pages = [
        {"comments": [{"id": "1"}, {"id": "2"}], "total": 3, "startAt": 0, "maxResults": 2},
        {"comments": [{"id": "3"}], "total": 3, "startAt": 2, "maxResults": 2},
    ]
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/api/3/issue/ERXD-1/comment"
        payload = pages[call_count["n"]]
        call_count["n"] += 1
        return httpx.Response(200, json=payload)

    with _make_client(handler) as client:
        all_comments = client.iter_comments("ERXD-1", page_size=2)
    assert [c["id"] for c in all_comments] == ["1", "2", "3"]
    assert call_count["n"] == 2


def test_get_issue_xml_returns_text():
    xml_body = '<?xml version="1.0"?><rss><channel><item><key>ERXD-1</key></item></channel></rss>'

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/si/jira.issueviews:issue-xml/ERXD-1/ERXD-1.xml"
        return httpx.Response(200, text=xml_body, headers={"content-type": "application/xml"})

    with _make_client(handler) as client:
        assert client.get_issue_xml("ERXD-1") == xml_body


def test_search_uses_enhanced_post_with_jql_body():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/rest/api/3/search/jql"
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"issues": [], "isLast": True})

    with _make_client(handler) as client:
        payload = client.search("project = ERXD", max_results=10)
    assert captured["body"]["jql"] == "project = ERXD"
    assert captured["body"]["maxResults"] == 10
    assert "startAt" not in captured["body"]
    assert payload["startAt"] == 0
    assert payload["maxResults"] == 10


def test_search_start_at_walks_next_page_token():
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/api/3/search/jql"
        body = json.loads(request.content.decode("utf-8"))
        captured.append(body)
        if len(captured) == 1:
            assert body["maxResults"] == 2
            assert "nextPageToken" not in body
            return httpx.Response(
                200,
                json={
                    "issues": [{"key": "ERXD-1"}, {"key": "ERXD-2"}],
                    "isLast": False,
                    "nextPageToken": "page-2",
                },
            )
        assert body["nextPageToken"] == "page-2"
        return httpx.Response(200, json={"issues": [{"key": "ERXD-3"}], "isLast": True})

    with _make_client(handler) as client:
        payload = client.search("project = ERXD", max_results=5, start_at=2)

    assert payload["issues"] == [{"key": "ERXD-3"}]
    assert payload["startAt"] == 2
    assert payload["maxResults"] == 5


def test_download_attachment_streams_to_disk(tmp_path: Path):
    payload = b"x" * (3 * 64 * 1024)  # 192 KB across multiple chunks

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    from oraflow.jira.client import AttachmentMeta

    att = AttachmentMeta(
        id="9001",
        filename="log.txt",
        size=len(payload),
        mime_type="text/plain",
        created=None,
        author=None,
        content_url="https://example.atlassian.net/secure/attachment/9001/log.txt",
    )
    dest = tmp_path / "log.txt"
    with _make_client(handler) as client:
        client.download_attachment(att, dest)
    assert dest.is_file()
    assert dest.read_bytes() == payload
    assert att.local_path == str(dest)
    assert att.downloaded_bytes == len(payload)


def test_download_attachment_enforces_size_cap(tmp_path: Path):
    payload = b"y" * (200 * 1024)  # 200 KB

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    from oraflow.jira.client import AttachmentMeta

    att = AttachmentMeta(
        id="9002",
        filename="huge.bin",
        size=len(payload),
        mime_type=None,
        created=None,
        author=None,
        content_url="https://example.atlassian.net/secure/attachment/9002/huge.bin",
    )
    dest = tmp_path / "huge.bin"
    with _make_client(handler) as client:
        client.download_attachment(att, dest, max_bytes=50 * 1024)  # cap below payload
    assert not dest.is_file()
    assert att.local_path is None
    assert att.skipped_reason and "cap" in att.skipped_reason


def test_sanitize_attachment_filename_removes_path_traversal_segments():
    assert sanitize_attachment_filename("../escape.txt") == "escape.txt"
    assert sanitize_attachment_filename("..\\escape.txt") == "escape.txt"
    assert sanitize_attachment_filename("nested/log.txt") == "log.txt"
    assert sanitize_attachment_filename("CON") == "_CON"


def test_download_attachments_keeps_sanitized_filenames_under_dest_dir(tmp_path: Path):
    payload = b"safe"
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, content=payload)

    from oraflow.jira.client import AttachmentMeta

    att = AttachmentMeta(
        id="9003",
        filename="../escape.txt",
        size=len(payload),
        mime_type=None,
        created=None,
        author=None,
        content_url="https://example.atlassian.net/secure/attachment/9003/escape.txt",
    )
    dest_dir = tmp_path / "attachments"
    with _make_client(handler) as client:
        report = client.download_attachments([att], dest_dir)
    assert len(report.fetched) == 1
    assert (dest_dir / "escape.txt").read_bytes() == payload
    assert not (tmp_path / "escape.txt").exists()
    assert seen_paths == ["/secure/attachment/9003/escape.txt"]


def test_download_attachment_rejects_unexpected_attachment_host(tmp_path: Path):
    from oraflow.jira.client import AttachmentMeta

    att = AttachmentMeta(
        id="9004",
        filename="log.txt",
        size=1,
        mime_type=None,
        created=None,
        author=None,
        content_url="https://evil.example.com/secure/attachment/9004/log.txt",
    )
    with _make_client(lambda request: httpx.Response(200, content=b"x")) as client:
        client.download_attachment(att, tmp_path / "log.txt")
    assert att.local_path is None
    assert att.skipped_reason and "unexpected host" in att.skipped_reason


def test_download_attachment_ssl_error_mentions_system_trust(tmp_path: Path):
    from oraflow.jira.client import AttachmentMeta

    class FailingStream:
        def __enter__(self):
            raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    class FailingHttpClient:
        def stream(self, method: str, url: str):
            return FailingStream()

        def close(self) -> None:
            return None

    att = AttachmentMeta(
        id="9005",
        filename="screenshot.jpg",
        size=1,
        mime_type="image/jpeg",
        created=None,
        author=None,
        content_url="https://example.atlassian.net/secure/attachment/9005/screenshot.jpg",
    )
    with JiraClient(_creds(), http_client=FailingHttpClient()) as client:
        client.download_attachment(att, tmp_path / "screenshot.jpg")

    assert att.local_path is None
    assert att.skipped_reason and "system trust store" in att.skipped_reason


# ------------------------------ evidence pipeline ----------------------------


def _patch_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect the OraFlow workspace root for these tests."""
    monkeypatch.setattr(evidence_module, "resolve_workspace_dir", lambda: tmp_path)
    return tmp_path


def test_fetch_ticket_writes_all_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_workspace(monkeypatch, tmp_path)

    issue_payload = {
        "key": "ERXD-1",
        "fields": {
            "summary": "Investigate duplicate prescriber addresses",
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Bug"},
            "priority": {"name": "High"},
            "assignee": {"displayName": "Abdul"},
            "reporter": {"displayName": "Boss"},
            "created": "2026-05-01T10:00:00.000+0000",
            "updated": "2026-05-10T10:00:00.000+0000",
            "labels": ["L3", "Kinney"],
            "components": [{"name": "TREXONE"}],
            "description": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Customer Kinney shows duplicate addresses."}]}],
            },
            "attachment": [
                {
                    "id": "5001",
                    "filename": "lemed.txt",
                    "size": 11,
                    "mimeType": "text/plain",
                    "created": "2026-05-01T10:00:00.000+0000",
                    "author": {"displayName": "Tester"},
                    "content": "https://example.atlassian.net/secure/attachment/5001/lemed.txt",
                }
            ],
            "comment": {"comments": [], "total": 1},
        },
    }
    comments_page = {
        "comments": [
            {
                "id": "7001",
                "created": "2026-05-02T11:00:00.000+0000",
                "author": {"displayName": "Reviewer"},
                "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Looks bad in PROD."}]}]},
            }
        ],
        "total": 1,
        "startAt": 0,
        "maxResults": 100,
    }
    attachment_bytes = b"hello world"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/api/3/issue/ERXD-1":
            return httpx.Response(200, json=issue_payload)
        if path == "/rest/api/3/issue/ERXD-1/comment":
            return httpx.Response(200, json=comments_page)
        if path.endswith("/secure/attachment/5001/lemed.txt"):
            return httpx.Response(200, content=attachment_bytes)
        return httpx.Response(404, text=f"unhandled {path}")

    client = _make_client(handler)
    try:
        result = fetch_ticket("erxd-1", client=client, credentials=_creds(), fetch_attachments=True)
    finally:
        client.close()

    assert result.key == "ERXD-1"
    assert result.summary == "Investigate duplicate prescriber addresses"
    assert result.status == "In Progress"
    assert result.comment_count == 1
    assert result.attachment_count == 1
    assert result.attachments_fetched == 1
    assert result.attachments_skipped == 0
    assert result.attachments_total_bytes == len(attachment_bytes)

    evidence_dir = Path(result.evidence_dir)
    assert evidence_dir == ticket_evidence_dir("ERXD-1")
    assert (evidence_dir / "issue.json").is_file()
    assert (evidence_dir / "comments.json").is_file()
    # XML export intentionally dropped (JSON-only pipeline; less context bloat for LLMs).
    assert not (evidence_dir / "issue.xml").exists()
    summary = (evidence_dir / "summary.md").read_text(encoding="utf-8")
    assert "ERXD-1" in summary
    assert "duplicate addresses" in summary
    assert "Looks bad in PROD." in summary
    assert "lemed.txt" in summary

    attachment_file = evidence_dir / "attachments" / "lemed.txt"
    assert attachment_file.is_file()
    assert attachment_file.read_bytes() == attachment_bytes

    audit_log = tmp_path / "OraFlow" / "jira" / "_audit" / "fetches.jsonl"
    assert audit_log.is_file()
    row = json.loads(audit_log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["key"] == "ERXD-1"
    assert row["attachments_fetched"] == 1
    assert row["error"] is None
    ticket_audit_log = evidence_dir / "fetches.jsonl"
    assert ticket_audit_log.is_file()


def test_fetch_ticket_does_not_call_xml_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """JSON-only pipeline: confirm the classic XML endpoint is never hit."""
    _patch_workspace(monkeypatch, tmp_path)

    issue_payload = {"key": "ERXD-2", "fields": {"summary": "x", "attachment": [], "comment": {"comments": [], "total": 0}}}
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen_paths.append(path)
        if path == "/rest/api/3/issue/ERXD-2":
            return httpx.Response(200, json=issue_payload)
        if path == "/rest/api/3/issue/ERXD-2/comment":
            return httpx.Response(200, json={"comments": [], "total": 0, "startAt": 0, "maxResults": 100})
        if "issue-xml" in path:
            raise AssertionError(f"XML endpoint must not be called: {path}")
        return httpx.Response(404)

    client = _make_client(handler)
    try:
        result = fetch_ticket("ERXD-2", client=client, credentials=_creds())
    finally:
        client.close()

    assert not any("issue-xml" in p for p in seen_paths)
    assert not (Path(result.evidence_dir) / "issue.xml").exists()


def test_fetch_ticket_skips_attachments_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_workspace(monkeypatch, tmp_path)

    issue_payload = {
        "key": "ERXD-3",
        "fields": {
            "summary": "x",
            "attachment": [
                {
                    "id": "1",
                    "filename": "a.txt",
                    "size": 5,
                    "content": "https://example.atlassian.net/secure/attachment/1/a.txt",
                }
            ],
            "comment": {"comments": [], "total": 0},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/api/3/issue/ERXD-3":
            return httpx.Response(200, json=issue_payload)
        if path == "/rest/api/3/issue/ERXD-3/comment":
            return httpx.Response(200, json={"comments": [], "total": 0})
        # Attachment URL and XML endpoint should NOT be hit.
        raise AssertionError(f"unexpected request to {path}")

    client = _make_client(handler)
    try:
        result = fetch_ticket("ERXD-3", client=client, credentials=_creds())
    finally:
        client.close()

    assert result.attachment_count == 1
    assert result.attachments_fetched == 0
    attachments_dir = Path(result.evidence_dir) / "attachments"
    assert not attachments_dir.exists() or not any(attachments_dir.iterdir())


def test_fetch_ticket_per_ticket_size_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_workspace(monkeypatch, tmp_path)

    issue_payload = {
        "key": "ERXD-4",
        "fields": {
            "summary": "x",
            "attachment": [
                {"id": "1", "filename": "a.bin", "size": 600, "content": "https://example.atlassian.net/a.bin"},
                {"id": "2", "filename": "b.bin", "size": 600, "content": "https://example.atlassian.net/b.bin"},
            ],
            "comment": {"comments": [], "total": 0},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/api/3/issue/ERXD-4":
            return httpx.Response(200, json=issue_payload)
        if path == "/rest/api/3/issue/ERXD-4/comment":
            return httpx.Response(200, json={"comments": [], "total": 0})
        if path == "/a.bin":
            return httpx.Response(200, content=b"a" * 600)
        if path == "/b.bin":
            return httpx.Response(200, content=b"b" * 600)
        return httpx.Response(404)

    client = _make_client(handler)
    try:
        # 1000-byte total cap should let the first 600-byte file through but
        # reject the second.
        result = fetch_ticket(
            "ERXD-4",
            client=client,
            credentials=_creds(),
            fetch_attachments=True,
            max_bytes_per_file=DEFAULT_PER_FILE_MAX_BYTES,
            max_bytes_total=1000,
        )
    finally:
        client.close()

    assert result.attachments_fetched == 1
    assert result.attachments_skipped == 1
    assert result.attachments_total_bytes == 600

# ------------------------- related/similar ticket expansion ------------------
def _related_issue_payload(key: str = "ERXD-10") -> dict:
    return {
        "key": key,
        "fields": {
            "summary": "Duplicate prescriber address for NPI 1669493565",
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Bug"},
            "labels": ["prescriber"],
            "components": [{"name": "Clinical"}],
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "See ERXD-12 and NPI 1669493565 for similar behavior."}
                        ],
                    }
                ],
            },
            "issuelinks": [
                {
                    "type": {"name": "Relates", "outward": "relates to"},
                    "outwardIssue": {
                        "key": "ERXD-11",
                        "fields": {
                            "summary": "Prior duplicate phone ticket",
                            "status": {"name": "Closed"},
                            "issuetype": {"name": "Bug"},
                        },
                    },
                }
            ],
            "parent": {"key": "ERXD-9", "fields": {"summary": "Parent issue"}},
            "subtasks": [{"key": "ERXD-13", "fields": {"summary": "Subtask issue"}}],
            "attachment": [],
            "comment": {"comments": [], "total": 1},
        },
    }
def test_extract_related_from_issue_finds_links_parent_and_subtasks():
    issue = _related_issue_payload()
    index = extract_related_from_issue(issue)
    assert index.key == "ERXD-10"
    assert [ref.key for ref in index.direct_links] == ["ERXD-11"]
    assert index.direct_links[0].relationship == "Relates"
    assert index.parent and index.parent.key == "ERXD-9"
    assert [ref.key for ref in index.subtasks] == ["ERXD-13"]
    assert index.unique_keys() == ["ERXD-11", "ERXD-9", "ERXD-13"]
def test_scan_text_references_finds_comment_mentions_and_excludes_self():
    issue = _related_issue_payload()
    comments = [
        {
            "created": "2026-05-01T10:00:00.000+0000",
            "author": {"displayName": "Reviewer"},
            "body": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "ERXD-14 looks similar; ERXD-10 is this ticket."}
                        ],
                    }
                ],
            },
        }
    ]
    refs = scan_text_references("ERXD-10", issue, comments)
    assert [ref.key for ref in refs] == ["ERXD-12", "ERXD-14"]
    assert all(ref.relationship == "text reference" for ref in refs)
def test_list_related_tickets_writes_index_and_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_workspace(monkeypatch, tmp_path)
    evidence_dir = ticket_evidence_dir("ERXD-10")
    (evidence_dir / "issue.json").write_text(json.dumps(_related_issue_payload()), encoding="utf-8")
    comments = [
        {
            "created": "2026-05-02T00:00:00.000+0000",
            "author": {"displayName": "BSA"},
            "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Also see ERXD-15."}]}]},
        }
    ]
    (evidence_dir / "comments.json").write_text(json.dumps(comments), encoding="utf-8")
    payload = list_related_tickets("ERXD-10")
    assert payload["key"] == "ERXD-10"
    assert [row["key"] for row in payload["direct_links"]] == ["ERXD-11"]
    assert payload["parent"]["key"] == "ERXD-9"
    assert [row["key"] for row in payload["subtasks"]] == ["ERXD-13"]
    assert "ERXD-15" in payload["unique_related_keys"]
    assert payload["suggested_jql"]
    assert (evidence_dir / "related_index.json").is_file()
    assert (evidence_dir / "related_summary.md").is_file()
def test_fetch_related_tickets_writes_nested_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_workspace(monkeypatch, tmp_path)
    parent_dir = ticket_evidence_dir("ERXD-10")
    (parent_dir / "issue.json").write_text(json.dumps(_related_issue_payload()), encoding="utf-8")
    (parent_dir / "comments.json").write_text("[]", encoding="utf-8")
    related_payload = {
        "key": "ERXD-11",
        "fields": {
            "summary": "Related ticket fetched",
            "status": {"name": "Closed"},
            "issuetype": {"name": "Bug"},
            "priority": {"name": "Medium"},
            "assignee": None,
            "reporter": {"displayName": "Reporter"},
            "created": "2026-05-01T00:00:00.000+0000",
            "updated": "2026-05-02T00:00:00.000+0000",
            "labels": [],
            "components": [],
            "description": None,
            "attachment": [],
            "comment": {"comments": [], "total": 0},
        },
    }
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/api/3/issue/ERXD-11":
            return httpx.Response(200, json=related_payload)
        if path == "/rest/api/3/issue/ERXD-11/comment":
            return httpx.Response(200, json={"comments": [], "total": 0})
        return httpx.Response(404, text=f"unhandled {path}")
    client = _make_client(handler)
    try:
        result = fetch_related_tickets(
            "ERXD-10",
            related_keys=["ERXD-11"],
            client=client,
            credentials=_creds(),
            fetch_attachments=False,
        )
    finally:
        client.close()
    related_dir = parent_dir / "related" / "ERXD-11"
    assert result["parent_key"] == "ERXD-10"
    assert len(result["fetched"]) == 1
    assert (related_dir / "issue.json").is_file()
    assert (related_dir / "comments.json").is_file()
    assert (related_dir / "summary.md").is_file()
    assert (parent_dir / "related_fetches.json").is_file()
def test_fetch_related_tickets_enforces_max_tickets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_workspace(monkeypatch, tmp_path)
    parent_dir = ticket_evidence_dir("ERXD-10")
    (parent_dir / "issue.json").write_text(json.dumps(_related_issue_payload()), encoding="utf-8")
    (parent_dir / "comments.json").write_text("[]", encoding="utf-8")
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path.split("/")[-1]
        if request.url.path.startswith("/rest/api/3/issue/") and not request.url.path.endswith("/comment"):
            return httpx.Response(200, json={"key": key, "fields": {"summary": key, "attachment": [], "comment": {"comments": [], "total": 0}}})
        if request.url.path.endswith("/comment"):
            return httpx.Response(200, json={"comments": [], "total": 0})
        return httpx.Response(404)
    client = _make_client(handler)
    try:
        result = fetch_related_tickets(
            "ERXD-10",
            related_keys=["ERXD-11", "ERXD-12", "ERXD-13"],
            client=client,
            credentials=_creds(),
            fetch_attachments=False,
            max_tickets=2,
        )
    finally:
        client.close()
    assert [row["key"] for row in result["fetched"]] == ["ERXD-11", "ERXD-12"]
    assert result["skipped"] == [{"key": "ERXD-13", "reason": "max_tickets cap (2)"}]
def test_find_similar_tickets_derives_terms_and_writes_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_workspace(monkeypatch, tmp_path)
    evidence_dir = ticket_evidence_dir("ERXD-10")
    (evidence_dir / "issue.json").write_text(json.dumps(_related_issue_payload()), encoding="utf-8")
    (evidence_dir / "comments.json").write_text("[]", encoding="utf-8")
    captured_jql: list[str] = []
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/search/jql":
            body = json.loads(request.content.decode("utf-8"))
            captured_jql.append(body["jql"])
            return httpx.Response(
                200,
                json={
                    "issues": [
                        {
                            "key": "ERXD-99",
                            "fields": {
                                "summary": "Similar prescriber duplicate",
                                "status": {"name": "Open"},
                                "assignee": {"displayName": "Analyst"},
                                "updated": "2026-05-03T00:00:00.000+0000",
                                "priority": {"name": "High"},
                                "issuetype": {"name": "Bug"},
                            },
                        }
                    ],
                    "total": 1,
                },
            )
        return httpx.Response(404)
    client = _make_client(handler)
    try:
        result = find_similar_tickets("ERXD-10", client=client, credentials=_creds(), max_results=5)
    finally:
        client.close()
    assert "1669493565" in result["terms"]
    assert captured_jql
    assert result["candidates"][0]["key"] == "ERXD-99"
    assert (evidence_dir / "similar_tickets.json").is_file()
def test_derive_search_terms_prioritizes_explicit_terms():
    terms = derive_search_terms(_related_issue_payload(), include_terms=["custom exact phrase"])
    assert terms[0] == "custom exact phrase"
# ------------------------------ JQL help ------------------------------------
def test_jira_jql_help_l3_contains_safe_custom_search_guidance():
    text = jira_jql_help("l3")
    assert "project = ERXD" in text
    assert "max_results=20" in text
    assert "jira_fetch_related_tickets" in text
    assert "1669493565" in text
def test_jira_jql_help_unknown_topic_lists_known_topics():
    text = jira_jql_help("not-a-topic")
    assert "Unknown JQL help topic" in text
    for topic in KNOWN_JQL_HELP_TOPICS:
        assert topic in text
def test_jira_jql_help_tool_delegates_to_helper():
    from oraflow.server import jira_jql_help as tool_jql_help
    text = tool_jql_help("escaping")
    assert "JQL escaping" in text
    assert 'text ~ "' in text
def test_jira_jql_help_hierarchy_includes_portfolio_children():
    text = jira_jql_help("hierarchy")
    assert "portfolioChildIssuesOf" in text
    assert "Initiative" in text
    assert "Epic" in text
    assert "jira_list_related_tickets" in text
def test_jira_jql_help_process_includes_issue_types_and_blocked_flag():
    text = jira_jql_help("process")
    assert "Story" in text
    assert "Task" in text
    assert "Bug" in text
    assert "Flag" in text
    assert "Discovered while testing" in text
def test_jira_jql_help_creation_includes_ticket_quality_and_linking_guidance():
    text = jira_jql_help("creation")
    assert "Ticket type decision guide" in text
    assert "Spike" in text
    assert "Bug evidence expectations" in text
    assert "Definition of Ready" in text
    assert "Definition of Done" in text
    assert "blocks" in text
    assert "is caused by" in text
def test_jira_jql_help_ticket_quality_is_preferred_alias_for_creation():
    ticket_quality = jira_jql_help("ticket_quality")
    creation = jira_jql_help("creation")
    assert ticket_quality == creation
    assert "read-only" in ticket_quality
    assert "do **not** create or modify Jira tickets via API" in ticket_quality
