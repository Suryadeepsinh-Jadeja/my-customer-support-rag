# Knowledge base

Policy and FAQ documents used for retrieval-augmented generation (RAG). This
file is ignored by the ingestion pipeline.

## Format

One Markdown file per document. The first line is the document title, followed
by optional `key: value` front matter lines; every `##` heading starts a section:

```markdown
# Baggage Policy
category: flights
last_updated: 2026-09-01

## Hand baggage
...
```

The title, section heading and file path are stored with every chunk and shown
to customers as the answer's sources.

## Contents

| Folder | Documents |
|---|---|
| `airline/` | `swiss_faq.md`: the SWISS FAQ from the LangGraph customer-support tutorial dataset (the trailing third-party SEO section, which contained an unofficial phone number, was deliberately excluded) |
| `flights/` | cancellation & refunds, flight changes, baggage, check-in & boarding |
| `travel/` | travel documents and special assistance |
| `car_rentals/`, `hotels/`, `excursions/` | partner-service policies |

Everything except `swiss_faq.md` is **demo content written for this project**
and is not official airline policy.

## Updating

After adding or editing documents, rebuild only the knowledge collection:

```bash
python scripts/ingest.py --only knowledge_base
```
