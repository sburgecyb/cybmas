"""Seed realistic support tickets and incidents with Vertex AI embeddings.

Idempotent — re-running updates existing rows via ON CONFLICT DO UPDATE.

Usage:
    python scripts/seed_demo_data.py
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import structlog
from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

load_dotenv(_ROOT / ".env.local")

from pipeline.embedding_worker.embedder import embed_text  # noqa: E402
from pipeline.embedding_worker.processor import (  # noqa: E402
    prepare_incident_text,
    prepare_ticket_text,
)

log = structlog.get_logger()

# ── Timestamps ─────────────────────────────────────────────────────────────────

_NOW = datetime(2024, 6, 1, tzinfo=timezone.utc)

# ── Demo data ──────────────────────────────────────────────────────────────────

_B1_TICKETS: list[dict] = [
    {
        "jira_id": "B1-1001", "business_unit": "B1", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Search results returning stale availability data after cache flush",
        "description": (
            "After the scheduled cache flush at 02:00 UTC, the availability search API "
            "continued serving stale data for up to 45 minutes. Customers were seeing "
            "rooms marked as available that had already been booked. The issue affected "
            "approximately 340 search queries before being detected."
        ),
        "resolution": (
            "Root cause was a race condition in the Redis cache warm-up logic. The cache "
            "was being marked as ready before all availability keys had been populated. "
            "Fix: added a readiness gate that checks key count before marking cache "
            "warm-up complete. Deployed in v2.4.1."
        ),
        "discussion": [
            {"author": "sarah.chen", "body": "Confirmed — Redis KEYS availability count was 0 at 02:03 UTC but cache was marked ready at 02:01 UTC."},
            {"author": "james.okafor", "body": "Fix deployed to prod at 09:45 UTC. Cache warm-up now validates key count threshold before marking ready."},
        ],
    },
    {
        "jira_id": "B1-1002", "business_unit": "B1", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Booking confirmation emails delayed by up to 2 hours during peak load",
        "description": (
            "Engineers reported that booking confirmation emails were being delayed "
            "significantly during peak hours (18:00-22:00 UTC). The email queue depth "
            "was growing faster than the worker pool could process. Customers were "
            "calling support asking if their bookings were confirmed."
        ),
        "resolution": (
            "The email worker pool was hardcoded to 5 workers. Increased to 20 workers "
            "and implemented auto-scaling based on queue depth. Also added dead letter "
            "queue for failed email jobs. Queue depth alert set at 500 messages."
        ),
        "discussion": [
            {"author": "mike.torres", "body": "Queue depth hit 4200 at 19:30 UTC. Workers were at max CPU."},
            {"author": "priya.sharma", "body": "Scaled workers to 20. Queue cleared within 15 minutes."},
        ],
    },
    {
        "jira_id": "B1-1003", "business_unit": "B1", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Reservation modification API returning 500 errors for bookings older than 90 days",
        "description": (
            "Customers attempting to modify reservations made more than 90 days ago "
            "were receiving 500 Internal Server Error responses. The issue was introduced "
            "in the v2.3.0 release which changed the date range validation logic."
        ),
        "resolution": (
            "A date arithmetic bug in the modification eligibility check was computing "
            "negative values for old bookings. Fixed by using absolute value in the date "
            "comparison. Fix released in v2.3.1."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B1-1004", "business_unit": "B1", "ticket_type": "BUG",
        "status": "In Progress",
        "summary": "Room type images not loading on booking confirmation page in Safari",
        "description": (
            "Customers using Safari (iOS and macOS) reported that room type images on "
            "the booking confirmation page fail to load. Chrome and Firefox are not "
            "affected. Issue appears related to CORS headers on the image CDN."
        ),
        "resolution": None,
        "discussion": [
            {"author": "alex.wu", "body": "Reproduced on Safari 17.2. The CDN is returning CORS headers without the required Origin header echo. Filed with CDN vendor."},
        ],
    },
    {
        "jira_id": "B1-1005", "business_unit": "B1", "ticket_type": "TASK",
        "status": "Resolved",
        "summary": "Migrate reservation search index from Elasticsearch 7 to Elasticsearch 8",
        "description": (
            "Elasticsearch 7 reaches end of life. Need to upgrade the reservation search "
            "cluster to ES8. This requires updating the client library, migrating index "
            "mappings, and reindexing approximately 12 million reservation records."
        ),
        "resolution": (
            "Migration completed over a weekend maintenance window. Reindex took 4.5 "
            "hours. Zero downtime achieved by using dual-write during transition."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B1-1006", "business_unit": "B1", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Duplicate booking records created when payment gateway timeout occurs",
        "description": (
            "When the payment gateway returns a timeout (504), the reservation service "
            "was retrying the entire booking creation including the DB insert. This "
            "created duplicate booking records. Discovered when a guest received two "
            "confirmation emails."
        ),
        "resolution": (
            "Implemented idempotency keys on booking creation. Payment requests now "
            "include a UUID idempotency key. Retries reuse the same key so the payment "
            "gateway deduplicates. DB insert uses ON CONFLICT DO NOTHING. Fixed in v2.5.0."
        ),
        "discussion": [
            {"author": "james.okafor", "body": "Found 23 duplicate booking pairs in production. Guest services team manually cancelled the duplicates."},
            {"author": "sarah.chen", "body": "Idempotency implementation reviewed and approved. Deploying tonight."},
        ],
    },
    {
        "jira_id": "B1-1007", "business_unit": "B1", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Group booking API fails when party size exceeds 10 guests",
        "description": (
            "The group booking endpoint returns HTTP 422 for any booking request with "
            "more than 10 guests. A hardcoded validation limit was never updated after "
            "the product team increased the maximum group size to 20."
        ),
        "resolution": (
            "Updated MAX_GROUP_SIZE constant from 10 to 20 in booking-service config. "
            "Added unit test for boundary values. Released in v2.4.2."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B1-1008", "business_unit": "B1", "ticket_type": "BUG",
        "status": "Open",
        "summary": "Search API response time degrading under high load - p95 exceeding 3 seconds",
        "description": (
            "Since the v2.5.0 deployment, the reservation search API p95 latency has "
            "been trending upward. During peak hours it now exceeds 3 seconds compared "
            "to the 800ms baseline. Database query plans show a sequential scan on the "
            "availability_cache table. The index may have been dropped during migration."
        ),
        "resolution": None,
        "discussion": [
            {"author": "priya.sharma", "body": "EXPLAIN ANALYZE shows seq scan on availability_cache. The idx_availability_date_property index is missing from prod."},
            {"author": "mike.torres", "body": "Confirmed index was accidentally dropped in migration script step 7. Working on hotfix."},
        ],
    },
    {
        "jira_id": "B1-1009", "business_unit": "B1", "ticket_type": "STORY",
        "status": "Resolved",
        "summary": "Implement real-time room availability websocket updates",
        "description": (
            "Currently availability data is polled every 30 seconds. Product requirement "
            "to implement WebSocket-based push updates so availability changes reflect "
            "in the UI within 2 seconds."
        ),
        "resolution": (
            "Implemented WebSocket server using FastAPI WebSockets. Room availability "
            "changes publish to Redis pub/sub channel. Average latency from availability "
            "change to UI update: 340ms. Deployed in v2.6.0."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B1-1010", "business_unit": "B1", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Cancellation refund amounts incorrect for multi-night bookings with rate changes",
        "description": (
            "When a multi-night booking spans a rate change date and is cancelled, "
            "the refund calculation was using only the first night rate for all nights. "
            "This resulted in incorrect refund amounts."
        ),
        "resolution": (
            "Fixed the refund calculation to look up the per-night rate for each night "
            "individually. Added integration test covering rate-change boundary scenarios. "
            "Finance team confirmed 8 affected bookings were manually corrected."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B1-1011", "business_unit": "B1", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Loyalty points not awarded for bookings made through corporate API",
        "description": (
            "Bookings created via the corporate B2B API were not triggering the loyalty "
            "points award event. The loyalty service only listened for events from the "
            "consumer booking flow."
        ),
        "resolution": (
            "Added CORPORATE_BOOKING_CREATED to the loyalty service event handler mapping. "
            "Backfilled loyalty points for 156 affected bookings via admin script. "
            "Released in v2.4.3."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B1-1012", "business_unit": "B1", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Date picker widget allowing selection of past dates on mobile browsers",
        "description": (
            "The check-in date picker on mobile browsers was not enforcing the min-date "
            "constraint correctly. Users could select past dates and proceed to payment "
            "before receiving a validation error server-side."
        ),
        "resolution": (
            "Fixed by explicitly setting min attribute on the native date input for "
            "mobile and adding client-side validation. Tested on iOS 17 and Android 14."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B1-1013", "business_unit": "B1", "ticket_type": "TASK",
        "status": "Resolved",
        "summary": "Add database connection pooling to reduce Cloud SQL connection overhead",
        "description": (
            "Each reservation service instance was opening direct connections to Cloud "
            "SQL, exhausting the max_connections limit during peak load. Need to "
            "implement PgBouncer connection pooling."
        ),
        "resolution": (
            "Deployed PgBouncer as a sidecar container. Pool size set to 25 per "
            "instance. Max Cloud SQL connections stable at 150 even during peak load "
            "of 40 service instances. p99 query latency improved by 35%."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B1-1014", "business_unit": "B1", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Search filters not persisting when navigating back from property detail page",
        "description": (
            "When a user applies search filters, views a property, and navigates back, "
            "all filters are reset to defaults. This forces users to re-enter their "
            "search criteria, leading to high bounce rates."
        ),
        "resolution": (
            "Implemented search state persistence using URL query parameters. Filters "
            "are now encoded in the URL and restored on navigation. Analytics showed "
            "23% reduction in search abandonment after fix."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B1-1015", "business_unit": "B1", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Overbooking occurring during concurrent booking requests for last available room",
        "description": (
            "When multiple users simultaneously attempt to book the last available room, "
            "the availability check and booking creation were not atomic. This resulted "
            "in multiple bookings for the same room — an overbooking situation."
        ),
        "resolution": (
            "Implemented SELECT FOR UPDATE on availability rows during booking creation. "
            "Concurrent requests for the same room are serialized. Load tested with 100 "
            "concurrent requests — zero overbookings."
        ),
        "discussion": [],
    },
]

_B2_TICKETS: list[dict] = [
    {
        "jira_id": "B2-2001", "business_unit": "B2", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Payment gateway returning intermittent 503 errors during Stripe webhook processing",
        "description": (
            "Stripe webhook events for payment_intent.succeeded were triggering 503 "
            "Service Unavailable responses. The webhooks were being retried by Stripe, "
            "causing duplicate processing attempts. Some bookings were marked as paid twice."
        ),
        "resolution": (
            "Implemented webhook deduplication using Redis (key: webhook:{event_id}, "
            "TTL 24h). Added idempotency check before processing. Connection pool "
            "increased. Stripe dashboard shows 100% webhook success rate since fix."
        ),
        "discussion": [
            {"author": "david.kim", "body": "Found 47 duplicate payment events in the audit log from the past week."},
            {"author": "lisa.patel", "body": "Redis deduplication deployed. Monitoring webhook success rate."},
        ],
    },
    {
        "jira_id": "B2-2002", "business_unit": "B2", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "3D Secure authentication failing for certain European card issuers",
        "description": (
            "Customers with cards from specific European banks (ING, Rabobank, ABN AMRO) "
            "were failing 3DS2 authentication. The 3DS2 iframe was being blocked by our "
            "Content Security Policy."
        ),
        "resolution": (
            "Added the 3DS2 authentication domains to the CSP frame-src directive. Also "
            "added stripecdn.com for asset loading. European conversion rate improved by "
            "4.2% in the week after fix."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B2-2003", "business_unit": "B2", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Currency conversion rates not refreshing - showing 6-hour-old rates",
        "description": (
            "The payment service was caching currency conversion rates with a TTL that "
            "was set to 21600 seconds (6 hours) instead of the intended 600 seconds "
            "(10 minutes). Customers were seeing exchange rates that could be "
            "significantly out of date."
        ),
        "resolution": (
            "Fixed TTL configuration — CURRENCY_CACHE_TTL env var was being read as a "
            "string and not converted to int, so Redis was using default TTL. Fixed "
            "with explicit int() cast. Rates now refresh every 10 minutes."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B2-2004", "business_unit": "B2", "ticket_type": "INCIDENT",
        "status": "Resolved",
        "summary": "Payment processing outage - all card payments failing for 23 minutes",
        "description": (
            "At 14:22 UTC on March 15, all card payment attempts were failing with a "
            "generic error. Investigation revealed that the payment service TLS certificate "
            "for the Stripe API connection had expired. The certificate renewal job had "
            "been silently failing for 3 days."
        ),
        "resolution": (
            "Certificate renewed manually. TLS certificate expiry monitoring added to "
            "Cloud Monitoring with 30-day and 7-day advance alerts. Certificate renewal "
            "automation repaired."
        ),
        "discussion": [
            {"author": "david.kim", "body": "Incident started 14:22 UTC. First customer report at 14:24 UTC. Service restored 14:45 UTC."},
            {"author": "ops.team", "body": "Post-incident: 1847 failed payment attempts. All customers received retry emails."},
        ],
    },
    {
        "jira_id": "B2-2005", "business_unit": "B2", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Refund API timeout when processing refunds for orders older than 180 days",
        "description": (
            "The refund endpoint was timing out for orders created more than 180 days "
            "ago. The query to fetch the original payment intent was performing a full "
            "table scan due to missing index on created_at column."
        ),
        "resolution": (
            "Added composite index on (created_at, status) for the payments table. "
            "Refund query now uses index seek. P99 refund API latency reduced from 28s "
            "to 340ms. Created index using CREATE INDEX CONCURRENTLY."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B2-2006", "business_unit": "B2", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Apple Pay button not displaying for customers in unsupported regions",
        "description": (
            "Instead of gracefully hiding the Apple Pay button for customers in regions "
            "where Apple Pay is not supported, the button was displaying but failing "
            "with a cryptic JavaScript error when clicked."
        ),
        "resolution": (
            "Added proper Apple Pay availability check using PaymentRequest.canMakePayment() "
            "before rendering the button. Button now only shown when Apple Pay is "
            "available in the customer region."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B2-2007", "business_unit": "B2", "ticket_type": "BUG",
        "status": "Open",
        "summary": "Split payment feature failing when total amount exceeds 10000 USD",
        "description": (
            "The split payment feature is failing for total booking amounts above "
            "$10,000. The payment service is returning HTTP 400 Bad Request. Initial "
            "investigation suggests the amount validation is using integer arithmetic "
            "that overflows for large amounts when converted to cents."
        ),
        "resolution": None,
        "discussion": [
            {"author": "lisa.patel", "body": "Confirmed: amount * 100 overflows int32 for values > $21,474. Need to use int64 or Decimal throughout payment amount handling."},
        ],
    },
    {
        "jira_id": "B2-2008", "business_unit": "B2", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Payment reconciliation report missing transactions from timezone boundary",
        "description": (
            "The daily payment reconciliation report was missing transactions that "
            "occurred between 23:00-24:00 UTC. The report query was using local server "
            "time instead of UTC for the day boundary calculation."
        ),
        "resolution": (
            "Standardized all report date range queries to use UTC explicitly. Added "
            "unit tests for UTC boundary conditions."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B2-2009", "business_unit": "B2", "ticket_type": "STORY",
        "status": "Resolved",
        "summary": "Implement PayPal payment method alongside existing Stripe integration",
        "description": (
            "Product requirement to add PayPal as an alternative payment method. "
            "Requires integrating PayPal Orders API v2, handling PayPal webhooks, and "
            "mapping PayPal transaction states to internal payment states."
        ),
        "resolution": (
            "PayPal integration completed and deployed in v3.1.0. A/B test shows 8% "
            "higher conversion for customers who see the PayPal option."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B2-2010", "business_unit": "B2", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Fraud detection false positives blocking legitimate corporate card payments",
        "description": (
            "The fraud detection model was flagging corporate Amex cards as high-risk, "
            "causing approximately 15% of corporate bookings to be declined. The model "
            "had been trained primarily on consumer card data."
        ),
        "resolution": (
            "Added corporate_card feature flag to fraud detection pipeline. Corporate "
            "Amex BIN ranges are now routed through a separate model tuned for corporate "
            "card patterns. False positive rate reduced from 15% to 0.8%."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B2-2011", "business_unit": "B2", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Chargeback webhook processing failing silently - disputed payments not updating",
        "description": (
            "Stripe chargeback webhooks were arriving at the webhook endpoint and "
            "returning 200 OK, but the payment status was not being updated to DISPUTED "
            "in the database. The dispute handler was catching the database exception "
            "and logging it but not re-raising."
        ),
        "resolution": (
            "Fixed the exception handler in dispute processing to re-raise after logging. "
            "Added monitoring alert on chargeback processing errors. Backfilled 34 "
            "disputed payments."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B2-2012", "business_unit": "B2", "ticket_type": "TASK",
        "status": "Resolved",
        "summary": "PCI DSS compliance audit - remediate findings from quarterly scan",
        "description": (
            "Q3 PCI DSS vulnerability scan identified three findings: TLS 1.0 and 1.1 "
            "still enabled on payment API endpoints, default error messages exposing "
            "internal stack traces, admin payment portal accessible from internet "
            "without MFA."
        ),
        "resolution": (
            "All three findings remediated: disabled TLS 1.0/1.1, added global exception "
            "handler, moved admin portal to VPN-only access with mandatory 2FA. Passed "
            "follow-up scan with zero findings."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B2-2013", "business_unit": "B2", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Payment amount displayed with wrong decimal places for JPY transactions",
        "description": (
            "Japanese Yen (JPY) is a zero-decimal currency. The payment display code "
            "was dividing all currencies by 100, showing 15000 JPY as 150.00 JPY. "
            "This caused confusion for Japanese customers."
        ),
        "resolution": (
            "Added ZERO_DECIMAL_CURRENCIES constant containing ISO 4217 codes for "
            "currencies with no minor units. Display formatter now checks this list "
            "before applying decimal division."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B2-2014", "business_unit": "B2", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Saved payment methods disappearing after password reset",
        "description": (
            "When a customer resets their password, their saved payment methods were "
            "being deleted. The password reset flow was calling the user cleanup "
            "function which incorrectly included a step to remove all associated "
            "Stripe customer data."
        ),
        "resolution": (
            "Removed the Stripe customer data cleanup from password reset flow. That "
            "cleanup should only run on account deletion. Added integration test "
            "verifying saved payment methods persist through password reset."
        ),
        "discussion": [],
    },
    {
        "jira_id": "B2-2015", "business_unit": "B2", "ticket_type": "BUG",
        "status": "Resolved",
        "summary": "Invoice PDF generation failing for bookings with special characters in guest name",
        "description": (
            "Invoice PDF generation was throwing an exception when the guest name "
            "contained special characters such as accented letters or Unicode "
            "characters. The PDF library was using Latin-1 encoding by default."
        ),
        "resolution": (
            "Updated PDF generation to use UTF-8 encoding explicitly. Switched to "
            "ReportLab TTFont with a Unicode-compatible font. Tested with names in "
            "Arabic, Chinese, Japanese, and various European scripts."
        ),
        "discussion": [],
    },
]

_INCIDENTS: list[dict] = [
    {
        "jira_id": "INC-001", "business_unit": "B1", "severity": "P1",
        "title": "Reservations Platform - Complete search outage for 47 minutes",
        "description": (
            "At 09:15 UTC on January 8, the reservation search service became completely "
            "unavailable. All search API calls were returning HTTP 503. The outage lasted "
            "47 minutes and affected 100% of search traffic."
        ),
        "root_cause": (
            "An unvalidated configuration change was deployed to the search service that "
            "set the Elasticsearch cluster URL to an incorrect value. The health check "
            "endpoint was not testing the search dependency, only the service itself. "
            "The misconfiguration passed all smoke tests."
        ),
        "long_term_fix": (
            "1. Added Elasticsearch connectivity to health check endpoint. "
            "2. Implemented configuration validation at startup - service fails to start "
            "if critical dependencies are unreachable. "
            "3. Added pre-deployment configuration diff review step. "
            "4. Elasticsearch cluster URL moved to Secret Manager."
        ),
        "related_tickets": ["B1-1008", "B1-1013"],
    },
    {
        "jira_id": "INC-002", "business_unit": "B2", "severity": "P1",
        "title": "Payment Processing - All card payments failing for 23 minutes",
        "description": (
            "At 14:22 UTC on March 15, all card payment attempts were failing. Customers "
            "received generic payment failure messages. Total business impact: 1847 failed "
            "payment attempts, estimated $340,000 in delayed revenue."
        ),
        "root_cause": (
            "The TLS certificate used by the payment service to authenticate with the "
            "Stripe API expired at 14:22 UTC. The automated certificate renewal Cloud "
            "Run job had been failing silently for 3 days - the job was misconfigured "
            "to write the renewed certificate to a GCS bucket path that the service "
            "account no longer had write access to."
        ),
        "long_term_fix": (
            "1. Certificate expiry monitoring: Cloud Monitoring alerts at 30 days, 14 "
            "days, and 7 days before expiry. "
            "2. Certificate renewal job permissions corrected and tested. "
            "3. Certificate renewal now sends Slack notification on success/failure. "
            "4. Runbook created for manual certificate renewal as fallback."
        ),
        "related_tickets": ["B2-2004", "B2-2012"],
    },
    {
        "jira_id": "INC-003", "business_unit": "B1", "severity": "P2",
        "title": "Reservations Platform - Overbooking event affecting 12 properties",
        "description": (
            "On February 3, the reservations team identified 31 overbooking instances "
            "across 12 properties. Guests with confirmed bookings arrived to find their "
            "rooms already occupied. Engineering was engaged at 15:30 UTC."
        ),
        "root_cause": (
            "A race condition in the availability locking mechanism. During a traffic "
            "spike caused by a flash sale, multiple concurrent booking requests for the "
            "same room were passing the availability check simultaneously before any of "
            "them had committed the booking to the database. The availability table had "
            "no row-level locking."
        ),
        "long_term_fix": (
            "1. Implemented SELECT FOR UPDATE on availability rows during booking creation. "
            "2. Added optimistic locking with version counter as secondary protection. "
            "3. Database-level unique constraint on (room_id, check_in_date). "
            "4. Load testing suite updated to include concurrent booking scenarios."
        ),
        "related_tickets": ["B1-1015", "B1-1006"],
    },
    {
        "jira_id": "INC-004", "business_unit": "B2", "severity": "P2",
        "title": "Payments Platform - Currency conversion showing wrong rates for 4 hours",
        "description": (
            "On April 12 between 08:00 and 12:00 UTC, customers making international "
            "payments were being quoted exchange rates that were up to 8% different from "
            "the actual market rate. Finance identified the discrepancy during morning "
            "reconciliation."
        ),
        "root_cause": (
            "The currency rate cache TTL was configured as 21600 seconds (6 hours) "
            "instead of the intended 600 seconds (10 minutes). This was caused by a "
            "type conversion bug - the TTL was being read from an environment variable "
            "as a string and passed directly to Redis SET, which treated the string "
            "value as a Unix timestamp expiry set in 1970, effectively never expiring."
        ),
        "long_term_fix": (
            "1. Fixed type conversion: int(os.getenv('CURRENCY_CACHE_TTL', '600')). "
            "2. Added startup validation that logs and alerts if cache TTL exceeds 1800 "
            "seconds. "
            "3. Currency rate age now included in API response headers. "
            "4. Added integration test verifying TTL is set correctly."
        ),
        "related_tickets": ["B2-2003", "B2-2008"],
    },
    {
        "jira_id": "INC-005", "business_unit": "B1", "severity": "P3",
        "title": "Reservations Platform - Email delivery failure for 340 confirmation emails",
        "description": (
            "On May 7, 340 booking confirmation emails failed to deliver between 18:00 "
            "and 20:30 UTC. Affected customers did not receive confirmation of their "
            "bookings and contacted support in large numbers."
        ),
        "root_cause": (
            "The email worker service was under-provisioned for peak load. The worker "
            "pool was hardcoded to 5 concurrent workers. During the evening peak booking "
            "window, the queue grew faster than the 5 workers could process. Messages "
            "queued for more than 2 hours were moved to the dead letter queue by the "
            "TTL policy, never being sent."
        ),
        "long_term_fix": (
            "1. Worker pool increased from 5 to 20 with auto-scaling based on queue depth. "
            "2. Queue depth alert at 500 messages. "
            "3. Dead letter queue now triggers immediate alert and retry job. "
            "4. Queue TTL increased from 2 hours to 24 hours."
        ),
        "related_tickets": ["B1-1002"],
    },
]

# ── Helpers ────────────────────────────────────────────────────────────────────


def _to_vector_str(values: list[float]) -> str:
    return "[" + ",".join(str(v) for v in values) + "]"


async def embed(text: str) -> list[float]:
    """Embed text via the pipeline embedder and sleep 1 s to respect rate limits."""
    result = await embed_text(text)
    await asyncio.sleep(1)
    return result


async def upsert_ticket(conn: asyncpg.Connection, ticket: dict, embedding: list[float]) -> None:
    await conn.execute(
        """
        INSERT INTO tickets (
            jira_id, business_unit, ticket_type, summary, description,
            status, resolution, discussion, created_at, updated_at,
            embedding, raw_json
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10, $11::vector, $12::jsonb)
        ON CONFLICT (jira_id) DO UPDATE SET
            business_unit = EXCLUDED.business_unit,
            ticket_type   = EXCLUDED.ticket_type,
            summary       = EXCLUDED.summary,
            description   = EXCLUDED.description,
            status        = EXCLUDED.status,
            resolution    = EXCLUDED.resolution,
            discussion    = EXCLUDED.discussion,
            updated_at    = EXCLUDED.updated_at,
            embedding     = EXCLUDED.embedding,
            raw_json      = EXCLUDED.raw_json
        """,
        ticket["jira_id"],
        ticket["business_unit"],
        ticket["ticket_type"],
        ticket["summary"],
        ticket.get("description"),
        ticket["status"],
        ticket.get("resolution"),
        json.dumps(ticket.get("discussion") or []),
        _NOW,
        _NOW,
        _to_vector_str(embedding),
        json.dumps({"jira_id": ticket["jira_id"], "seeded": True}),
    )


async def upsert_incident(conn: asyncpg.Connection, incident: dict, embedding: list[float]) -> None:
    await conn.execute(
        """
        INSERT INTO incidents (
            jira_id, business_unit, title, description, root_cause,
            long_term_fix, related_tickets, severity, resolved_at,
            created_at, updated_at, embedding, raw_json
        ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11, $12::vector, $13::jsonb)
        ON CONFLICT (jira_id) DO UPDATE SET
            business_unit  = EXCLUDED.business_unit,
            title          = EXCLUDED.title,
            description    = EXCLUDED.description,
            root_cause     = EXCLUDED.root_cause,
            long_term_fix  = EXCLUDED.long_term_fix,
            related_tickets = EXCLUDED.related_tickets,
            severity       = EXCLUDED.severity,
            resolved_at    = EXCLUDED.resolved_at,
            updated_at     = EXCLUDED.updated_at,
            embedding      = EXCLUDED.embedding,
            raw_json       = EXCLUDED.raw_json
        """,
        incident["jira_id"],
        incident["business_unit"],
        incident["title"],
        incident.get("description"),
        incident.get("root_cause"),
        incident.get("long_term_fix"),
        json.dumps(incident.get("related_tickets") or []),
        incident["severity"],
        _NOW,
        _NOW,
        _NOW,
        _to_vector_str(embedding),
        json.dumps({"jira_id": incident["jira_id"], "seeded": True}),
    )


# ── Main ───────────────────────────────────────────────────────────────────────


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    if not dsn:
        print("ERROR: DATABASE_URL not set in .env.local", file=sys.stderr)
        sys.exit(1)

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)

    async with pool.acquire() as conn:
        # ── Business units ─────────────────────────────────────────────────────
        await conn.execute(
            """
            INSERT INTO business_units (code, name) VALUES
                ('B1', 'Reservations Platform'),
                ('B2', 'Payments Platform')
            ON CONFLICT (code) DO NOTHING
            """
        )
        log.info("seed.business_units_ok")

        # ── Tickets ────────────────────────────────────────────────────────────
        all_tickets = _B1_TICKETS + _B2_TICKETS
        for idx, ticket in enumerate(all_tickets, start=1):
            jira_id = ticket["jira_id"]
            print(f"  Embedding ticket {jira_id} ({idx}/{len(all_tickets)})...", flush=True)
            text = prepare_ticket_text(ticket)
            vector = await embed(text)
            await upsert_ticket(conn, ticket, vector)
            log.info("seed.ticket_upserted", jira_id=jira_id, idx=idx, total=len(all_tickets))

        # ── Incidents ──────────────────────────────────────────────────────────
        for idx, incident in enumerate(_INCIDENTS, start=1):
            jira_id = incident["jira_id"]
            print(f"  Embedding incident {jira_id} ({idx}/{len(_INCIDENTS)})...", flush=True)
            text = prepare_incident_text(incident)
            vector = await embed(text)
            await upsert_incident(conn, incident, vector)
            log.info("seed.incident_upserted", jira_id=jira_id, idx=idx, total=len(_INCIDENTS))

    await pool.close()

    total = len(all_tickets) + len(_INCIDENTS)
    divider = "─" * 37
    print(f"\n✅ Seed data inserted successfully")
    print(divider)
    print(f"  Business Units  : 2")
    print(f"  B1 Tickets      : {len(_B1_TICKETS)}")
    print(f"  B2 Tickets      : {len(_B2_TICKETS)}")
    print(f"  Incidents       : {len(_INCIDENTS)}")
    print(f"  Total embeddings: {total}")
    print(divider)
    print("Try asking:")
    print('  - "We have database timeout issues in the reservation search"')
    print('  - "What happened with the payment outage in March?"')
    print('  - "Are there incidents related to overbooking?"')
    print('  - "What is the status of B1-1008?"')


if __name__ == "__main__":
    asyncio.run(main())
