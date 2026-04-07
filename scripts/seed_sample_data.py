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
      "jira_id": "B1-4004",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "James Okafor",
          "body": "Initial observation: Users reporting intermittent login failures. Checking logs now."
        },
        {
          "author": "Rahul Sharma",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Rahul Sharma",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Arjun Reddy",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Li Wei",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Maria Garcia",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Priya Nair",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "James Okafor",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Fatima Khan",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "James Okafor",
          "body": "Suggest rollback of last release."
        }
      ]
    },
    {
      "jira_id": "B1-4008",
      "business_unit": "B1",
      "ticket_type": "Task",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "David Chen",
          "body": "Initial observation: Users reporting intermittent login failures. Checking logs now."
        },
        {
          "author": "James Okafor",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "James Okafor",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Maria Garcia",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Fatima Khan",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "David Chen",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "James Okafor",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Maria Garcia",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Rahul Sharma",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Priya Nair",
          "body": "Looks like connection pool saturation."
        }
      ]
    },
    {
      "jira_id": "B2-4011",
      "business_unit": "B2",
      "ticket_type": "Story",
      "summary": "Search results inconsistent across regions",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Priya Nair",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "Priya Nair",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Maria Garcia",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Fatima Khan",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "James Okafor",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Rahul Sharma",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Arjun Reddy",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Maria Garcia",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "James Okafor",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "David Chen",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        }
      ]
    },
    {
      "jira_id": "B1-4013",
      "business_unit": "B1",
      "ticket_type": "Bug",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Maria Garcia",
          "body": "Initial observation: DB latency increased after last deployment. Checking logs now."
        },
        {
          "author": "Maria Garcia",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Priya Nair",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Li Wei",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Fatima Khan",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "David Chen",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Fatima Khan",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Arjun Reddy",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Amit Verma",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Li Wei",
          "body": "Looks like connection pool saturation."
        }
      ]
    },
    {
      "jira_id": "B1-4018",
      "business_unit": "B1",
      "ticket_type": "Bug",
      "summary": "Search results inconsistent across regions",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Fatima Khan",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Li Wei",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Maria Garcia",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Fatima Khan",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "James Okafor",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Rahul Sharma",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Priya Nair",
          "body": "Reproduced partially in staging."
        }
      ]
    },
    {
      "jira_id": "B1-4019",
      "business_unit": "B1",
      "ticket_type": "Bug",
      "summary": "High latency in recommendation engine",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Sneha Kulkarni",
          "body": "Initial observation: DB latency increased after last deployment. Checking logs now."
        },
        {
          "author": "Maria Garcia",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Fatima Khan",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Arjun Reddy",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "David Chen",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Amit Verma",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Amit Verma",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Arjun Reddy",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Li Wei",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Maria Garcia",
          "body": "Looks like connection pool saturation."
        }
      ]
    },
    {
      "jira_id": "B1-4020",
      "business_unit": "B1",
      "ticket_type": "Bug",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "",
      "discussion": [
        {
          "author": "Sneha Kulkarni",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Maria Garcia",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "James Okafor",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Priya Nair",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Rahul Sharma",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "James Okafor",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "James Okafor",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Arjun Reddy",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Li Wei",
          "body": "Temporary retry added to mitigate."
        }
      ]
    },
    {
      "jira_id": "B1-4021",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "Notification delay in email service",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Maria Garcia",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Maria Garcia",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "James Okafor",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "James Okafor",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Maria Garcia",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Li Wei",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Maria Garcia",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Rahul Sharma",
          "body": "Reproduced partially in staging."
        }
      ]
    },
    {
      "jira_id": "B1-4022",
      "business_unit": "B1",
      "ticket_type": "Bug",
      "summary": "Notification delay in email service",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "",
      "discussion": [
        {
          "author": "Sneha Kulkarni",
          "body": "Initial observation: DB latency increased after last deployment. Checking logs now."
        },
        {
          "author": "James Okafor",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Maria Garcia",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Rahul Sharma",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Maria Garcia",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Maria Garcia",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Amit Verma",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Arjun Reddy",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Priya Nair",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Priya Nair",
          "body": "Temporary retry added to mitigate."
        }
      ]
    },
    {
      "jira_id": "B1-4024",
      "business_unit": "B1",
      "ticket_type": "Bug",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "",
      "discussion": [
        {
          "author": "Amit Verma",
          "body": "Initial observation: Spike in 5xx errors from payment-service. Checking logs now."
        },
        {
          "author": "Arjun Reddy",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "David Chen",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Amit Verma",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Rahul Sharma",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Li Wei",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Rahul Sharma",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "James Okafor",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "David Chen",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        }
      ]
    },
    {
      "jira_id": "B1-4027",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Rahul Sharma",
          "body": "Initial observation: Users reporting intermittent login failures. Checking logs now."
        },
        {
          "author": "James Okafor",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Arjun Reddy",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Amit Verma",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Priya Nair",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Li Wei",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Fatima Khan",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "David Chen",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Amit Verma",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Amit Verma",
          "body": "Logs show timeout exceptions from downstream service."
        }
      ]
    },
    {
      "jira_id": "B1-4031",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Fatima Khan",
          "body": "Initial observation: Users reporting intermittent login failures. Checking logs now."
        },
        {
          "author": "James Okafor",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Li Wei",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Priya Nair",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Rahul Sharma",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Priya Nair",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Maria Garcia",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Amit Verma",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Maria Garcia",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Priya Nair",
          "body": "Looks like connection pool saturation."
        }
      ]
    },
    {
      "jira_id": "B1-4032",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Sneha Kulkarni",
          "body": "Initial observation: DB latency increased after last deployment. Checking logs now."
        },
        {
          "author": "Li Wei",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Fatima Khan",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Rahul Sharma",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Priya Nair",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Arjun Reddy",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Priya Nair",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Priya Nair",
          "body": "Root cause confirmed as timeout misconfiguration."
        }
      ]
    },
    {
      "jira_id": "B1-4033",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "High latency in recommendation engine",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Sneha Kulkarni",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "David Chen",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "David Chen",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Rahul Sharma",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Amit Verma",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Arjun Reddy",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Fatima Khan",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Priya Nair",
          "body": "Root cause confirmed as timeout misconfiguration."
        }
      ]
    },
    {
      "jira_id": "B1-4036",
      "business_unit": "B1",
      "ticket_type": "Bug",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "James Okafor",
          "body": "Initial observation: Users reporting intermittent login failures. Checking logs now."
        },
        {
          "author": "Maria Garcia",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "James Okafor",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Priya Nair",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Amit Verma",
          "body": "Temporary retry added to mitigate."
        }
      ]
    },
    {
      "jira_id": "B1-4037",
      "business_unit": "B1",
      "ticket_type": "Task",
      "summary": "High latency in recommendation engine",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Sneha Kulkarni",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "Maria Garcia",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "James Okafor",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Li Wei",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Maria Garcia",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Maria Garcia",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "James Okafor",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Arjun Reddy",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Arjun Reddy",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        }
      ]
    },
    {
      "jira_id": "B1-4038",
      "business_unit": "B1",
      "ticket_type": "Task",
      "summary": "Notification delay in email service",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Maria Garcia",
          "body": "Initial observation: Users reporting intermittent login failures. Checking logs now."
        },
        {
          "author": "Rahul Sharma",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Priya Nair",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "James Okafor",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Fatima Khan",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Maria Garcia",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "David Chen",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "James Okafor",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Rahul Sharma",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Amit Verma",
          "body": "Metrics stabilizing post fix."
        }
      ]
    },
    {
      "jira_id": "B1-4042",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "David Chen",
          "body": "Initial observation: Spike in 5xx errors from payment-service. Checking logs now."
        },
        {
          "author": "James Okafor",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Maria Garcia",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Fatima Khan",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Li Wei",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Fatima Khan",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Rahul Sharma",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "David Chen",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "James Okafor",
          "body": "Looks like connection pool saturation."
        }
      ]
    },
    {
      "jira_id": "B1-4046",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "",
      "discussion": [
        {
          "author": "Priya Nair",
          "body": "Initial observation: Users reporting intermittent login failures. Checking logs now."
        },
        {
          "author": "Li Wei",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Rahul Sharma",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "James Okafor",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Fatima Khan",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Maria Garcia",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Rahul Sharma",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Maria Garcia",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "James Okafor",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Arjun Reddy",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        }
      ]
    },
    {
      "jira_id": "B1-4050",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "Notification delay in email service",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Amit Verma",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "Fatima Khan",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Maria Garcia",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Fatima Khan",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Amit Verma",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "David Chen",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "James Okafor",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Rahul Sharma",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        }
      ]
    },
    {
      "jira_id": "B1-4067",
      "business_unit": "B1",
      "ticket_type": "Bug",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Amit Verma",
          "body": "Initial observation: Spike in 5xx errors from payment-service. Checking logs now."
        },
        {
          "author": "James Okafor",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "James Okafor",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Li Wei",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "James Okafor",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Arjun Reddy",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Rahul Sharma",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Priya Nair",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Temporary retry added to mitigate."
        }
      ]
    },
    {
      "jira_id": "B1-4068",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "High latency in recommendation engine",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Li Wei",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Maria Garcia",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Fatima Khan",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Amit Verma",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "James Okafor",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Rahul Sharma",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Rahul Sharma",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Maria Garcia",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "James Okafor",
          "body": "Can we confirm if any config changes went live?"
        }
      ]
    },
    {
      "jira_id": "B1-4073",
      "business_unit": "B1",
      "ticket_type": "Bug",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "James Okafor",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "Arjun Reddy",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Li Wei",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Fatima Khan",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "James Okafor",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "James Okafor",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "James Okafor",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Priya Nair",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Rahul Sharma",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        }
      ]
    },
    {
      "jira_id": "B1-4076",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "Search results inconsistent across regions",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Amit Verma",
          "body": "Initial observation: Spike in 5xx errors from payment-service. Checking logs now."
        },
        {
          "author": "Arjun Reddy",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Maria Garcia",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Priya Nair",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "James Okafor",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Rahul Sharma",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Amit Verma",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Fatima Khan",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "James Okafor",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Fix deployed to staging, validating."
        }
      ]
    },
    {
      "jira_id": "B1-4077",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "",
      "discussion": [
        {
          "author": "Rahul Sharma",
          "body": "Initial observation: Spike in 5xx errors from payment-service. Checking logs now."
        },
        {
          "author": "Priya Nair",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Li Wei",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Li Wei",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Amit Verma",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Arjun Reddy",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Rahul Sharma",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "James Okafor",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Priya Nair",
          "body": "Fix deployed to staging, validating."
        }
      ]
    },
    {
      "jira_id": "B1-4079",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Arjun Reddy",
          "body": "Initial observation: Spike in 5xx errors from payment-service. Checking logs now."
        },
        {
          "author": "James Okafor",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "David Chen",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Maria Garcia",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Li Wei",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Amit Verma",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Li Wei",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        }
      ]
    },
    {
      "jira_id": "B1-4080",
      "business_unit": "B1",
      "ticket_type": "Bug",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Priya Nair",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Priya Nair",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "David Chen",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Priya Nair",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Amit Verma",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Fatima Khan",
          "body": "Temporary retry added to mitigate."
        }
      ]
    },
    {
      "jira_id": "B1-4081",
      "business_unit": "B1",
      "ticket_type": "Bug",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "",
      "discussion": [
        {
          "author": "Fatima Khan",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "James Okafor",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Li Wei",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Priya Nair",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Arjun Reddy",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Rahul Sharma",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Arjun Reddy",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Arjun Reddy",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Rahul Sharma",
          "body": "Suggest rollback of last release."
        }
      ]
    },
    {
      "jira_id": "B1-4084",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "Search results inconsistent across regions",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Sneha Kulkarni",
          "body": "Initial observation: Users reporting intermittent login failures. Checking logs now."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Fatima Khan",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Li Wei",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Fatima Khan",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Amit Verma",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Priya Nair",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "James Okafor",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Arjun Reddy",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Li Wei",
          "body": "Logs show timeout exceptions from downstream service."
        }
      ]
    },
    {
      "jira_id": "B1-4085",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "High latency in recommendation engine",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Sneha Kulkarni",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Arjun Reddy",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "James Okafor",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "David Chen",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Amit Verma",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Maria Garcia",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Rahul Sharma",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Priya Nair",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Arjun Reddy",
          "body": "Suggest rollback of last release."
        }
      ]
    },
    {
      "jira_id": "B1-4091",
      "business_unit": "B1",
      "ticket_type": "Task",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "",
      "discussion": [
        {
          "author": "Li Wei",
          "body": "Initial observation: Spike in 5xx errors from payment-service. Checking logs now."
        },
        {
          "author": "Arjun Reddy",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Arjun Reddy",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Rahul Sharma",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Priya Nair",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "David Chen",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Fatima Khan",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Rahul Sharma",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Amit Verma",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        }
      ]
    },
    {
      "jira_id": "B1-4092",
      "business_unit": "B1",
      "ticket_type": "Task",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "",
      "discussion": [
        {
          "author": "Amit Verma",
          "body": "Initial observation: DB latency increased after last deployment. Checking logs now."
        },
        {
          "author": "Rahul Sharma",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Rahul Sharma",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Fatima Khan",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Rahul Sharma",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Maria Garcia",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Amit Verma",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Rahul Sharma",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Rahul Sharma",
          "body": "Temporary retry added to mitigate."
        }
      ]
    },
    {
      "jira_id": "B1-4094",
      "business_unit": "B1",
      "ticket_type": "Task",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Arjun Reddy",
          "body": "Initial observation: Users reporting intermittent login failures. Checking logs now."
        },
        {
          "author": "Priya Nair",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Priya Nair",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Maria Garcia",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Fatima Khan",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "David Chen",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "James Okafor",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "David Chen",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Rahul Sharma",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        }
      ]
    },
    {
      "jira_id": "B1-4095",
      "business_unit": "B1",
      "ticket_type": "Bug",
      "summary": "High latency in recommendation engine",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "James Okafor",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "David Chen",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Amit Verma",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Amit Verma",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Arjun Reddy",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "David Chen",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Rahul Sharma",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Maria Garcia",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "David Chen",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Metrics stabilizing post fix."
        }
      ]
    },
    {
      "jira_id": "B1-4097",
      "business_unit": "B1",
      "ticket_type": "Task",
      "summary": "Notification delay in email service",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "",
      "discussion": [
        {
          "author": "Arjun Reddy",
          "body": "Initial observation: DB latency increased after last deployment. Checking logs now."
        },
        {
          "author": "David Chen",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Rahul Sharma",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Priya Nair",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Arjun Reddy",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Priya Nair",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Li Wei",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "James Okafor",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Maria Garcia",
          "body": "Logs show timeout exceptions from downstream service."
        }
      ]
    },
    {
      "jira_id": "B1-4098",
      "business_unit": "B1",
      "ticket_type": "Story",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "David Chen",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "James Okafor",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Priya Nair",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Arjun Reddy",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "David Chen",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "David Chen",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Fatima Khan",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Rahul Sharma",
          "body": "Reproduced partially in staging."
        }
      ]
    },
    {
      "jira_id": "B1-4099",
      "business_unit": "B1",
      "ticket_type": "Bug",
      "summary": "High latency in recommendation engine",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "",
      "discussion": [
        {
          "author": "Maria Garcia",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "Amit Verma",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Rahul Sharma",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Priya Nair",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "David Chen",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Priya Nair",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "James Okafor",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Arjun Reddy",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Fatima Khan",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Looks like connection pool saturation."
        }
      ]
    },
]

_B2_TICKETS: list[dict] = [
   {
      "jira_id": "B2-4000",
      "business_unit": "B2",
      "ticket_type": "Bug",
      "summary": "Search results inconsistent across regions",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "",
      "discussion": [
        {
          "author": "James Okafor",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "David Chen",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Priya Nair",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Arjun Reddy",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "David Chen",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Rahul Sharma",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Arjun Reddy",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Maria Garcia",
          "body": "Can we confirm if any config changes went live?"
        }
      ]
    },
    {
      "jira_id": "B2-4001",
      "business_unit": "B2",
      "ticket_type": "Task",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Li Wei",
          "body": "Initial observation: DB latency increased after last deployment. Checking logs now."
        },
        {
          "author": "Rahul Sharma",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "James Okafor",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "David Chen",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Maria Garcia",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Priya Nair",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Maria Garcia",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Arjun Reddy",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Maria Garcia",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Priya Nair",
          "body": "Root cause confirmed as timeout misconfiguration."
        }
      ]
    },
    {
      "jira_id": "B2-4002",
      "business_unit": "B2",
      "ticket_type": "Bug",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "",
      "discussion": [
        {
          "author": "James Okafor",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "Li Wei",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Fatima Khan",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Li Wei",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Fatima Khan",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "David Chen",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "David Chen",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Arjun Reddy",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Arjun Reddy",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Fatima Khan",
          "body": "Suggest rollback of last release."
        }
      ]
    },
    {
      "jira_id": "B2-4003",
      "business_unit": "B2",
      "ticket_type": "Story",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Rahul Sharma",
          "body": "Initial observation: DB latency increased after last deployment. Checking logs now."
        },
        {
          "author": "Maria Garcia",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Amit Verma",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "James Okafor",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Li Wei",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "David Chen",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "James Okafor",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Fatima Khan",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        }
      ]
    },
    {
      "jira_id": "B2-4005",
      "business_unit": "B2",
      "ticket_type": "Bug",
      "summary": "High latency in recommendation engine",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Maria Garcia",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Li Wei",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "David Chen",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Li Wei",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Rahul Sharma",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Priya Nair",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Fatima Khan",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Li Wei",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Arjun Reddy",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Amit Verma",
          "body": "Logs show timeout exceptions from downstream service."
        }
      ]
    },
    {
      "jira_id": "B2-4006",
      "business_unit": "B2",
      "ticket_type": "Story",
      "summary": "Search results inconsistent across regions",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "",
      "discussion": [
        {
          "author": "Fatima Khan",
          "body": "Initial observation: Spike in 5xx errors from payment-service. Checking logs now."
        },
        {
          "author": "Rahul Sharma",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Maria Garcia",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "David Chen",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Priya Nair",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Rahul Sharma",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Rahul Sharma",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Rahul Sharma",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Root cause confirmed as timeout misconfiguration."
        }
      ]
    },
    {
      "jira_id": "B2-4007",
      "business_unit": "B2",
      "ticket_type": "Story",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Fatima Khan",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Maria Garcia",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "David Chen",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "James Okafor",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "David Chen",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Arjun Reddy",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "James Okafor",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Rahul Sharma",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Fatima Khan",
          "body": "Looks like connection pool saturation."
        }
      ]
    },
    {
      "jira_id": "B2-4012",
      "business_unit": "B2",
      "ticket_type": "Task",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "David Chen",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "Rahul Sharma",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Maria Garcia",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "David Chen",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Maria Garcia",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Arjun Reddy",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Maria Garcia",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Li Wei",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Li Wei",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Can we confirm if any config changes went live?"
        }
      ]
    },
    {
      "jira_id": "B2-4014",
      "business_unit": "B2",
      "ticket_type": "Bug",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Amit Verma",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "Maria Garcia",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Maria Garcia",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "David Chen",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "James Okafor",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Rahul Sharma",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Li Wei",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "James Okafor",
          "body": "Temporary retry added to mitigate."
        }
      ]
    },
    {
      "jira_id": "B2-4015",
      "business_unit": "B2",
      "ticket_type": "Task",
      "summary": "Search results inconsistent across regions",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "James Okafor",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "Priya Nair",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "David Chen",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Li Wei",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "David Chen",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Li Wei",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Li Wei",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Li Wei",
          "body": "Suggest rollback of last release."
        }
      ]
    },
    {
      "jira_id": "B2-4017",
      "business_unit": "B2",
      "ticket_type": "Task",
      "summary": "Search results inconsistent across regions",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "",
      "discussion": [
        {
          "author": "Maria Garcia",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Fatima Khan",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Maria Garcia",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Priya Nair",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "David Chen",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Li Wei",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "David Chen",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Fatima Khan",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Rahul Sharma",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Fatima Khan",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        }
      ]
    },
    {
      "jira_id": "B2-4023",
      "business_unit": "B2",
      "ticket_type": "Task",
      "summary": "Notification delay in email service",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "",
      "discussion": [
        {
          "author": "Fatima Khan",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "David Chen",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Arjun Reddy",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Li Wei",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "David Chen",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Arjun Reddy",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Fatima Khan",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Priya Nair",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "David Chen",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Rahul Sharma",
          "body": "Can we confirm if any config changes went live?"
        }
      ]
    },
    {
      "jira_id": "B2-4029",
      "business_unit": "B2",
      "ticket_type": "Task",
      "summary": "Search results inconsistent across regions",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Amit Verma",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "Fatima Khan",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "James Okafor",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Li Wei",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Arjun Reddy",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "James Okafor",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Fatima Khan",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Arjun Reddy",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Maria Garcia",
          "body": "Reproduced partially in staging."
        }
      ]
    },
    {
      "jira_id": "B2-4030",
      "business_unit": "B2",
      "ticket_type": "Task",
      "summary": "Notification delay in email service",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Fatima Khan",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "James Okafor",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "David Chen",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Fatima Khan",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Fatima Khan",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Li Wei",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Priya Nair",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Li Wei",
          "body": "Logs show timeout exceptions from downstream service."
        }
      ]
    },
    {
      "jira_id": "B2-4034",
      "business_unit": "B2",
      "ticket_type": "Story",
      "summary": "Search results inconsistent across regions",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Maria Garcia",
          "body": "Initial observation: DB latency increased after last deployment. Checking logs now."
        },
        {
          "author": "Maria Garcia",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Li Wei",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Fatima Khan",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Amit Verma",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Li Wei",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "David Chen",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Fatima Khan",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Fatima Khan",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Li Wei",
          "body": "Suggest rollback of last release."
        }
      ]
    },
    {
      "jira_id": "B2-4035",
      "business_unit": "B2",
      "ticket_type": "Task",
      "summary": "Search results inconsistent across regions",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Amit Verma",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Rahul Sharma",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Rahul Sharma",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Amit Verma",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Rahul Sharma",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Li Wei",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Priya Nair",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Rahul Sharma",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Amit Verma",
          "body": "Reproduced partially in staging."
        }
      ]
    },
    {
      "jira_id": "B2-4040",
      "business_unit": "B2",
      "ticket_type": "Task",
      "summary": "Search results inconsistent across regions",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Li Wei",
          "body": "Initial observation: DB latency increased after last deployment. Checking logs now."
        },
        {
          "author": "James Okafor",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Amit Verma",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Priya Nair",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Arjun Reddy",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Arjun Reddy",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Maria Garcia",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Li Wei",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Priya Nair",
          "body": "Root cause confirmed as timeout misconfiguration."
        }
      ]
    },
    {
      "jira_id": "B2-4043",
      "business_unit": "B2",
      "ticket_type": "Bug",
      "summary": "Notification delay in email service",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Maria Garcia",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "Arjun Reddy",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Maria Garcia",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Li Wei",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Amit Verma",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Rahul Sharma",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Arjun Reddy",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Li Wei",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "James Okafor",
          "body": "Fix deployed to staging, validating."
        }
      ]
    },
    {
      "jira_id": "B2-4047",
      "business_unit": "B2",
      "ticket_type": "Bug",
      "summary": "High latency in recommendation engine",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Amit Verma",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Arjun Reddy",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Fatima Khan",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Li Wei",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Maria Garcia",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Maria Garcia",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Arjun Reddy",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Rahul Sharma",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Maria Garcia",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Rahul Sharma",
          "body": "Temporary retry added to mitigate."
        }
      ]
    },
    {
      "jira_id": "B2-4048",
      "business_unit": "B2",
      "ticket_type": "Task",
      "summary": "Notification delay in email service",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Fatima Khan",
          "body": "Initial observation: Spike in 5xx errors from payment-service. Checking logs now."
        },
        {
          "author": "David Chen",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Amit Verma",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Amit Verma",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Amit Verma",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Li Wei",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Li Wei",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Fatima Khan",
          "body": "Metrics stabilizing post fix."
        }
      ]
    },
    {
      "jira_id": "B2-4053",
      "business_unit": "B2",
      "ticket_type": "Story",
      "summary": "High latency in recommendation engine",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "",
      "discussion": [
        {
          "author": "Priya Nair",
          "body": "Initial observation: DB latency increased after last deployment. Checking logs now."
        },
        {
          "author": "Arjun Reddy",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Amit Verma",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "James Okafor",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Li Wei",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Fatima Khan",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "David Chen",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Maria Garcia",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Arjun Reddy",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Priya Nair",
          "body": "Fix deployed to staging, validating."
        }
      ]
    },
    {
      "jira_id": "B2-4054",
      "business_unit": "B2",
      "ticket_type": "Task",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "",
      "discussion": [
        {
          "author": "Amit Verma",
          "body": "Initial observation: Spike in 5xx errors from payment-service. Checking logs now."
        },
        {
          "author": "Arjun Reddy",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "James Okafor",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "David Chen",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Fatima Khan",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Amit Verma",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Amit Verma",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Rahul Sharma",
          "body": "Reproduced partially in staging."
        }
      ]
    },
    {
      "jira_id": "B2-4056",
      "business_unit": "B2",
      "ticket_type": "Story",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "David Chen",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Li Wei",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Amit Verma",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "David Chen",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Maria Garcia",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Arjun Reddy",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "David Chen",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Maria Garcia",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "David Chen",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "David Chen",
          "body": "Suggest rollback of last release."
        }
      ]
    },
    {
      "jira_id": "B2-4059",
      "business_unit": "B2",
      "ticket_type": "Bug",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "David Chen",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "Fatima Khan",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Maria Garcia",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Arjun Reddy",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Amit Verma",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Fatima Khan",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Li Wei",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Li Wei",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Maria Garcia",
          "body": "Reproduced partially in staging."
        }
      ]
    },
    {
      "jira_id": "B2-4060",
      "business_unit": "B2",
      "ticket_type": "Bug",
      "summary": "High latency in recommendation engine",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Sneha Kulkarni",
          "body": "Initial observation: Users reporting intermittent login failures. Checking logs now."
        },
        {
          "author": "David Chen",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Li Wei",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Priya Nair",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "David Chen",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "James Okafor",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Rahul Sharma",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Priya Nair",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Li Wei",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Amit Verma",
          "body": "Temporary retry added to mitigate."
        }
      ]
    },
    {
      "jira_id": "B2-4061",
      "business_unit": "B2",
      "ticket_type": "Story",
      "summary": "High latency in recommendation engine",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "",
      "discussion": [
        {
          "author": "David Chen",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Rahul Sharma",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "James Okafor",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Maria Garcia",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Maria Garcia",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Amit Verma",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Rahul Sharma",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "David Chen",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Arjun Reddy",
          "body": "Looks like connection pool saturation."
        }
      ]
    },
    {
      "jira_id": "B2-4062",
      "business_unit": "B2",
      "ticket_type": "Task",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Arjun Reddy",
          "body": "Initial observation: Spike in 5xx errors from payment-service. Checking logs now."
        },
        {
          "author": "Priya Nair",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Amit Verma",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Rahul Sharma",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "James Okafor",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Rahul Sharma",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Amit Verma",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "James Okafor",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Metrics stabilizing post fix."
        }
      ]
    },
    {
      "jira_id": "B2-4064",
      "business_unit": "B2",
      "ticket_type": "Task",
      "summary": "High latency in recommendation engine",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "",
      "discussion": [
        {
          "author": "Sneha Kulkarni",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Li Wei",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "James Okafor",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Arjun Reddy",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "James Okafor",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Maria Garcia",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Amit Verma",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Maria Garcia",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Priya Nair",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Rahul Sharma",
          "body": "Suggest rollback of last release."
        }
      ]
    },
    {
      "jira_id": "B2-4069",
      "business_unit": "B2",
      "ticket_type": "Story",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "David Chen",
          "body": "Initial observation: DB latency increased after last deployment. Checking logs now."
        },
        {
          "author": "Rahul Sharma",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Rahul Sharma",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Rahul Sharma",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Amit Verma",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Rahul Sharma",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "James Okafor",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "David Chen",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Amit Verma",
          "body": "Reproduced partially in staging."
        }
      ]
    },
    {
      "jira_id": "B2-4071",
      "business_unit": "B2",
      "ticket_type": "Task",
      "summary": "Search results inconsistent across regions",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Fatima Khan",
          "body": "Initial observation: Users reporting intermittent login failures. Checking logs now."
        },
        {
          "author": "Fatima Khan",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Priya Nair",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Fatima Khan",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Priya Nair",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "David Chen",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Arjun Reddy",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Priya Nair",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Arjun Reddy",
          "body": "Suggest rollback of last release."
        }
      ]
    },
    {
      "jira_id": "B2-4074",
      "business_unit": "B2",
      "ticket_type": "Bug",
      "summary": "Notification delay in email service",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Sneha Kulkarni",
          "body": "Initial observation: DB latency increased after last deployment. Checking logs now."
        },
        {
          "author": "Rahul Sharma",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "David Chen",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Priya Nair",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Priya Nair",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Arjun Reddy",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Maria Garcia",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Maria Garcia",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "David Chen",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "David Chen",
          "body": "Metrics stabilizing post fix."
        }
      ]
    },
    {
      "jira_id": "B2-4075",
      "business_unit": "B2",
      "ticket_type": "Story",
      "summary": "Notification delay in email service",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Sneha Kulkarni",
          "body": "Initial observation: DB latency increased after last deployment. Checking logs now."
        },
        {
          "author": "Maria Garcia",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "David Chen",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Amit Verma",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Li Wei",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Priya Nair",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "David Chen",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Fatima Khan",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Li Wei",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "James Okafor",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        }
      ]
    },
    {
      "jira_id": "B2-4082",
      "business_unit": "B2",
      "ticket_type": "Bug",
      "summary": "Search results inconsistent across regions",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "",
      "discussion": [
        {
          "author": "Sneha Kulkarni",
          "body": "Initial observation: Cache miss ratio unusually high. Checking logs now."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Priya Nair",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Rahul Sharma",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "James Okafor",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Rahul Sharma",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "Li Wei",
          "body": "Suggest rollback of last release."
        },
        {
          "author": "David Chen",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Rahul Sharma",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "David Chen",
          "body": "Reproduced partially in staging."
        }
      ]
    },
    {
      "jira_id": "B2-4083",
      "business_unit": "B2",
      "ticket_type": "Story",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Resolved",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "Li Wei",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "David Chen",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Arjun Reddy",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Fatima Khan",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Rahul Sharma",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Maria Garcia",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Priya Nair",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Priya Nair",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Rahul Sharma",
          "body": "Can we confirm if any config changes went live?"
        }
      ]
    },
    {
      "jira_id": "B2-4087",
      "business_unit": "B2",
      "ticket_type": "Bug",
      "summary": "Payment failures during checkout",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "",
      "discussion": [
        {
          "author": "Sneha Kulkarni",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Rahul Sharma",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "James Okafor",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "Fatima Khan",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Li Wei",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "James Okafor",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Fatima Khan",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Priya Nair",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Li Wei",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Amit Verma",
          "body": "Logs show timeout exceptions from downstream service."
        }
      ]
    },
    {
      "jira_id": "B2-4088",
      "business_unit": "B2",
      "ticket_type": "Story",
      "summary": "Notification delay in email service",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Closed",
      "resolution": "Resolved via configuration fix and deployment after validation.",
      "discussion": [
        {
          "author": "David Chen",
          "body": "Initial observation: Users reporting intermittent login failures. Checking logs now."
        },
        {
          "author": "Li Wei",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Li Wei",
          "body": "Logs show timeout exceptions from downstream service."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "David Chen",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Amit Verma",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Fatima Khan",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Arjun Reddy",
          "body": "Temporary retry added to mitigate."
        },
        {
          "author": "Fatima Khan",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Arjun Reddy",
          "body": "Suggest rollback of last release."
        }
      ]
    },
    {
      "jira_id": "B2-4089",
      "business_unit": "B2",
      "ticket_type": "Bug",
      "summary": "User sessions dropping unexpectedly",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "In Progress",
      "resolution": "",
      "discussion": [
        {
          "author": "David Chen",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Fatima Khan",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "David Chen",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Sneha Kulkarni",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Maria Garcia",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Rahul Sharma",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Arjun Reddy",
          "body": "Can we confirm if any config changes went live?"
        },
        {
          "author": "Fatima Khan",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Li Wei",
          "body": "Looks like connection pool saturation."
        },
        {
          "author": "Fatima Khan",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        }
      ]
    },
    {
      "jira_id": "B2-4093",
      "business_unit": "B2",
      "ticket_type": "Story",
      "summary": "Search results inconsistent across regions",
      "description": "Production issue affecting users with supporting logs and monitoring anomalies.",
      "status": "Open",
      "resolution": "",
      "discussion": [
        {
          "author": "Li Wei",
          "body": "Initial observation: Third-party API timing out frequently. Checking logs now."
        },
        {
          "author": "Arjun Reddy",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Li Wei",
          "body": "Reproduced partially in staging."
        },
        {
          "author": "Priya Nair",
          "body": "Checked Grafana dashboards, latency increased post deployment."
        },
        {
          "author": "Rahul Sharma",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Li Wei",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Priya Nair",
          "body": "Metrics stabilizing post fix."
        },
        {
          "author": "David Chen",
          "body": "Fix deployed to staging, validating."
        },
        {
          "author": "Li Wei",
          "body": "Root cause confirmed as timeout misconfiguration."
        },
        {
          "author": "Amit Verma",
          "body": "Looks like connection pool saturation."
        }
      ]
    },
]

_INCIDENTS: list[dict] = [
    {
      "jira_id": "INC-400",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Applied hotfix to correct timeout configuration and redeployed service. Verified recovery via monitoring dashboards.",
      "related_tickets": [
        "B1-4071",
        "B1-4018"
      ]
    },
    {
      "jira_id": "INC-401",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Misconfigured timeout setting",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B1-4063",
        "B1-4007"
      ]
    },
    {
      "jira_id": "INC-402",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B1-4082",
        "B1-4060"
      ]
    },
    {
      "jira_id": "INC-403",
      "business_unit": "B1",
      "severity": "P3",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B1-4026",
        "B1-4031"
      ]
    },
    {
      "jira_id": "INC-404",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B1-4099",
        "B2-4067"
      ]
    },
    {
      "jira_id": "INC-405",
      "business_unit": "B1",
      "severity": "P1",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B2-4043",
        "B2-4008"
      ]
    },
    {
      "jira_id": "INC-406",
      "business_unit": "B2",
      "severity": "P2",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B1-4024",
        "B1-4042"
      ]
    },
    {
      "jira_id": "INC-407",
      "business_unit": "B1",
      "severity": "P3",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B2-4076",
        "B2-4082"
      ]
    },
    {
      "jira_id": "INC-408",
      "business_unit": "B1",
      "severity": "P1",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B1-4071",
        "B2-4081"
      ]
    },
    {
      "jira_id": "INC-409",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Misconfigured timeout setting",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Applied hotfix to correct timeout configuration and redeployed service. Verified recovery via monitoring dashboards.",
      "related_tickets": [
        "B1-4065",
        "B2-4046"
      ]
    },
    {
      "jira_id": "INC-410",
      "business_unit": "B1",
      "severity": "P3",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Code regression after deployment",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B1-4093",
        "B1-4057"
      ]
    },
    {
      "jira_id": "INC-411",
      "business_unit": "B1",
      "severity": "P1",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Misconfigured timeout setting",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Applied hotfix to correct timeout configuration and redeployed service. Verified recovery via monitoring dashboards.",
      "related_tickets": [
        "B2-4006",
        "B2-4088"
      ]
    },
    {
      "jira_id": "INC-412",
      "business_unit": "B1",
      "severity": "P3",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B2-4071",
        "B2-4055"
      ]
    },
    {
      "jira_id": "INC-413",
      "business_unit": "B1",
      "severity": "P1",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Applied hotfix to correct timeout configuration and redeployed service. Verified recovery via monitoring dashboards.",
      "related_tickets": [
        "B1-4059",
        "B2-4072"
      ]
    },
    {
      "jira_id": "INC-414",
      "business_unit": "B2",
      "severity": "P2",
      "title": "Checkout outage impacting transactions",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Code regression after deployment",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B2-4022",
        "B1-4060"
      ]
    },
    {
      "jira_id": "INC-415",
      "business_unit": "B2",
      "severity": "P3",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B1-4083",
        "B1-4091"
      ]
    },
    {
      "jira_id": "INC-416",
      "business_unit": "B2",
      "severity": "P3",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B1-4059",
        "B2-4099"
      ]
    },
    {
      "jira_id": "INC-417",
      "business_unit": "B2",
      "severity": "P2",
      "title": "Checkout outage impacting transactions",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Applied hotfix to correct timeout configuration and redeployed service. Verified recovery via monitoring dashboards.",
      "related_tickets": [
        "B2-4077",
        "B2-4028"
      ]
    },
    {
      "jira_id": "INC-418",
      "business_unit": "B2",
      "severity": "P3",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Misconfigured timeout setting",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B1-4000",
        "B2-4052"
      ]
    },
    {
      "jira_id": "INC-419",
      "business_unit": "B2",
      "severity": "P1",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Misconfigured timeout setting",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B1-4066",
        "B1-4070"
      ]
    },
    {
      "jira_id": "INC-420",
      "business_unit": "B2",
      "severity": "P2",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Code regression after deployment",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B2-4002",
        "B2-4050"
      ]
    },
    {
      "jira_id": "INC-421",
      "business_unit": "B2",
      "severity": "P3",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Code regression after deployment",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B1-4081",
        "B1-4061"
      ]
    },
    {
      "jira_id": "INC-422",
      "business_unit": "B1",
      "severity": "P3",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B1-4080",
        "B1-4006"
      ]
    },
    {
      "jira_id": "INC-423",
      "business_unit": "B1",
      "severity": "P1",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B1-4090",
        "B2-4091"
      ]
    },
    {
      "jira_id": "INC-424",
      "business_unit": "B2",
      "severity": "P1",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Applied hotfix to correct timeout configuration and redeployed service. Verified recovery via monitoring dashboards.",
      "related_tickets": [
        "B2-4024",
        "B1-4094"
      ]
    },
    {
      "jira_id": "INC-425",
      "business_unit": "B1",
      "severity": "P1",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Code regression after deployment",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B1-4085",
        "B1-4036"
      ]
    },
    {
      "jira_id": "INC-426",
      "business_unit": "B2",
      "severity": "P2",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Misconfigured timeout setting",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B1-4059",
        "B1-4030"
      ]
    },
    {
      "jira_id": "INC-427",
      "business_unit": "B1",
      "severity": "P1",
      "title": "Checkout outage impacting transactions",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Applied hotfix to correct timeout configuration and redeployed service. Verified recovery via monitoring dashboards.",
      "related_tickets": [
        "B2-4089",
        "B1-4011"
      ]
    },
    {
      "jira_id": "INC-428",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B1-4044",
        "B1-4046"
      ]
    },
    {
      "jira_id": "INC-429",
      "business_unit": "B1",
      "severity": "P3",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B2-4044",
        "B2-4075"
      ]
    },
    {
      "jira_id": "INC-430",
      "business_unit": "B1",
      "severity": "P1",
      "title": "Checkout outage impacting transactions",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B1-4076",
        "B2-4009"
      ]
    },
    {
      "jira_id": "INC-431",
      "business_unit": "B2",
      "severity": "P1",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B2-4098",
        "B1-4073"
      ]
    },
    {
      "jira_id": "INC-432",
      "business_unit": "B1",
      "severity": "P3",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B2-4050",
        "B1-4095"
      ]
    },
    {
      "jira_id": "INC-433",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B2-4058",
        "B1-4013"
      ]
    },
    {
      "jira_id": "INC-434",
      "business_unit": "B1",
      "severity": "P2",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B2-4099",
        "B2-4035"
      ]
    },
    {
      "jira_id": "INC-435",
      "business_unit": "B1",
      "severity": "P1",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B1-4099",
        "B1-4058"
      ]
    },
    {
      "jira_id": "INC-436",
      "business_unit": "B2",
      "severity": "P1",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B1-4066",
        "B1-4026"
      ]
    },
    {
      "jira_id": "INC-437",
      "business_unit": "B1",
      "severity": "P1",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Code regression after deployment",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B1-4037",
        "B1-4046"
      ]
    },
    {
      "jira_id": "INC-438",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B1-4003",
        "B1-4014"
      ]
    },
    {
      "jira_id": "INC-439",
      "business_unit": "B1",
      "severity": "P1",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B1-4081",
        "B1-4014"
      ]
    },
    {
      "jira_id": "INC-440",
      "business_unit": "B2",
      "severity": "P2",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Code regression after deployment",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B2-4064",
        "B1-4007"
      ]
    },
    {
      "jira_id": "INC-441",
      "business_unit": "B1",
      "severity": "P3",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B1-4037",
        "B2-4030"
      ]
    },
    {
      "jira_id": "INC-442",
      "business_unit": "B1",
      "severity": "P3",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B2-4090",
        "B2-4068"
      ]
    },
    {
      "jira_id": "INC-443",
      "business_unit": "B1",
      "severity": "P3",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B2-4031",
        "B1-4096"
      ]
    },
    {
      "jira_id": "INC-444",
      "business_unit": "B1",
      "severity": "P1",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B2-4012",
        "B2-4078"
      ]
    },
    {
      "jira_id": "INC-445",
      "business_unit": "B2",
      "severity": "P1",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B2-4031",
        "B2-4025"
      ]
    },
    {
      "jira_id": "INC-446",
      "business_unit": "B2",
      "severity": "P1",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B2-4049",
        "B1-4010"
      ]
    },
    {
      "jira_id": "INC-447",
      "business_unit": "B2",
      "severity": "P2",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Misconfigured timeout setting",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B1-4041",
        "B2-4021"
      ]
    },
    {
      "jira_id": "INC-448",
      "business_unit": "B2",
      "severity": "P1",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B1-4074",
        "B2-4043"
      ]
    },
    {
      "jira_id": "INC-449",
      "business_unit": "B2",
      "severity": "P2",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B1-4007",
        "B2-4021"
      ]
    },
    {
      "jira_id": "INC-450",
      "business_unit": "B2",
      "severity": "P1",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Applied hotfix to correct timeout configuration and redeployed service. Verified recovery via monitoring dashboards.",
      "related_tickets": [
        "B2-4089",
        "B2-4019"
      ]
    },
    {
      "jira_id": "INC-451",
      "business_unit": "B1",
      "severity": "P1",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B1-4020",
        "B1-4009"
      ]
    },
    {
      "jira_id": "INC-452",
      "business_unit": "B2",
      "severity": "P3",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B1-4079",
        "B2-4067"
      ]
    },
    {
      "jira_id": "INC-453",
      "business_unit": "B2",
      "severity": "P3",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B2-4044",
        "B2-4073"
      ]
    },
    {
      "jira_id": "INC-454",
      "business_unit": "B2",
      "severity": "P2",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B2-4042",
        "B2-4083"
      ]
    },
    {
      "jira_id": "INC-455",
      "business_unit": "B1",
      "severity": "P3",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B2-4026",
        "B1-4009"
      ]
    },
    {
      "jira_id": "INC-456",
      "business_unit": "B2",
      "severity": "P2",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Code regression after deployment",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B2-4052",
        "B1-4064"
      ]
    },
    {
      "jira_id": "INC-457",
      "business_unit": "B2",
      "severity": "P2",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Misconfigured timeout setting",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B2-4061",
        "B1-4012"
      ]
    },
    {
      "jira_id": "INC-458",
      "business_unit": "B1",
      "severity": "P1",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B1-4008",
        "B2-4097"
      ]
    },
    {
      "jira_id": "INC-459",
      "business_unit": "B2",
      "severity": "P2",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B2-4035",
        "B1-4054"
      ]
    },
    {
      "jira_id": "INC-460",
      "business_unit": "B2",
      "severity": "P2",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Code regression after deployment",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B1-4006",
        "B2-4036"
      ]
    },
    {
      "jira_id": "INC-461",
      "business_unit": "B1",
      "severity": "P3",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Misconfigured timeout setting",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B2-4002",
        "B1-4006"
      ]
    },
    {
      "jira_id": "INC-462",
      "business_unit": "B2",
      "severity": "P3",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B1-4021",
        "B2-4015"
      ]
    },
    {
      "jira_id": "INC-463",
      "business_unit": "B1",
      "severity": "P1",
      "title": "Checkout outage impacting transactions",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B1-4040",
        "B1-4046"
      ]
    },
    {
      "jira_id": "INC-464",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Checkout outage impacting transactions",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Misconfigured timeout setting",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Applied hotfix to correct timeout configuration and redeployed service. Verified recovery via monitoring dashboards.",
      "related_tickets": [
        "B1-4079",
        "B1-4047"
      ]
    },
    {
      "jira_id": "INC-465",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Checkout outage impacting transactions",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B1-4001",
        "B2-4049"
      ]
    },
    {
      "jira_id": "INC-466",
      "business_unit": "B1",
      "severity": "P1",
      "title": "Checkout outage impacting transactions",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B1-4078",
        "B2-4092"
      ]
    },
    {
      "jira_id": "INC-467",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Code regression after deployment",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Applied hotfix to correct timeout configuration and redeployed service. Verified recovery via monitoring dashboards.",
      "related_tickets": [
        "B1-4034",
        "B2-4011"
      ]
    },
    {
      "jira_id": "INC-468",
      "business_unit": "B1",
      "severity": "P3",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Misconfigured timeout setting",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B2-4068",
        "B1-4010"
      ]
    },
    {
      "jira_id": "INC-469",
      "business_unit": "B2",
      "severity": "P3",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Applied hotfix to correct timeout configuration and redeployed service. Verified recovery via monitoring dashboards.",
      "related_tickets": [
        "B2-4030",
        "B1-4044"
      ]
    },
    {
      "jira_id": "INC-470",
      "business_unit": "B2",
      "severity": "P3",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B2-4012",
        "B1-4008"
      ]
    },
    {
      "jira_id": "INC-471",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B1-4020",
        "B2-4030"
      ]
    },
    {
      "jira_id": "INC-472",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Checkout outage impacting transactions",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B2-4026",
        "B1-4095"
      ]
    },
    {
      "jira_id": "INC-473",
      "business_unit": "B1",
      "severity": "P1",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B2-4086",
        "B1-4022"
      ]
    },
    {
      "jira_id": "INC-474",
      "business_unit": "B1",
      "severity": "P3",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B1-4000",
        "B1-4085"
      ]
    },
    {
      "jira_id": "INC-475",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Checkout outage impacting transactions",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Applied hotfix to correct timeout configuration and redeployed service. Verified recovery via monitoring dashboards.",
      "related_tickets": [
        "B2-4046",
        "B2-4018"
      ]
    },
    {
      "jira_id": "INC-476",
      "business_unit": "B2",
      "severity": "P3",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B2-4078",
        "B1-4053"
      ]
    },
    {
      "jira_id": "INC-477",
      "business_unit": "B1",
      "severity": "P3",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B1-4030",
        "B2-4033"
      ]
    },
    {
      "jira_id": "INC-478",
      "business_unit": "B1",
      "severity": "P3",
      "title": "Checkout outage impacting transactions",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B1-4098",
        "B1-4062"
      ]
    },
    {
      "jira_id": "INC-479",
      "business_unit": "B1",
      "severity": "P3",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B1-4088",
        "B2-4059"
      ]
    },
    {
      "jira_id": "INC-480",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Code regression after deployment",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B1-4022",
        "B1-4013"
      ]
    },
    {
      "jira_id": "INC-481",
      "business_unit": "B2",
      "severity": "P3",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B2-4007",
        "B1-4037"
      ]
    },
    {
      "jira_id": "INC-482",
      "business_unit": "B2",
      "severity": "P1",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B2-4048",
        "B2-4045"
      ]
    },
    {
      "jira_id": "INC-483",
      "business_unit": "B2",
      "severity": "P3",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B2-4045",
        "B1-4057"
      ]
    },
    {
      "jira_id": "INC-484",
      "business_unit": "B2",
      "severity": "P3",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B2-4028",
        "B2-4098"
      ]
    },
    {
      "jira_id": "INC-485",
      "business_unit": "B2",
      "severity": "P1",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Misconfigured timeout setting",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B1-4078",
        "B1-4030"
      ]
    },
    {
      "jira_id": "INC-486",
      "business_unit": "B2",
      "severity": "P1",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B2-4047",
        "B1-4082"
      ]
    },
    {
      "jira_id": "INC-487",
      "business_unit": "B2",
      "severity": "P1",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B2-4081",
        "B2-4064"
      ]
    },
    {
      "jira_id": "INC-488",
      "business_unit": "B1",
      "severity": "P3",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Applied hotfix to correct timeout configuration and redeployed service. Verified recovery via monitoring dashboards.",
      "related_tickets": [
        "B1-4018",
        "B2-4035"
      ]
    },
    {
      "jira_id": "INC-489",
      "business_unit": "B1",
      "severity": "P1",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Code regression after deployment",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B1-4023",
        "B1-4058"
      ]
    },
    {
      "jira_id": "INC-490",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Applied hotfix to correct timeout configuration and redeployed service. Verified recovery via monitoring dashboards.",
      "related_tickets": [
        "B2-4092",
        "B1-4086"
      ]
    },
    {
      "jira_id": "INC-491",
      "business_unit": "B2",
      "severity": "P3",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Misconfigured timeout setting",
      "long_term_fix": "Improve load testing coverage.",
      "resolution": "Scaled up database connections and cleared stuck sessions. System performance returned to normal levels.",
      "related_tickets": [
        "B2-4028",
        "B2-4067"
      ]
    },
    {
      "jira_id": "INC-492",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Checkout outage impacting transactions",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Introduce circuit breaker pattern and retries.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B2-4014",
        "B1-4046"
      ]
    },
    {
      "jira_id": "INC-493",
      "business_unit": "B2",
      "severity": "P2",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Third-party API slowdown",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B2-4093",
        "B2-4053"
      ]
    },
    {
      "jira_id": "INC-494",
      "business_unit": "B2",
      "severity": "P3",
      "title": "Checkout outage impacting transactions",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Code regression after deployment",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B1-4036",
        "B2-4056"
      ]
    },
    {
      "jira_id": "INC-495",
      "business_unit": "B2",
      "severity": "P1",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Optimize database queries and indexing.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B2-4019",
        "B1-4077"
      ]
    },
    {
      "jira_id": "INC-496",
      "business_unit": "B2",
      "severity": "P1",
      "title": "Login service intermittent failures",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B2-4082",
        "B2-4006"
      ]
    },
    {
      "jira_id": "INC-497",
      "business_unit": "B2",
      "severity": "P3",
      "title": "Notification delays across system",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Service was stabilized by rolling back the last deployment and restarting affected pods. Traffic gradually restored after cache warm-up.",
      "related_tickets": [
        "B2-4051",
        "B1-4072"
      ]
    },
    {
      "jira_id": "INC-498",
      "business_unit": "B2",
      "severity": "P2",
      "title": "API latency spike across services",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Connection pool exhaustion",
      "long_term_fix": "Add config validation at startup.",
      "resolution": "Switched to fallback API provider and implemented temporary rate limiting to reduce load.",
      "related_tickets": [
        "B2-4060",
        "B2-4071"
      ]
    },
    {
      "jira_id": "INC-499",
      "business_unit": "B1",
      "severity": "P2",
      "title": "Search service degradation",
      "description": "Incident caused widespread impact requiring mitigation and RCA.",
      "root_cause": "Cache invalidation failure",
      "long_term_fix": "Enhance monitoring and alert thresholds.",
      "resolution": "Manually invalidated cache and triggered re-population. Confirmed consistency across services post fix.",
      "related_tickets": [
        "B1-4034",
        "B2-4046"
      ]
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
        print(
            "ERROR: DATABASE_URL is not set (use .env.local locally or env/secret on Cloud Run).",
            file=sys.stderr,
        )
        sys.exit(1)

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)

    async with pool.acquire() as conn:
        # ── Business units ─────────────────────────────────────────────────────
        await conn.execute(
            """
            INSERT INTO business_units (code, name) VALUES
                ('B1', 'Reservations Platform'),
                ('B2', 'Payments Platform'),
                ('Default', 'Unmapped / default')
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
