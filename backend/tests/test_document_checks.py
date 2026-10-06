"""Cross-document conflict checks (plain functions, no LLM)."""

from datetime import date

from app.agents.document_checks import DocFields, check

TODAY = date(2026, 10, 6)


def ticket(name="ticket.pdf", passenger="ASHA MEHTA", *dates: str) -> DocFields:
    fields = [("passenger_name", passenger, 1)]
    for i, d in enumerate(dates or ("2026-10-20",), start=1):
        fields += [("flight_number", f"LX{150 + i}", i), ("departure_date", d, i)]
    return DocFields(name, "flight_ticket", fields)


def passport(expiry="2031-01-01", holder="MEHTA ASHA") -> DocFields:
    return DocFields("passport.pdf", "passport",
                     [("full_name", holder, 1), ("expiry_date", expiry, 1)])


def hotel(check_in: str, check_out: str) -> DocFields:
    return DocFields("hotel.pdf", "hotel_booking",
                     [("check_in", check_in, 1), ("check_out", check_out, 1)])


def kinds(docs: list[DocFields]) -> list[tuple[str, str]]:
    return [(i.kind, i.severity) for i in check(docs, TODAY)]


def test_consistent_documents_have_no_issues():
    assert kinds([ticket(), passport(), hotel("2026-10-20", "2026-10-23")]) == []


def test_passenger_name_must_match_the_passport():
    assert kinds([ticket(passenger="Mehta, Asha Mrs"), passport()]) == []  # order, title
    issues = check([ticket(), passport(holder="ERIKSSON ANNA MARIA")], TODAY)
    assert [i.kind for i in issues] == ["name_mismatch"]
    assert "ASHA MEHTA" in issues[0].message and "ERIKSSON ANNA MARIA" in issues[0].message
    assert issues[0].documents == ["ticket.pdf", "passport.pdf"]


def test_passport_validity():
    assert kinds([passport("2012-04-15")]) == [("passport_expiry", "error")]  # expired
    assert kinds([ticket(), passport("2027-01-15")]) == [("passport_expiry", "warning")]
    assert kinds([ticket(), passport("2026-10-10")]) == [("passport_expiry", "error")]
    assert kinds([ticket(), passport("2027-04-20")]) == []  # exactly 6 months: fine
    assert kinds([ticket("old.pdf", "ASHA MEHTA", "2026-01-01"), passport("2026-12-01")]) == []


def test_hotel_dates_should_line_up_with_flights():
    assert kinds([ticket(), passport(), hotel("2026-11-02", "2026-11-05")]) == [
        ("hotel_dates", "warning")]
    assert kinds([ticket(), hotel("2026-10-21", "2026-10-23")]) == []  # night flight
    assert kinds([hotel("2026-11-02", "2026-11-05")]) == []  # no flights to compare


def test_two_tickets_on_the_same_day():
    assert kinds([ticket("a.pdf"), ticket("b.pdf")]) == [("same_day_flights", "warning")]
    # Connecting segments on one ticket are normal.
    assert kinds([ticket("a.pdf", "ASHA MEHTA", "2026-10-20", "2026-10-20")]) == []


def test_unreadable_dates_are_ignored():
    assert kinds([ticket("a.pdf", "ASHA MEHTA", "20 Oct"), passport("soon")]) == []
