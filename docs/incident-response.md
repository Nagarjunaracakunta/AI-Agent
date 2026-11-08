# Incident Response

This document defines how we classify, escalate and communicate during production incidents. Alerts reach on-call engineers through PagerDuty, in the service named `acme-platform`.

## Severity levels

**SEV1** means a full outage, or any risk to customer data. The first responder must acknowledge within 5 minutes. Page both the primary and secondary on-call engineers, and appoint an incident commander immediately.

**SEV2** means a major feature is degraded but the product is still usable. Respond within 15 minutes.

**SEV3** means a minor issue with a workaround. Respond within 30 minutes during business hours. No paging is needed outside business hours.

If you are unsure between two levels, choose the higher one. You can always downgrade later.

## Escalation

If the primary on-call engineer does not acknowledge a page within 10 minutes, PagerDuty escalates to the secondary on-call engineer. If the secondary does not acknowledge within a further 10 minutes, the page escalates to the engineering manager.

## Roles

For SEV1 and SEV2 incidents, assign three roles:

- **Incident commander:** coordinates the response and makes decisions. Does not debug.
- **Ops lead:** investigates and applies fixes.
- **Communications lead:** updates the status page and stakeholders.

## Communication

Open a dedicated Slack channel named `#inc-YYYYMMDD-short-name`, for example `#inc-20260312-checkout-errors`.

For SEV1 and SEV2, the status page must be updated within 20 minutes of the incident starting. During a SEV1, post an update at least every 30 minutes, even if the update is "no change".

## After the incident

Hold a blameless postmortem within 5 business days of any SEV1 or SEV2 incident. The postmortem must list a timeline, the root cause, and action items with named owners and due dates. We focus on how the system allowed the failure, not on who made the mistake.
