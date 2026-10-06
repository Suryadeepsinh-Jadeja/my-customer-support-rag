"""End-to-end smoke test against a RUNNING API with the real LLM.

    python scripts/smoke_test.py [--api http://127.0.0.1:8000] [--passenger "3369 995465" --reference 904C29]

Drives the main customer journeys over HTTP (frontend -> API -> LangGraph ->
agents -> RAG/tools -> LLM) and checks the observable outcome of each one.
Sensitive actions are confirmed, so this MODIFIES the travel database; restore
`customer_support_chat/data/travel2.sqlite` from a copy afterwards if needed.
"""

import argparse
import sys
import time

import requests


class Client:
    def __init__(self, api: str, token: str | None = None):
        self.api = api.rstrip("/")
        self.token = token

    def post(self, path: str, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        response = requests.post(f"{self.api}{path}", json=payload, headers=headers, timeout=180)
        body = response.json()
        if response.status_code >= 400:
            raise RuntimeError(f"{path} -> {response.status_code}: {body}")
        return body


def converse(client: Client, opening: str, follow_ups: list[str], confirm: bool = True, max_turns: int = 6):
    """Send `opening`, answer questions with `follow_ups`, confirm pending actions."""
    transcript, confirmations = [], 0
    body = client.post("/chat", {"message": opening})
    transcript.append(("user", opening))
    conversation_id = body["conversation_id"]
    sources = list(body["sources"])
    agents = {body["agent"]}
    for _ in range(max_turns):
        transcript.append((body["agent"], body["response"]))
        if body["status"] == "confirmation_required":
            actions = "; ".join(a["title"] for a in body["pending_actions"])
            transcript.append(("pending", actions))
            if not confirm:
                break
            confirmations += 1
            body = client.post("/chat/confirm", {"conversation_id": conversation_id, "approved": True})
        elif follow_ups:
            message = follow_ups.pop(0)
            transcript.append(("user", message))
            body = client.post("/chat", {"conversation_id": conversation_id, "message": message})
        else:
            break
        sources += body["sources"]
        agents.add(body["agent"])
    else:
        transcript.append((body["agent"], body["response"]))
    return {"transcript": transcript, "sources": sources, "agents": agents,
            "confirmations": confirmations, "last": body}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--passenger", default="3369 995465")
    parser.add_argument("--reference", default="904C29")
    parser.add_argument("--only", nargs="*", help="Run only scenarios whose name contains these words")
    parser.add_argument("--pause", type=float, default=0, help="Seconds to wait between scenarios (free-tier rate limits)")
    args = parser.parse_args()

    guest = Client(args.api)
    token = guest.post("/auth/login", {"passenger_id": args.passenger, "booking_reference": args.reference})["session_token"]
    customer = Client(args.api, token)

    def docs(result):
        return {s["document_name"] for s in result["sources"]}

    scenarios = [
        ("1 knowledge: baggage policy", guest, "What is the baggage policy?", [],
         lambda r: "Baggage Policy" in docs(r)),
        ("1b knowledge: unknown policy is not invented", guest,
         "Do you allow emotional support peacocks in the cabin?", [],
         lambda r: not r["sources"] or "verif" in r["last"]["response"].lower() or "couldn't" in r["last"]["response"].lower()),
        ("2 flight info", customer, "Show me my flight information.", [],
         lambda r: "DL0042" in r["last"]["response"] or "HAM" in r["last"]["response"] or "Hamburg" in r["last"]["response"]),
        ("7 hybrid: cancel + refund", customer, "Can I cancel my flight, and what refund will I get?", [],
         lambda r: any("Cancellation" in d for d in docs(r)) and r["confirmations"] == 0),
        ("3 flight change w/ confirmation", customer,
         "I want to change my flight to an earlier flight on the same route, on 13 October.",
         ["Yes, the earliest one that day is fine.", "Yes, please go ahead with the change."],
         lambda r: r["confirmations"] >= 1 and "Flight Support" in r["agents"]),
        ("4 hotel booking", customer, "I want to book a hotel in Basel for 2 nights from 13 October.",
         ["The Hilton Basel please.", "Yes, book it."],
         lambda r: r["confirmations"] >= 1 and "Hotel Support" in r["agents"]),
        ("5 car rental", customer, "I need a rental car in Basel from 13 to 15 October.",
         ["Europcar is fine.", "Yes, book it."],
         lambda r: r["confirmations"] >= 1 and "Car Rental Support" in r["agents"]),
        ("6 excursion", customer, "Recommend an excursion in Basel for my trip.",
         ["I like art and museums. Please book the Kunstmuseum.", "Yes, book it."],
         lambda r: "Trips & Excursions" in r["agents"]),
    ]

    failures = 0
    for name, client, opening, follow_ups, check in scenarios:
        if args.only and not any(word in name for word in args.only):
            continue
        if args.pause and name != scenarios[0][0]:
            time.sleep(args.pause)
        start = time.perf_counter()
        try:
            result = converse(client, opening, list(follow_ups))
            ok = check(result)
        except Exception as exc:  # report and continue with the other scenarios
            result, ok = {"transcript": [("error", str(exc))], "sources": []}, False
        failures += not ok
        print(f"\n{'PASS' if ok else 'FAIL'}  {name}  ({time.perf_counter() - start:.1f}s)")
        for who, text in result["transcript"]:
            print(f"   {who:>18}: {text[:300].replace(chr(10), ' ')}")
        if result.get("sources"):
            print("   sources: " + ", ".join(sorted({s['document_name'] for s in result['sources']})))

    print(f"\n{'ALL PASSED' if not failures else f'{failures} FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
