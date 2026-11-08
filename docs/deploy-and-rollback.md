# Deployments and Rollbacks

This runbook describes how the Platform team ships changes to production and how to undo them. All deployments go through `deployctl`, our internal deployment CLI. Never run `kubectl apply` against production by hand.

## Deployment windows

Production deployments are allowed Monday to Thursday, between 10:00 and 16:00 IST. We observe a deploy freeze on Fridays, weekends and public holidays, because fewer engineers are available to respond if something breaks.

A hotfix during a freeze is possible, but it needs written approval from the on-call engineering manager. Post the approval in the #deploys Slack channel before you start.

Rollbacks are never blocked by the freeze. You may roll back at any time, on any day, without approval.

## Approvals

A normal change needs one reviewer. Any change that includes a database migration needs two reviewers, and one of them must be a member of the Data Platform team.

## Canary rollout

Every production deploy is a canary rollout with three stages:

1. 5% of traffic for 15 minutes.
2. 50% of traffic for 15 minutes.
3. 100% of traffic.

During the canary the pipeline watches two guardrails. If the error rate rises above 2%, or the p95 latency rises above 800 ms, the deploy is rolled back automatically and the pipeline posts the reason in #deploys.

Check the "Deploy Health" dashboard in Grafana during every stage, even if the guardrails are green.

## Manual rollback

To roll back a service to the previous version, run:

```
deployctl rollback --service <name> --to previous
```

A rollback normally takes about 3 minutes. If `deployctl` itself is unavailable, use the Kubernetes fallback:

```
kubectl rollout undo deployment/<name> -n prod
```

After any rollback, confirm that the error rate has returned to normal on the Deploy Health dashboard, and open a ticket in the PLAT project describing why the rollback was needed.

## Database migrations

Migrations must be backward compatible with the previous application version, so that a rollback of the application does not break the database. Never drop a column in the same release that stops using it. Drop it in a later release, after the old version is gone.
