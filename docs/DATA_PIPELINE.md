# Data Pipeline Design — JIRA → pgvector

## Overview

The data pipeline is responsible for keeping the pgvector knowledge base in sync with JIRA. It handles both real-time delta updates and periodic full syncs.

---

## Embedding Provider

The pipeline uses **Vertex AI text-embedding-004** in all environments — local dev and production identical.

- **Model**: `text-embedding-004`
- **Dimensions**: 768 (always)
- **Auth**: `GOOGLE_APPLICATION_CREDENTIALS` (service account JSON key locally, attached service account in production)
- **Batch size**: 5 texts per API call

The pgvector column is always `vector(768)` — local and production schemas are identical. Data generated locally can be migrated to production as-is.

## Pipeline Flow

```
JIRA
  │
  ├── Webhook (real-time) ──────────────► Cloud Pub/Sub (jira-events topic)
  │                                               │
  └── REST API (full sync, scheduled) ────────────┘
                                                  │
                                                  ▼
                                        Cloud Run Job
                                        (embedding-worker)
                                                  │
                                    ┌─────────────┼─────────────┐
                                    ▼             ▼             ▼
                              Fetch content  Generate        Store raw
                              from JIRA      embedding       snapshot
                              REST API       (Vertex AI      (GCS)
                                             gecko-004)
                                                  │
                                                  ▼
                                        Upsert into pgvector
                                        (Cloud SQL)
```

---

## Sync Modes

### Delta Sync (Event-Driven)

Triggered by JIRA webhook on:
- Issue created
- Issue updated (any field)
- Comment added
- Status changed

JIRA webhook payload → Pub/Sub message → Embedding worker processes single ticket.

Latency target: < 5 minutes from JIRA update to searchable in pgvector.

### Full Sync (Scheduled)

Daily at 02:00 UTC via Cloud Scheduler.

Paginates all tickets and incidents using JQL:
```
project in (B1_PROJECT, B2_PROJECT) ORDER BY updated ASC
```

Processes all tickets, upserts embeddings. Handles drift caused by:
- Missed webhooks
- Schema changes requiring re-embedding
- New BU onboarding

---

## Text Preparation for Embedding

### Tickets

```python
def prepare_ticket_text(ticket: dict) -> str:
    parts = []
    
    # Summary is most important — repeated for weight
    parts.append(f"Issue: {ticket['summary']}")
    parts.append(f"Type: {ticket['issue_type']} | Status: {ticket['status']}")
    
    if ticket.get('description'):
        # Truncate long descriptions
        desc = ticket['description'][:1500]
        parts.append(f"Description: {desc}")
    
    if ticket.get('resolution'):
        parts.append(f"Resolution: {ticket['resolution']}")
    
    # Last 3 comments (most recent context)
    comments = ticket.get('comments', [])[-3:]
    for comment in comments:
        parts.append(f"Comment: {comment['body'][:300]}")
    
    return "\n\n".join(parts)[:3000]  # Hard limit for embedding model
```

### Incidents

```python
def prepare_incident_text(incident: dict) -> str:
    parts = []
    
    parts.append(f"Incident: {incident['title']}")
    parts.append(f"Severity: {incident['severity']}")
    
    if incident.get('description'):
        parts.append(f"Description: {incident['description'][:1000]}")
    
    if incident.get('root_cause'):
        # RCA root cause is high-signal — weight it by including fully
        parts.append(f"Root Cause: {incident['root_cause']}")
    
    if incident.get('long_term_fix'):
        parts.append(f"Long-term Fix: {incident['long_term_fix']}")
    
    return "\n\n".join(parts)[:3000]
```

---

## Business Unit Mapping

JIRA projects must be mapped to BU codes in configuration:

```python
BU_PROJECT_MAP = {
    "B1": ["PROJECT_A", "PROJECT_B"],  # JIRA project keys for BU1
    "B2": ["PROJECT_C", "PROJECT_D"],  # JIRA project keys for BU2
}
```

Or, if JIRA has a custom field for BU, use:
```python
BU_FIELD_ID = "customfield_10100"  # JIRA custom field ID for BU
```

The pipeline tags every ticket/incident with the correct `business_unit` code at ingest time.

---

## Incident Detection in JIRA

Incidents are distinguished from regular tickets by:
1. Issue type: `Incident` or `Production Issue`
2. Labels: `incident`, `production-incident`, `outage`
3. Custom field: `is_incident = true`

Configure via environment variable:
```
INCIDENT_ISSUE_TYPES=Incident,Production Issue
INCIDENT_LABELS=incident,production-incident,outage
```

RCA content is typically in:
- JIRA issue description (structured with headings like "Root Cause:", "Long-term Fix:")
- Or as a linked Confluence page (future enhancement)

---

## Upsert Strategy

All upserts are idempotent using `ON CONFLICT (jira_id) DO UPDATE`:

```sql
INSERT INTO tickets (
    jira_id, business_unit, ticket_type, summary, description,
    status, resolution, discussion, created_at, updated_at,
    embedding, raw_json
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::vector, $12)
ON CONFLICT (jira_id) DO UPDATE SET
    summary = EXCLUDED.summary,
    description = EXCLUDED.description,
    status = EXCLUDED.status,
    resolution = EXCLUDED.resolution,
    discussion = EXCLUDED.discussion,
    updated_at = EXCLUDED.updated_at,
    embedding = EXCLUDED.embedding,
    raw_json = EXCLUDED.raw_json;
```

This means re-running the full sync is safe and will update changed records.

---

## Error Handling & Dead Letter Queue

Failed messages go to `jira-events-dlq` topic after 3 retry attempts.

A Cloud Function monitors the DLQ and:
1. Logs the failed message with structured context
2. Sends an alert if DLQ depth > 10 messages
3. Allows manual replay via a simple admin endpoint

---

## Performance Targets

| Metric | Target |
|---|---|
| Delta sync latency (webhook → searchable) | < 5 minutes |
| Full sync throughput | 1,000 tickets/minute |
| Embedding generation (Vertex AI) | < 500ms per batch of 5 |
| pgvector upsert | < 50ms per ticket |
| Daily full sync completion | < 30 minutes for 50k tickets |

---

## Monitoring

Pipeline metrics to track:
- `embedding_worker.tickets_processed` (counter, labelled by BU)
- `embedding_worker.embedding_latency_ms` (histogram)
- `embedding_worker.upsert_errors` (counter)
- `pubsub.subscription.oldest_unacked_message_age` — alert if > 10 min
- Full sync job duration and exit code via Cloud Run Jobs metrics
