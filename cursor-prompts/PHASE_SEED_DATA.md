# Cursor Build Prompts — Demo Seed Data

This prompt creates realistic seed data so the application has meaningful content to search, display, and demonstrate from day one.

Run this after Prompt 4.6 (Local Dev Setup). It generates two scripts:
- `scripts/seed_users.py` — engineer and admin accounts
- `scripts/seed_demo_data.py` — tickets, incidents, and RCAs with real content

---

## PROMPT SD.1 — Demo Seed Data Script

```
Create scripts/seed_demo_data.py — a comprehensive seed script that populates
the database with realistic support tickets and incidents for two business units
(B1 = Reservations Platform, B2 = Payments Platform).

The data must be rich enough that the chatbot can demonstrate real RAG behaviour
when engineers ask questions like:
- "Have we seen database timeout issues before?"
- "What was the fix for the payment gateway failures last quarter?"
- "Are there any incidents related to booking failures?"
- "What is the status of B1-1008?"

═══════════════════════════════════════════════════════════════
SECTION 1: SETUP
═══════════════════════════════════════════════════════════════

Requirements:
- asyncpg for DB writes
- vertexai SDK to generate REAL embeddings via text-embedding-004
  (same model used in production — vectors will actually work for semantic search)
- python-dotenv to load DATABASE_URL and Google credentials from .env.local
- structlog for progress logging
- All inserts use ON CONFLICT (jira_id) DO UPDATE — idempotent

Initialise Vertex AI at startup:
  vertexai.init(project=GCP_PROJECT_ID, location=VERTEX_AI_LOCATION)
  embedding_model = TextEmbeddingModel.from_pretrained("text-embedding-004")

Helper function embed(text: str) -> list[float]:
  Calls embedding_model.get_embeddings([text])[0].values
  Adds 1 second sleep between calls to respect Vertex AI rate limits

═══════════════════════════════════════════════════════════════
SECTION 2: BUSINESS UNITS
═══════════════════════════════════════════════════════════════

Insert two business units:
  B1 — Reservations Platform
  B2 — Payments Platform

═══════════════════════════════════════════════════════════════
SECTION 3: B1 TICKETS (Reservations Platform) — 15 tickets
═══════════════════════════════════════════════════════════════

B1-1001 | BUG | status=Resolved
summary: "Search results returning stale availability data after cache flush"
description: "After the scheduled cache flush at 02:00 UTC, the availability
search API continued serving stale data for up to 45 minutes. Customers were
seeing rooms marked as available that had already been booked. The issue affected
approximately 340 search queries before being detected."
resolution: "Root cause was a race condition in the Redis cache warm-up logic.
The cache was being marked as ready before all availability keys had been
populated. Fix: added a readiness gate that checks key count before marking
cache warm-up complete. Deployed in v2.4.1. Monitoring alert added for
cache-hit-rate dropping below 80%."
discussion: [
  { author: "sarah.chen", body: "Confirmed — Redis KEYS availability:* count was 0 at 02:03 UTC but cache was marked ready at 02:01 UTC." },
  { author: "james.okafor", body: "Fix deployed to prod at 09:45 UTC. Cache warm-up now validates key count threshold before marking ready." }
]

B1-1002 | BUG | status=Resolved
summary: "Booking confirmation emails delayed by up to 2 hours during peak load"
description: "Engineers reported that booking confirmation emails were being
delayed significantly during peak hours (18:00-22:00 UTC). The email queue
depth was growing faster than the worker pool could process. Customers were
calling support asking if their bookings were confirmed."
resolution: "The email worker pool was hardcoded to 5 workers. Increased to
20 workers and implemented auto-scaling based on queue depth. Also added
SQS dead letter queue for failed email jobs. Queue depth alert set at 500 messages."
discussion: [
  { author: "mike.torres", body: "Queue depth hit 4,200 at 19:30 UTC. Workers were at max CPU." },
  { author: "priya.sharma", body: "Scaled workers to 20. Queue cleared within 15 minutes. Deploying auto-scale config." }
]

B1-1003 | BUG | status=Resolved
summary: "Reservation modification API returning 500 errors for bookings older than 90 days"
description: "Customers attempting to modify reservations made more than 90
days ago were receiving 500 Internal Server Error responses. The issue was
introduced in the v2.3.0 release which changed the date range validation logic."
resolution: "A date arithmetic bug in the modification eligibility check was
computing negative values for old bookings and failing the range validation.
Fixed by using absolute value in the date comparison. Fix released in v2.3.1."

B1-1004 | BUG | status=In Progress
summary: "Room type images not loading on booking confirmation page in Safari"
description: "Customers using Safari (iOS and macOS) reported that room type
images on the booking confirmation page fail to load. The images show broken
icon placeholders. Chrome and Firefox are not affected. Issue appears related
to CORS headers on the image CDN."
resolution: null
discussion: [
  { author: "alex.wu", body: "Reproduced on Safari 17.2. The CDN is returning CORS headers without the required Origin header echo. Filed with CDN vendor." }
]

B1-1005 | TASK | status=Resolved
summary: "Migrate reservation search index from Elasticsearch 7 to Elasticsearch 8"
description: "Elasticsearch 7 reaches end of life in August 2024. Need to
upgrade the reservation search cluster to ES8. This requires updating the
client library, migrating index mappings, and reindexing approximately
12 million reservation records."
resolution: "Migration completed over a weekend maintenance window. Used
ES8 compatible client, updated index mappings for new field types. Reindex
took 4.5 hours. Zero downtime achieved by using dual-write during transition."

B1-1006 | BUG | status=Resolved
summary: "Duplicate booking records created when payment gateway timeout occurs"
description: "When the payment gateway returns a timeout (504), the reservation
service was retrying the entire booking creation including the DB insert. This
created duplicate booking records with the same guest and dates but different
confirmation numbers. Discovered when a guest received two confirmation emails."
resolution: "Implemented idempotency keys on booking creation. Payment requests
now include a UUID idempotency key. Retries reuse the same key so the payment
gateway deduplicates. DB insert uses ON CONFLICT DO NOTHING. Fixed in v2.5.0."
discussion: [
  { author: "james.okafor", body: "Found 23 duplicate booking pairs in production. Guest services team manually cancelled the duplicates and issued apologies." },
  { author: "sarah.chen", body: "Idempotency implementation reviewed and approved. Deploying tonight." }
]

B1-1007 | BUG | status=Resolved
summary: "Group booking API fails when party size exceeds 10 guests"
description: "The group booking endpoint returns HTTP 422 Unprocessable Entity
for any booking request with more than 10 guests. Investigation revealed a
hardcoded validation limit in the group booking service that was never updated
after the product team increased the maximum group size to 20."
resolution: "Updated MAX_GROUP_SIZE constant from 10 to 20 in booking-service
config. Added unit test for boundary values. Released in v2.4.2."

B1-1008 | BUG | status=Open
summary: "Search API response time degrading under high load — p95 exceeding 3 seconds"
description: "Since the v2.5.0 deployment, the reservation search API p95
latency has been trending upward. During peak hours it now exceeds 3 seconds
compared to the 800ms baseline. Database query plans show a sequential scan
on the availability_cache table that previously used an index. The index may
have been dropped during the migration."
resolution: null
discussion: [
  { author: "priya.sharma", body: "EXPLAIN ANALYZE shows seq scan on availability_cache. The idx_availability_date_property index is missing from prod." },
  { author: "mike.torres", body: "Confirmed index was accidentally dropped in migration script step 7. Working on hotfix." }
]

B1-1009 | STORY | status=Resolved
summary: "Implement real-time room availability websocket updates"
description: "Currently availability data is polled every 30 seconds.
Product requirement to implement WebSocket-based push updates so availability
changes reflect in the UI within 2 seconds. Affects the search results page
and the room selection step of booking flow."
resolution: "Implemented WebSocket server using FastAPI WebSockets. Room
availability changes publish to Redis pub/sub channel. WebSocket handler
subscribes and pushes deltas to connected clients. Average latency from
availability change to UI update: 340ms. Deployed in v2.6.0."

B1-1010 | BUG | status=Resolved
summary: "Cancellation refund amounts incorrect for multi-night bookings with rate changes"
description: "When a multi-night booking spans a rate change date and is
cancelled, the refund calculation was using only the first night's rate for all
nights. This resulted in incorrect refund amounts — guests either over- or
under-refunded depending on rate direction."
resolution: "Fixed the refund calculation to look up the per-night rate for
each night individually. Added integration test covering rate-change boundary
scenarios. Finance team confirmed 8 affected bookings were manually corrected."

B1-1011 | BUG | status=Resolved
summary: "Loyalty points not awarded for bookings made through corporate API"
description: "Bookings created via the corporate B2B API were not triggering
the loyalty points award event. The loyalty service only listened for events
from the consumer booking flow. Corporate API bookings used a different event
type that was not mapped to the loyalty award handler."
resolution: "Added CORPORATE_BOOKING_CREATED to the loyalty service event
handler mapping. Backfilled loyalty points for 156 affected bookings via
admin script. Released in v2.4.3."

B1-1012 | BUG | status=Resolved
summary: "Date picker widget allowing selection of past dates on mobile browsers"
description: "The check-in date picker on mobile browsers (iOS Safari, Android Chrome)
was not enforcing the min-date constraint correctly. Users could select past dates
and proceed to payment before receiving a validation error server-side. This
caused a poor user experience with no clear error message on mobile."
resolution: "Fixed by explicitly setting min attribute on the native date
input for mobile and adding client-side validation that mirrors the server-side
constraint. Tested on iOS 17 and Android 14."

B1-1013 | TASK | status=Resolved
summary: "Add database connection pooling to reduce Cloud SQL connection overhead"
description: "Each reservation service instance was opening direct connections
to Cloud SQL, exhausting the max_connections limit during peak load (hitting
512 connections with only 12 service instances). Need to implement PgBouncer
connection pooling in transaction mode."
resolution: "Deployed PgBouncer as a sidecar container. Pool size set to 25
per instance. Max Cloud SQL connections stable at 150 even during peak load
of 40 service instances. p99 query latency improved by 35% due to reduced
connection overhead."

B1-1014 | BUG | status=Resolved  
summary: "Search filters not persisting when navigating back from property detail page"
description: "When a user applies search filters (dates, guest count, amenities),
views a property, and navigates back, all filters are reset to defaults.
This forces users to re-enter their search criteria, leading to high bounce rates
on the search results page."
resolution: "Implemented search state persistence using URL query parameters.
Filters are now encoded in the URL and restored on navigation. Browser back
button correctly restores the filtered search state. Analytics showed 23%
reduction in search abandonment after fix."

B1-1015 | BUG | status=Resolved
summary: "Overbooking occurring during concurrent booking requests for last available room"
description: "When multiple users simultaneously attempt to book the last
available room, the availability check and booking creation were not atomic.
This resulted in multiple bookings for the same room on the same dates —
an overbooking situation requiring manual intervention."
resolution: "Implemented optimistic locking on availability records using
a version counter. Booking creation now uses SELECT FOR UPDATE to lock the
availability row. Concurrent requests for the same room are serialized.
Load tested with 100 concurrent requests for the same room — zero overbookings."

═══════════════════════════════════════════════════════════════
SECTION 4: B2 TICKETS (Payments Platform) — 15 tickets
═══════════════════════════════════════════════════════════════

B2-2001 | BUG | status=Resolved
summary: "Payment gateway returning intermittent 503 errors during Stripe webhook processing"
description: "Stripe webhook events for payment_intent.succeeded were triggering
503 Service Unavailable responses from the payment processing service. The webhooks
were being retried by Stripe, causing duplicate processing attempts. Some bookings
were marked as paid twice, creating accounting discrepancies."
resolution: "The payment service was running out of database connections during
webhook bursts. Implemented webhook deduplication using Redis (key: webhook:{event_id},
TTL 24h). Added idempotency check before processing. Connection pool increased.
Stripe dashboard shows 100% webhook success rate since fix."
discussion: [
  { author: "david.kim", body: "Found 47 duplicate payment events in the audit log from the past week." },
  { author: "lisa.patel", body: "Redis deduplication deployed. Monitoring webhook success rate over next 24h." }
]

B2-2002 | BUG | status=Resolved
summary: "3D Secure authentication failing for certain European card issuers"
description: "Customers with cards from specific European banks (ING, Rabobank,
ABN AMRO) were failing 3DS2 authentication. The authentication page was loading
but submitting without the challenge completing. Investigation showed the 3DS2
iframe was being blocked by our Content Security Policy."
resolution: "Added the 3DS2 authentication domains (*.stripe.com, *.acs-server.com)
to the CSP frame-src directive. Also added *.stripecdn.com for asset loading.
Tested successfully with test cards from affected issuers. European conversion
rate improved by 4.2% in the week after fix."

B2-2003 | BUG | status=Resolved
summary: "Currency conversion rates not refreshing — showing 6-hour-old rates"
description: "The payment service was caching currency conversion rates with
a TTL that was set to 21600 seconds (6 hours) instead of the intended 600
seconds (10 minutes). Customers were seeing exchange rates that could be
significantly out of date during volatile currency periods."
resolution: "Fixed TTL configuration — CURRENCY_CACHE_TTL env var was being
read as a string and not converted to int, so the Redis SET command was using
the default TTL of 21600. Fixed with explicit int() cast. Rates now refresh
every 10 minutes as intended."

B2-2004 | INCIDENT | status=Resolved
summary: "Payment processing outage — all card payments failing for 23 minutes"
description: "At 14:22 UTC on March 15, all card payment attempts were failing
with a generic error. Investigation revealed that the payment service TLS
certificate for the Stripe API connection had expired. The certificate renewal
job had been silently failing for 3 days without alerting."
resolution: "Certificate renewed manually. TLS certificate expiry monitoring
added to Cloud Monitoring with 30-day and 7-day advance alerts. Certificate
renewal automation repaired — was failing due to incorrect GCS bucket permissions.
Root cause: monitoring gap in certificate lifecycle management."
discussion: [
  { author: "david.kim", body: "Incident started 14:22 UTC. First customer report at 14:24 UTC. Service restored 14:45 UTC." },
  { author: "ops.team", body: "Post-incident: 1,847 failed payment attempts. All customers received retry emails." }
]

B2-2005 | BUG | status=Resolved
summary: "Refund API timeout when processing refunds for orders older than 180 days"
description: "The refund endpoint was timing out (30 second limit) for orders
created more than 180 days ago. The query to fetch the original payment intent
was performing a full table scan due to missing index on created_at column for
archived orders."
resolution: "Added composite index on (created_at, status) for the payments
table. Refund query now uses index seek instead of table scan. P99 refund
API latency reduced from 28s to 340ms. Backfill index creation ran without
table lock using CREATE INDEX CONCURRENTLY."

B2-2006 | BUG | status=Resolved
summary: "Apple Pay button not displaying for customers in unsupported regions"
description: "Instead of gracefully hiding the Apple Pay button for customers
in regions where Apple Pay is not supported, the button was displaying but
failing with a cryptic JavaScript error when clicked. This was confusing
customers who expected it to work."
resolution: "Added proper Apple Pay availability check using PaymentRequest.canMakePayment()
before rendering the button. Button now only shown when both Apple Pay and
the relevant card networks are available in the customer's region."

B2-2007 | BUG | status=Open
summary: "Split payment feature failing when total amount exceeds 10,000 USD"
description: "The split payment feature (paying with two cards) is failing
for total booking amounts above $10,000. The payment service is returning
HTTP 400 Bad Request. Initial investigation suggests the amount validation
is using integer arithmetic that overflows for large amounts when converted
to cents (multiply by 100)."
resolution: null
discussion: [
  { author: "lisa.patel", body: "Confirmed: amount * 100 overflows int32 for values > $21,474. Need to use int64 or Decimal throughout payment amount handling." }
]

B2-2008 | BUG | status=Resolved
summary: "Payment reconciliation report missing transactions from timezone boundary"
description: "The daily payment reconciliation report was missing transactions
that occurred between 23:00-24:00 UTC. The report query was using local server
time instead of UTC for the day boundary calculation. On servers in UTC+1,
this caused the last hour of each day to be included in the next day's report."
resolution: "Standardized all report date range queries to use UTC explicitly:
WHERE created_at >= date_trunc('day', NOW() AT TIME ZONE 'UTC').
Added unit tests for UTC boundary conditions."

B2-2009 | STORY | status=Resolved
summary: "Implement PayPal payment method alongside existing Stripe integration"
description: "Product requirement to add PayPal as an alternative payment method.
Requires integrating PayPal Orders API v2, handling PayPal webhooks, updating
the checkout UI to show PayPal button, and mapping PayPal transaction states
to internal payment states."
resolution: "PayPal integration completed and deployed in v3.1.0. Using
PayPal Orders API v2 with server-side order creation. Webhook processing
handles PAYMENT.CAPTURE.COMPLETED and PAYMENT.CAPTURE.DENIED events.
A/B test shows 8% higher conversion for customers who see the PayPal option."

B2-2010 | BUG | status=Resolved
summary: "Fraud detection false positives blocking legitimate corporate card payments"
description: "The fraud detection model was flagging corporate Amex cards as
high-risk, causing approximately 15% of corporate bookings to be declined.
The model had been trained primarily on consumer card data and was incorrectly
scoring corporate card velocity patterns as fraudulent."
resolution: "Added corporate_card feature flag to fraud detection pipeline.
Corporate Amex BIN ranges (372xxx, 378xxx) are now routed through a separate
model tuned for corporate card patterns. False positive rate for corporate
cards reduced from 15% to 0.8%."

B2-2011 | BUG | status=Resolved
summary: "Chargeback webhook processing failing silently — disputed payments not updating"
description: "Stripe chargeback webhooks (charge.dispute.created) were arriving
at the webhook endpoint and returning 200 OK, but the payment status was not
being updated to DISPUTED in the database. The dispute handler was catching
the database exception and logging it but not re-raising, causing silent failures."
resolution: "Fixed the exception handler in dispute processing to re-raise
after logging. Added monitoring alert on chargeback processing errors.
Backfilled 34 disputed payments that had been silently ignored over 2 months."

B2-2012 | TASK | status=Resolved
summary: "PCI DSS compliance audit — remediate findings from quarterly scan"
description: "Q3 PCI DSS vulnerability scan identified three findings:
1. TLS 1.0 and 1.1 still enabled on payment API endpoints
2. Default error messages exposing internal stack traces
3. Admin payment portal accessible from internet without MFA"
resolution: "All three findings remediated:
1. Disabled TLS 1.0/1.1 in nginx config — TLS 1.2 minimum enforced
2. Added global exception handler returning generic error messages
3. Admin portal moved to VPN-only access with mandatory 2FA
Passed follow-up scan with zero findings."

B2-2013 | BUG | status=Resolved
summary: "Payment amount displayed with wrong decimal places for JPY transactions"
description: "Japanese Yen (JPY) is a zero-decimal currency — amounts should
not be divided by 100 when displaying. The payment display code was dividing
all currencies by 100, showing ¥15000 as ¥150.00. This caused confusion for
Japanese customers and accounting discrepancies."
resolution: "Added ZERO_DECIMAL_CURRENCIES constant containing ISO 4217 codes
for currencies with no minor units (JPY, KRW, VND, etc.). Display formatter
now checks this list before applying decimal division."

B2-2014 | BUG | status=Resolved
summary: "Saved payment methods disappearing after password reset"
description: "When a customer resets their password, their saved payment
methods (Stripe customer payment methods) were being deleted. The password
reset flow was calling the user cleanup function which incorrectly included
a step to remove all associated Stripe customer data."
resolution: "Removed the Stripe customer data cleanup from password reset flow.
That cleanup should only run on account deletion. Added integration test
verifying saved payment methods persist through password reset."

B2-2015 | BUG | status=Resolved
summary: "Invoice PDF generation failing for bookings with special characters in guest name"
description: "Invoice PDF generation was throwing an exception when the guest
name contained special characters such as accented letters (é, ü, ñ) or
certain Unicode characters. The PDF library was using Latin-1 encoding by
default, which does not support extended Unicode characters."
resolution: "Updated PDF generation to use UTF-8 encoding explicitly.
Switched to ReportLab's TTFont with a Unicode-compatible font (DejaVu).
Tested with names in Arabic, Chinese, Japanese, and various European scripts."

═══════════════════════════════════════════════════════════════
SECTION 5: INCIDENTS — 5 incidents with full RCA
═══════════════════════════════════════════════════════════════

INC-001 | severity=P1 | business_unit=B1 | resolved
title: "Reservations Platform — Complete search outage for 47 minutes"
description: "At 09:15 UTC on January 8, the reservation search service
became completely unavailable. All search API calls were returning HTTP 503.
The outage lasted 47 minutes and affected 100% of search traffic."
root_cause: "An unvalidated configuration change was deployed to the search
service that set the Elasticsearch cluster URL to an incorrect value. The
health check endpoint was not testing the search dependency, only the
service itself. The misconfiguration passed all smoke tests."
long_term_fix: "1. Added Elasticsearch connectivity to health check endpoint
2. Implemented configuration validation at startup — service fails to start
if critical dependencies are unreachable
3. Added pre-deployment configuration diff review step to deployment pipeline
4. Elasticsearch cluster URL moved to Secret Manager — requires PR review to change"
related_tickets: ["B1-1008", "B1-1013"]

INC-002 | severity=P1 | business_unit=B2 | resolved
title: "Payment Processing — All card payments failing for 23 minutes"
description: "At 14:22 UTC on March 15, all card payment attempts were failing.
Customers received generic payment failure messages. The engineering team was
alerted by a spike in payment failure rate (0.3% → 100% in 2 minutes).
Total business impact: 1,847 failed payment attempts, estimated $340,000 in
delayed revenue."
root_cause: "The TLS certificate used by the payment service to authenticate
with the Stripe API expired at 14:22 UTC. The automated certificate renewal
Cloud Run job had been failing silently for 3 days — the job was misconfigured
to write the renewed certificate to a GCS bucket path that the service account
no longer had write access to (permissions were tightened in a security audit)."
long_term_fix: "1. Certificate expiry monitoring: Cloud Monitoring alerts at
30 days, 14 days, and 7 days before expiry
2. Certificate renewal job permissions corrected and tested
3. Certificate renewal now also sends Slack notification on success/failure
4. Runbook created for manual certificate renewal as fallback
5. Monthly rotation scheduled to prevent long expiry gaps"
related_tickets: ["B2-2004", "B2-2012"]

INC-003 | severity=P2 | business_unit=B1 | resolved
title: "Reservations Platform — Overbooking event affecting 12 properties"
description: "On February 3, the reservations team identified 31 overbooking
instances across 12 properties. Guests with confirmed bookings arrived to find
their rooms already occupied. The issue had been present for approximately
6 hours before detection. Engineering was engaged at 15:30 UTC."
root_cause: "A race condition in the availability locking mechanism. During
a traffic spike (3x normal load due to a flash sale), multiple concurrent
booking requests for the same room were passing the availability check
simultaneously before any of them had committed the booking to the database.
The availability table had no row-level locking."
long_term_fix: "1. Implemented SELECT FOR UPDATE on availability rows during
booking creation — serializes concurrent bookings for the same room
2. Added optimistic locking with version counter as secondary protection
3. Database-level unique constraint on (room_id, check_in_date) prevents
physical duplicates even if application logic fails
4. Load testing suite updated to include concurrent booking scenarios
5. Real-time overbooking detection alert added"
related_tickets: ["B1-1015", "B1-1006"]

INC-004 | severity=P2 | business_unit=B2 | resolved
title: "Payments Platform — Currency conversion showing wrong rates for 4 hours"
description: "On April 12 between 08:00 and 12:00 UTC, customers making
international payments were being quoted exchange rates that were up to 8%
different from the actual market rate. The issue affected approximately
2,400 transactions. Finance identified the discrepancy during morning reconciliation."
root_cause: "The currency rate cache TTL was configured as 21600 seconds
(6 hours) instead of the intended 600 seconds (10 minutes). This was caused
by a type conversion bug introduced in a refactor — the TTL was being read
from an environment variable as a string and passed directly to Redis SET,
which used the value as a float (21600.0 → treated as expiry Unix timestamp,
setting expiry to Unix timestamp 21600 which is in 1970 — effectively never expiring).
The rate cache was seeded at service startup and never refreshed."
long_term_fix: "1. Fixed type conversion: int(os.getenv('CURRENCY_CACHE_TTL', '600'))
2. Added startup validation that logs and alerts if cache TTL exceeds 1800 seconds
3. Currency rate age is now included in the API response headers
4. Added integration test verifying TTL is set correctly
5. Finance reconciliation script now flags rate-age > 15 minutes"
related_tickets: ["B2-2003", "B2-2008"]

INC-005 | severity=P3 | business_unit=B1 | resolved
title: "Reservations Platform — Email delivery failure for 340 confirmation emails"
description: "On May 7, 340 booking confirmation emails failed to deliver
between 18:00 and 20:30 UTC. Affected customers did not receive confirmation
of their bookings and contacted support in large numbers. The email queue
had a depth of 4,200 messages at peak."
root_cause: "The email worker service was under-provisioned for peak load.
The worker pool was hardcoded to 5 concurrent workers. During the evening
peak booking window, the queue grew faster than the 5 workers could process.
Messages that remained queued for more than 2 hours were moved to the dead
letter queue by the queue TTL policy, never being sent."
long_term_fix: "1. Worker pool increased from 5 to 20 with auto-scaling
based on queue depth
2. Queue depth alert at 500 messages (previously no alert existed)
3. Dead letter queue now triggers immediate alert and retry job
4. Email delivery SLA dashboard added to ops monitoring
5. Queue TTL increased from 2 hours to 24 hours"
related_tickets: ["B1-1002"]

═══════════════════════════════════════════════════════════════
SECTION 6: EMBEDDING GENERATION
═══════════════════════════════════════════════════════════════

For each ticket and incident, generate a real Vertex AI embedding:

1. Prepare text using the same prepare_ticket_text() / prepare_incident_text()
   functions from pipeline/embedding_worker/processor.py
   (import and reuse — do not duplicate the logic)

2. Call embed(text) for each record
   Log progress: "Embedding ticket B1-1001 (1/30)..."
   Sleep 1 second between calls to respect rate limits

3. Upsert each record with its real embedding into the database

═══════════════════════════════════════════════════════════════
SECTION 7: EXECUTION
═══════════════════════════════════════════════════════════════

Main function should:
1. Connect to DB using DATABASE_URL from .env.local
2. Insert business units
3. Insert all 30 tickets with embeddings (B1 first, then B2)
4. Insert all 5 incidents with embeddings
5. Print final summary:

   ✅ Seed data inserted successfully
   ─────────────────────────────────
   Business Units : 2 (B1 - Reservations Platform, B2 - Payments Platform)
   B1 Tickets     : 15 (12 resolved, 2 open, 1 in progress)
   B2 Tickets     : 15 (13 resolved, 1 open, 1 incident)
   Incidents      : 5  (all resolved, with full RCA)
   Total embeddings generated: 35
   ─────────────────────────────────
   Try asking:
   • "We have database timeout issues in the reservation search"
   • "What happened with the payment outage in March?"
   • "Are there incidents related to overbooking?"
   • "What is the status of B1-1008?"

Usage:
  python scripts/seed_demo_data.py

Requirements file: scripts/requirements-scripts.txt
  asyncpg, vertexai, google-cloud-aiplatform, python-dotenv, structlog
```

---

## PROMPT SD.2 — Seed Users Script

```
Create scripts/seed_users.py — creates default engineer and admin accounts.

Insert these users (skip if email already exists):

1. Admin user
   email: admin@company.com
   password: Admin@1234  (bcrypt hashed)
   full_name: System Admin
   role: admin

2. L1/L2 Engineer
   email: l1engineer@company.com
   password: Engineer@1234  (bcrypt hashed)
   full_name: L1/L2 Support Engineer
   role: engineer

3. L3 Engineer
   email: l3engineer@company.com
   password: Engineer@1234  (bcrypt hashed)
   full_name: L3 Support Engineer
   role: engineer

Print on completion:
  ✅ Users seeded
  ─────────────────────────────────────────────
  admin@company.com       / Admin@1234    (admin)
  l1engineer@company.com  / Engineer@1234 (engineer)
  l3engineer@company.com  / Engineer@1234 (engineer)
  ─────────────────────────────────────────────
  Use these credentials to log in to the application.

Requirements:
- asyncpg for DB
- passlib[bcrypt] for password hashing
- python-dotenv to load DATABASE_URL
```

---

## PROMPT SD.3 — Update seed_test_data.py Orchestrator

```
Update scripts/seed_test_data.py to be the master orchestrator that runs all seed scripts in order.

import subprocess, sys

steps = [
    ("Seeding users...",     ["python", "scripts/seed_users.py"]),
    ("Seeding demo data...", ["python", "scripts/seed_demo_data.py"]),
]

for label, cmd in steps:
    print(f"\n{label}")
    result = subprocess.run(cmd, check=True)

print("\n✅ All seed data loaded. Application is ready to demo.")
```

---

## What the Seed Data Enables

After running these scripts, engineers can immediately demo:

| Question to ask the chatbot | Expected behaviour |
|---|---|
| "We're seeing database timeouts in the reservation search" | Finds B1-1008, B1-1013, links to INC-001 |
| "What happened with the March payment outage?" | Finds INC-002, links to B2-2004 |
| "Have we had overbooking incidents before?" | Finds INC-003, links to B1-1015 and B1-1006 |
| "What is the status of B1-1008?" | Fetches B1-1008 directly — shows Open status and discussion |
| "How did we fix the email delay issue?" | Finds B1-1002 and INC-005, shows resolution |
| "Are there any payment incidents and were tickets raised?" | Cross-ref: INC-002 → B2-2004, B2-2012 |
| "What was the long-term fix for the currency rate incident?" | Finds INC-004, returns long_term_fix field |
| "Show me open tickets in B1" | Returns B1-1004 and B1-1008 |
| "We have a race condition in concurrent booking requests" | Finds B1-1015 and INC-003 |
| "3D Secure failing for European cards" | Finds B2-2002 with resolution |
