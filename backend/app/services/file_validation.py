"""Upload validation: the file type comes from the bytes, never from the client's claim."""

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass

from app.core.errors import InvalidRequestError, PayloadTooLargeError, UnsupportedFileError

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TXT = "text/plain"

EXTENSIONS = {PDF: ".pdf", PNG: ".png", JPEG: ".jpg", DOCX: ".docx", TXT: ".txt"}


@dataclass(frozen=True)
class ValidatedFile:
    filename: str
    content_type: str


def sniff_content_type(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"PK\x03\x04"):
        return DOCX if _is_docx(data) else None
    if _is_text(data):
        return TXT
    return None


def _is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                return False
            # Refuse zip bombs: the uncompressed size must stay reasonable.
            return sum(i.file_size for i in archive.infolist()) < 200 * 1024 * 1024
    except (zipfile.BadZipFile, OSError, ValueError):
        return False


def _is_text(data: bytes) -> bool:
    if b"\x00" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def sanitize_filename(name: str | None, content_type: str) -> str:
    """A display name safe for headers and the UI: no paths, controls or odd characters."""
    name = unicodedata.normalize("NFKC", (name or "").replace("\\", "/").split("/")[-1])
    name = re.sub(r"[^\w.\- ()]+", "_", name).strip(" ._")[:200]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return f"{stem or 'document'}{EXTENSIONS[content_type]}"


def validate_upload(data: bytes, filename: str | None, max_bytes: int) -> ValidatedFile:
    if not data:
        raise InvalidRequestError("The file is empty.")
    if len(data) > max_bytes:
        raise PayloadTooLargeError(
            f"Files can be at most {max_bytes // (1024 * 1024)} MB."
        )
    content_type = sniff_content_type(data)
    if content_type is None:
        raise UnsupportedFileError()
    return ValidatedFile(filename=sanitize_filename(filename, content_type),
                         content_type=content_type)
