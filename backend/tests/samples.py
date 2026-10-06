"""Sample travel documents generated in code (no binary fixtures in the repo)."""

import io

# ICAO 9303 specimen passport MRZ (valid check digits).
MRZ = (
    "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
    "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
)

PASSPORT_TEXT = f"""PASSPORT
Type P   Country code UTO
Surname ERIKSSON
Given names ANNA MARIA
Nationality: UTOPIAN
Date of birth: 12 AUG 1974
Date of issue: 16 APR 2007
Date of expiry: 15 APR 2012

{MRZ}
"""

FLIGHT_TICKET_TEXT = """ELECTRONIC TICKET RECEIPT
Passenger name: ASHA MEHTA
Booking reference: X7KQ2P
Ticket number: 724 2412345678
Airline: SWISS
Flight: LX 154
From: Mumbai (BOM)
To: Zurich (ZRH)
Departure date: 20 Oct 2026
Departure time: 01:45
Arrival time: 07:10
Terminal: 2
Seat: 34A
Baggage allowance: 1 x 23 kg
Total: CHF 812.40
"""

HOTEL_TEXT = [
    "Hotel reservation confirmation",
    "Guest name: Asha Mehta",
    "Hotel: The Strand Palace",
    "Address: 372 Strand, London WC2R 0JJ",
    "Check-in: 2026-10-20",
    "Check-out: 2026-10-23",
    "Confirmation number: HSP-99812",
    "Room type: Double",
]


def pdf_bytes(text: str) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 60), text, fontname="cour", fontsize=9)
    data = doc.tobytes()
    doc.close()
    return data


def scanned_pdf_bytes() -> bytes:
    """A PDF whose only page is an image (no text layer), like a scan."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=png_bytes())
    data = doc.tobytes()
    doc.close()
    return data


def docx_bytes(lines: list[str]) -> bytes:
    import docx

    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def png_bytes() -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (400, 120), "white")
    ImageDraw.Draw(image).text((10, 50), "BOARDING PASS LX 154", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
