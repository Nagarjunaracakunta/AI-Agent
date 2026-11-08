# PostgreSQL Failover

Our production database is a PostgreSQL cluster managed by Patroni. The primary is `pg-prod-1` in ap-south-1a and the replica is `pg-prod-2` in ap-south-1b.

## Automatic failover

If the primary becomes unreachable, Patroni promotes the replica automatically. Failover normally completes in about 30 seconds. Our recovery time objective (RTO) is 2 minutes, and our recovery point objective (RPO) is 5 seconds or less, because the critical tables use synchronous replication.

Applications reconnect through PgBouncer. After a failover, restart PgBouncer on the application hosts if connections hang:

```
systemctl restart pgbouncer
```

## Checking replication lag

Before any planned switchover, confirm that the replica is caught up. Run this on the replica:

```
SELECT now() - pg_last_xact_replay_timestamp();
```

The result should be under 1 second. If lag is above 30 seconds, do not switch over without approval from the incident commander. The monitoring alert for high replica lag uses the error code `ERR_DB_5103`.

## Manual switchover

To switch over deliberately, for example during maintenance, run:

```
patronictl -c /etc/patroni.yml switchover --candidate pg-prod-2
```

Announce the switchover in #platform-ops first. Expect a brief interruption of a few seconds while connections move.

## Backups

A full backup runs every night at 02:00 IST. Write-ahead logs are archived to S3 continuously, which allows point-in-time recovery. Backups and archived logs are retained for 14 days.

We test a restore once a month. A backup that has never been restored is not considered a backup.

## When failover goes wrong

If neither node is healthy, declare a SEV1 and page the Data Platform on-call engineer. Do not delete the Patroni cluster state in etcd, and do not run `pg_resetwal`, without the incident commander's approval.
