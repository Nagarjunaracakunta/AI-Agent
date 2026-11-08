# Kafka Consumer Lag

The `ConsumerLagHigh` alert fires when the consumer group lag on the `orders` topic stays above 50,000 messages for 5 minutes. The consumer group is `orders-processor`.

## Checking the lag

Describe the consumer group to see lag per partition:

```
kafka-consumer-groups.sh --bootstrap-server kafka-prod:9092 --describe --group orders-processor
```

If the lag is concentrated in a single partition, suspect a poison message. If it is spread evenly, suspect a shortage of consumers or a slow downstream dependency.

## Scaling consumers

The `orders` topic has 12 partitions. Each partition can be read by only one consumer in the group at a time, so more than 12 consumers gives no benefit. To scale up:

```
kubectl scale deployment/orders-processor --replicas=8
```

Do not exceed 12 replicas.

## Poison messages and the dead-letter queue

A message that fails processing is retried up to 5 times. After the fifth failure it is moved to the dead-letter topic `orders.dlq`, so that it no longer blocks the partition.

Once the underlying bug is fixed, replay the dead-lettered messages at a controlled rate:

```
dlq-replay --topic orders.dlq --rate 100
```

The rate is in messages per second.

## Offsets

Never reset consumer offsets in production without approval from the incident commander. Resetting offsets can cause orders to be processed twice or skipped.

## Retention

Messages on the `orders` topic are retained for 7 days. If lag is so large that the consumers will not catch up within 7 days, messages will be lost, so escalate to SEV2.
