"""Upload -> background processing -> retrieval / download / deletion, through the API."""

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core import rate_limit
from app.core.config import get_settings
from app.db.models import (
    AuditLog,
    Document,
    DocumentPage,
    ExtractedEntity,
    JobStatus,
    ProcessingJob,
)
from app.services import document_processor, jobs
from app.services.malware import ScanResult
from app.services.storage import StorageError
from tests import samples
from tests.conftest import bearer, register

PDF_MIME = "application/pdf"


async def upload(client, token, data: bytes, name: str = "ticket.pdf",
                 mime: str = PDF_MIME):
    return await client.post("/api/documents", headers=bearer(token),
                             files={"file": (name, data, mime)})


async def upload_and_process(client, token, data, name="ticket.pdf"):
    response = await upload(client, token, data, name)
    assert response.status_code == 202, response.text
    await jobs.run_pending()
    doc_id = response.json()["id"]
    detail = await client.get(f"/api/documents/{doc_id}", headers=bearer(token))
    assert detail.status_code == 200
    return detail.json()


def field(detail, name, group=0):
    return next((f for f in detail["fields"] if f["field"] == name and f["group"] == group), None)


@pytest.fixture
async def second_token(client):
    response = await register(client, email="bob@example.com", name="Bob Other")
    client.cookies.clear()
    return response.json()["access_token"]


# ------------------------------------------------------------------ pipeline


async def test_pdf_flight_ticket_is_processed(client, user_token):
    queued = await upload(client, user_token, samples.pdf_bytes(samples.FLIGHT_TICKET_TEXT))
    assert queued.status_code == 202
    assert queued.json()["status"] == "queued"
    assert queued.json()["steps"] == {"uploaded": True, "scanned": False,
                                      "text_extracted": False, "fields_extracted": False,
                                      "indexed": False}

    await jobs.run_pending()
    detail = (await client.get(f"/api/documents/{queued.json()['id']}",
                               headers=bearer(user_token))).json()
    assert detail["status"] == "ready"
    assert detail["document_type"] == "flight_ticket"
    assert detail["analysis_method"] == "rules"
    assert detail["page_count"] == 1
    assert detail["steps"] == {"uploaded": True, "scanned": True,
                               "text_extracted": True, "fields_extracted": True,
                               "indexed": True}
    assert field(detail, "flight_number")["value"] == "LX154"
    assert field(detail, "pnr")["value"] == "X7KQ2P"
    assert field(detail, "departure_airport")["value"] == "BOM"
    assert field(detail, "arrival_airport")["value"] == "ZRH"
    assert field(detail, "departure_date")["value"] == "2026-10-20"
    assert field(detail, "departure_time")["value"] == "01:45"
    assert field(detail, "seat")["value"] == "34A"
    assert field(detail, "currency")["value"] == "CHF"
    # Every value carries its source page, confidence and method.
    assert field(detail, "pnr")["page"] == 1
    assert field(detail, "pnr")["method"] == "rules"
    # Ticket numbers are identifiers: masked in the API.
    ticket = field(detail, "ticket_number")
    assert ticket["masked"] and ticket["value"].startswith("****")


async def test_passport_mrz_is_verified_and_masked(client, user_token, db_session):
    detail = await upload_and_process(client, user_token, samples.PASSPORT_TEXT.encode(),
                                      "passport.txt")
    assert detail["document_type"] == "passport"
    number = field(detail, "passport_number")
    assert number["value"] == "****02C3" and number["masked"] and number["method"] == "mrz"
    assert field(detail, "full_name")["value"] == "ANNA MARIA ERIKSSON"
    assert field(detail, "nationality")["value"] == "UTO"
    assert field(detail, "expiry_date")["value"] == "2012-04-15"
    assert field(detail, "date_of_birth")["value"] == "1974-**-**"
    # The full value is stored server-side for the assistant to use.
    stored = (await db_session.execute(
        select(ExtractedEntity.value).where(ExtractedEntity.field == "passport_number")
    )).scalar_one()
    assert stored == "L898902C3"


async def test_docx_hotel_booking(client, user_token):
    detail = await upload_and_process(client, user_token, samples.docx_bytes(samples.HOTEL_TEXT),
                                      "hotel.docx")
    assert detail["document_type"] == "hotel_booking"
    assert field(detail, "hotel_name")["value"] == "The Strand Palace"
    assert field(detail, "check_in")["value"] == "2026-10-20"
    assert field(detail, "check_out")["value"] == "2026-10-23"
    assert field(detail, "confirmation_number")["value"] == "HSP-99812"


async def test_image_without_ocr_fails_with_explanation(client, user_token):
    detail = await upload_and_process(client, user_token, samples.png_bytes(), "pass.png")
    assert detail["status"] == "failed"
    assert detail["error_code"] == "ocr_unavailable"
    assert "text recognition" in detail["error_message"]
    # The scan passed; the failure is shown at the text-extraction step.
    assert detail["steps"]["scanned"] is True
    assert detail["steps"]["text_extracted"] is False
    # Timestamps are always explicit UTC.
    assert detail["created_at"].endswith(("Z", "+00:00"))


class FakeOcr:
    name = "fake"

    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    async def image_to_text(self, image: bytes, mime_type: str) -> str:
        assert image.startswith(b"\x89PNG")
        self.calls += 1
        return self.text


async def test_scanned_pdf_uses_ocr(client, user_token, monkeypatch):
    ocr = FakeOcr("BOARDING PASS\nPassenger: ASHA MEHTA\nFlight: LX 154\nGate: B34\n"
                  "Seat: 12C\nBoarding time: 00:55")
    monkeypatch.setattr(document_processor, "get_ocr", lambda: ocr)
    detail = await upload_and_process(client, user_token, samples.scanned_pdf_bytes(), "bp.pdf")
    assert ocr.calls == 1
    assert detail["ocr_used"] is True
    assert detail["document_type"] == "boarding_pass"
    assert field(detail, "gate")["value"] == "B34"
    assert field(detail, "boarding_time")["value"] == "00:55"


async def test_image_uses_ocr(client, user_token, monkeypatch):
    monkeypatch.setattr(document_processor, "get_ocr", lambda: FakeOcr(samples.PASSPORT_TEXT))
    detail = await upload_and_process(client, user_token, samples.png_bytes(), "scan.png")
    assert detail["status"] == "ready"
    assert detail["document_type"] == "passport"


async def test_infected_file_is_rejected_and_removed(client, user_token, monkeypatch, db_session):
    class Infected:
        name = "test"

        async def scan(self, data):
            return ScanResult(clean=False, signature="Eicar-Test-Signature")

    monkeypatch.setattr(document_processor, "get_scanner", lambda: Infected())
    detail = await upload_and_process(client, user_token, b"just text, honestly", "a.txt")
    assert detail["status"] == "rejected"
    assert detail["error_code"] == "malware_detected"
    assert detail["fields"] == []
    key = (await db_session.execute(select(Document.storage_key))).scalar_one()
    assert not Path(get_settings().STORAGE_LOCAL_PATH, key).exists()
    download = await client.get(f"/api/documents/{detail['id']}/file", headers=bearer(user_token))
    assert download.status_code == 404


# -------------------------------------------------------------- validation


@pytest.mark.parametrize("data,name,status,code", [
    (b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff", "setup.exe", 415, "unsupported_file"),
    (b"\x00\x01binary\x00junk", "notes.txt", 415, "unsupported_file"),
    (b"%PDF-1.7 broken", "fake.png", 202, None),  # type comes from the bytes, not the name
    (b"", "empty.pdf", 422, "invalid_request"),
])
async def test_upload_validation(client, user_token, data, name, status, code):
    response = await upload(client, user_token, data, name, "image/png")
    assert response.status_code == status, response.text
    if code:
        assert response.json()["error"]["code"] == code
    else:
        assert response.json()["content_type"] == PDF_MIME
        assert response.json()["filename"] == "fake.pdf"


async def test_damaged_pdf_fails_cleanly(client, user_token):
    detail = await upload_and_process(client, user_token, b"%PDF-1.7 broken", "x.pdf")
    assert detail["status"] == "failed"
    assert detail["error_code"] == "invalid_pdf"


async def test_size_limits(client, user_token):
    limit = get_settings().max_upload_bytes
    just_over = await upload(client, user_token, b"a" * (limit + 10), "big.txt", "text/plain")
    assert just_over.status_code == 413
    assert just_over.json()["error"]["code"] == "file_too_large"
    # Far over the limit: refused by the middleware before the body is parsed.
    huge = await upload(client, user_token, b"a" * (limit + 2 * 1024 * 1024), "huge.txt")
    assert huge.status_code == 413


async def test_duplicate_upload_rejected(client, user_token):
    data = samples.pdf_bytes(samples.FLIGHT_TICKET_TEXT)
    assert (await upload(client, user_token, data)).status_code == 202
    again = await upload(client, user_token, data, "copy.pdf")
    assert again.status_code == 409


async def test_filename_is_sanitised(client, user_token):
    response = await upload(client, user_token, b"hello", "../../etc/pass<script>wd.txt",
                            "text/plain")
    assert response.status_code == 202
    assert response.json()["filename"] == "pass_script_wd.txt"


async def test_upload_requires_auth(client):
    response = await client.post("/api/documents", files={"file": ("a.txt", b"hi", "text/plain")})
    assert response.status_code == 401


async def test_upload_rate_limit(client, user_token, monkeypatch):
    monkeypatch.setattr(get_settings(), "UPLOAD_RATE_LIMIT_PER_HOUR", 2)
    rate_limit.limiter.reset()
    for i in range(2):
        assert (await upload(client, user_token, f"doc {i}".encode(), "a.txt")).status_code == 202
    assert (await upload(client, user_token, b"doc 3", "a.txt")).status_code == 429


# ------------------------------------------------------------ storage security


async def test_files_are_encrypted_at_rest(client, user_token, db_session):
    data = samples.FLIGHT_TICKET_TEXT.encode()
    await upload(client, user_token, data, "ticket.txt", "text/plain")
    key = (await db_session.execute(select(Document.storage_key))).scalar_one()
    stored = Path(get_settings().STORAGE_LOCAL_PATH, key).read_bytes()
    assert b"X7KQ2P" not in stored and b"ASHA MEHTA" not in stored
    assert "ticket" not in key and "@" not in key  # no filename / PII in object keys


async def test_download_returns_original_with_safe_headers(client, user_token, db_session):
    data = samples.pdf_bytes(samples.FLIGHT_TICKET_TEXT)
    doc_id = (await upload(client, user_token, data, "My Ticket.pdf")).json()["id"]
    response = await client.get(f"/api/documents/{doc_id}/file", headers=bearer(user_token))
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == PDF_MIME
    assert "sandbox" in response.headers["content-security-policy"]
    assert "My%20Ticket.pdf" in response.headers["content-disposition"]
    actions = (await db_session.execute(select(AuditLog.action))).scalars().all()
    assert "document.download" in actions


# ------------------------------------------------------------- user isolation


async def test_other_users_cannot_see_or_touch_documents(client, user_token, second_token):
    doc_id = (await upload(client, user_token, b"private", "mine.txt")).json()["id"]
    await jobs.run_pending()

    assert (await client.get("/api/documents", headers=bearer(second_token))).json() == []
    for method, path in [("GET", f"/api/documents/{doc_id}"),
                         ("GET", f"/api/documents/{doc_id}/file"),
                         ("DELETE", f"/api/documents/{doc_id}"),
                         ("POST", f"/api/documents/{doc_id}/reprocess")]:
        response = await client.request(method, path, headers=bearer(second_token))
        assert response.status_code == 404, (method, path)
    # Still there for the owner.
    owner = await client.get(f"/api/documents/{doc_id}", headers=bearer(user_token))
    assert owner.status_code == 200


async def test_list_and_search(client, user_token):
    await upload_and_process(client, user_token, samples.PASSPORT_TEXT.encode(), "passport.txt")
    await upload_and_process(client, user_token, samples.docx_bytes(samples.HOTEL_TEXT),
                             "stay.docx")
    listed = (await client.get("/api/documents", headers=bearer(user_token))).json()
    assert [d["filename"] for d in listed] == ["stay.docx", "passport.txt"]  # newest first
    hotel = (await client.get("/api/documents?q=hotel", headers=bearer(user_token))).json()
    assert [d["filename"] for d in hotel] == ["stay.docx"]
    by_type = (await client.get("/api/documents?document_type=passport",
                                headers=bearer(user_token))).json()
    assert [d["filename"] for d in by_type] == ["passport.txt"]


# ------------------------------------------------------------------ deletion


async def test_delete_removes_file_and_all_derived_data(client, user_token, db_session):
    detail = await upload_and_process(client, user_token,
                                      samples.pdf_bytes(samples.FLIGHT_TICKET_TEXT))
    key = (await db_session.execute(select(Document.storage_key))).scalar_one()
    path = Path(get_settings().STORAGE_LOCAL_PATH, key)
    assert path.exists()

    response = await client.delete(f"/api/documents/{detail['id']}", headers=bearer(user_token))
    assert response.status_code == 204
    assert not path.exists()
    for model in (Document, DocumentPage, ExtractedEntity, ProcessingJob):
        count = (await db_session.execute(select(func.count()).select_from(model))).scalar_one()
        assert count == 0, model.__name__
    audit = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "document.delete")
    )).scalar_one()
    assert audit.resource_id == detail["id"]
    assert (await client.get(f"/api/documents/{detail['id']}",
                             headers=bearer(user_token))).status_code == 404


async def test_delete_keeps_everything_if_storage_is_down(client, user_token, monkeypatch,
                                                          db_session):
    doc_id = (await upload(client, user_token, b"keep me", "a.txt")).json()["id"]

    async def broken(*args, **kwargs):
        raise StorageError("down")

    from app.services.storage import get_storage
    monkeypatch.setattr(type(get_storage()), "delete", broken)
    response = await client.delete(f"/api/documents/{doc_id}", headers=bearer(user_token))
    assert response.status_code == 503
    assert (await db_session.execute(select(func.count()).select_from(Document))).scalar_one() == 1


# ------------------------------------------------------------- retries / jobs


async def test_transient_failure_is_retried_then_marked_failed(client, user_token, monkeypatch,
                                                               db_session):
    class Down:
        name = "down"

        async def scan(self, data):
            from app.services.malware import ScannerUnavailableError
            raise ScannerUnavailableError("connection refused")

    monkeypatch.setattr(document_processor, "get_scanner", lambda: Down())
    monkeypatch.setattr(jobs, "RETRY_BASE_SECONDS", 0)
    doc_id = (await upload(client, user_token, b"retry me", "a.txt")).json()["id"]

    await jobs.run_pending()
    job = (await db_session.execute(select(ProcessingJob))).scalar_one()
    assert job.attempts == job.max_attempts
    assert job.status == JobStatus.FAILED and job.last_error == "scanner_unavailable"
    detail = (await client.get(f"/api/documents/{doc_id}", headers=bearer(user_token))).json()
    assert detail["status"] == "failed" and detail["error_code"] == "scanner_unavailable"

    # Once the scanner is back, the user can retry.
    monkeypatch.undo()
    response = await client.post(f"/api/documents/{doc_id}/reprocess", headers=bearer(user_token))
    assert response.status_code == 202 and response.json()["status"] == "queued"
    await jobs.run_pending()
    detail = (await client.get(f"/api/documents/{doc_id}", headers=bearer(user_token))).json()
    assert detail["status"] == "ready"


async def test_reprocess_rules(client, user_token):
    doc_id = (await upload(client, user_token, b"fine", "a.txt")).json()["id"]
    url = f"/api/documents/{doc_id}/reprocess"
    # Not while it's still queued...
    assert (await client.post(url, headers=bearer(user_token))).status_code == 409
    await jobs.run_pending()
    # ...but a finished document can be re-run (e.g. to re-index it).
    assert (await client.post(url, headers=bearer(user_token))).status_code == 202


async def test_job_claimed_only_once(db_session, client, user_token):
    await upload(client, user_token, b"one", "a.txt")
    first = await jobs.claim_next(db_session)
    second = await jobs.claim_next(db_session)
    assert first is not None and second is None
