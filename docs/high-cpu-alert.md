# High CPU Alert

The `HighCPU` alert fires when CPU usage stays above 85% for 10 minutes on any production node. This runbook explains how to investigate it.

## Step 1: Look at the processes

On the affected node, list the busiest processes:

```
top -o %CPU
```

Note whether one process dominates or whether the load is spread across many.

## Step 2: Check for a recent deploy

Open the Deploy Health dashboard and check whether a deploy finished in the last hour. If CPU rose right after a deploy, treat the deploy as the likely cause and consider a rollback.

## Step 3: Check autoscaling

Services scale with a Horizontal Pod Autoscaler. It keeps a minimum of 4 pods and a maximum of 20 pods, and it scales up when average CPU exceeds 70%. If the service is already at 20 pods, autoscaling cannot help and the cause must be found and fixed.

## Known causes

The most common cause is the nightly `report-generator` job, which starts at 01:00 IST and can use a lot of CPU. If it is still running and starving other workloads, delete the job:

```
kubectl delete job report-generator-<id> -n prod
```

Tell the Reporting team afterwards so that they can rerun it off-peak.

## Capturing evidence before restarting

Before restarting a node or a process, capture a CPU profile so that the root cause can be found later:

```
perf record -F 99 -g -p <pid> -- sleep 30
```

Attach the resulting file to the incident ticket. Do not restart nodes before capturing it.

## Escalation

Raise the incident to SEV2 if CPU stays above 95% for 20 minutes and the p95 latency is above 1.5 seconds.
