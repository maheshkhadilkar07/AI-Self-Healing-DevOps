"""Kafka-style event router (block diagram: 'Kafka Event Router').

Every telemetry item and every AI decision flows through named topics:
  telemetry.metrics | telemetry.logs | telemetry.traces | telemetry.events
  ai.anomalies | ai.diagnosis | automation.plan | automation.actions
  verification.results | learning.kb | policy.updates
Default backend is in-process (zero install). If KAFKA_BOOTSTRAP is set and `kafka-python`
is installed, every message is ALSO produced to a real Kafka topic (not tested against a live broker here).
"""
import json, os
from collections import defaultdict, deque


class EventRouter:
    def __init__(self):
        self.subs = defaultdict(list)
        self.counts = defaultdict(int)
        self.recent = defaultdict(lambda: deque(maxlen=20))
        self.total = 0
        self.producer = None
        bootstrap = os.environ.get("KAFKA_BOOTSTRAP")
        if bootstrap:
            try:
                from kafka import KafkaProducer
                self.producer = KafkaProducer(bootstrap_servers=bootstrap,
                                              value_serializer=lambda v: json.dumps(v, default=str).encode())
            except Exception as e:
                print("Kafka unavailable, using in-process router:", e)

    @property
    def backend(self):
        return "kafka+in-process" if self.producer else "in-process"

    def subscribe(self, topic, fn):
        self.subs[topic].append(fn)

    def publish(self, topic, msg):
        self.total += 1
        self.counts[topic] += 1
        self.recent[topic].append(msg)
        if self.producer:
            try: self.producer.send(topic, msg)
            except Exception: pass
        for fn in self.subs.get(topic, []):
            fn(msg)
