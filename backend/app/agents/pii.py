"""Masking identifier numbers in assistant answers.

The model may see full values (so it can answer "what is my passport number?"), but an
answer only shows them when the user's own message asked for that kind of number. Anywhere
else they appear as ****1234.
"""

import re

from app.core.logging import mask

# Extracted fields treated as identifiers, and the word that names them in a question.
IDENTIFIERS = {
    "passport_number": "passport",
    "visa_number": "visa",
    "document_number": "document",
    "policy_number": "policy",
    "ticket_number": "ticket",
}


def asked_for(field: str, message: str) -> bool:
    text = message.lower()
    return IDENTIFIERS[field] in text and bool(re.search(r"\bnumbers?\b|\bno\b|#", text))


def mask_identifiers(answer: str, user_message: str,
                     values: list[tuple[str, str]]) -> str:
    """values: (field, value) pairs from the user's documents."""
    for field, value in values:
        compact = re.sub(r"[\s-]", "", value)
        if len(compact) < 5 or asked_for(field, user_message):
            continue
        # Match the value even if the model spaced or hyphenated it.
        pattern = r"[\s-]?".join(re.escape(c) for c in compact)
        answer = re.sub(pattern, mask(compact) or "", answer, flags=re.IGNORECASE)
    return answer
