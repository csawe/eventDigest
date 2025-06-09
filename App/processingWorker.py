# src/App/processingWorker.py

import redis
import json
import time
import os
from prometheus_client import start_http_server, Counter, Histogram, Gauge
import threading

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

QUEUE_IN = "events_preprocessed"
QUEUE_OUT = "events_processed"

def connect_redis():
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

def process_event(event_data: dict) -> dict:
    # Example transformation: Add a new field
    event_data["processed_at"] = time.time()
    return event_data

PROCESSING_COUNTER = Counter("processing_worker_events_processed_total", "Total events processed", ["user_id"])
ERROR_COUNTER = Counter("processing_worker_errors_total", "Total processing errors")
PROCESSING_LATENCY = Histogram("processing_worker_processing_latency_seconds", "Processing time per event", ["user_id"])

QUEUE_DEQUEUE_COUNTER = Counter("processing_worker_dequeue_total", "Total events dequeued from events_preprocessed")
QUEUE_IN_LENGTH_GAUGE = Gauge("processing_worker_queue_in_length", "Current length of events_preprocessed queue")

QUEUE_ENQUEUE_COUNTER = Counter("processing_worker_enqueue_total", "Total events enqueued to events_processed")
QUEUE_OUT_LENGTH_GAUGE = Gauge("processing_worker_queue_out_length", "Current length of events_processed queue")

def start_metrics_server():
    start_http_server(8080)

threading.Thread(target=start_metrics_server, daemon=True).start()

def main():
    r = connect_redis()
    print("Processing worker started. Waiting for events...")

    while True:
        try:
            # BLPOP blocks until something is available
            _, raw_event = r.blpop(QUEUE_IN)

            QUEUE_DEQUEUE_COUNTER.inc()
            queue_in_length = r.llen(QUEUE_IN)
            QUEUE_IN_LENGTH_GAUGE.set(queue_in_length)

            print("Received event:", raw_event)
            start_time = time.time()

            event = json.loads(raw_event)
            processed_event = process_event(event)

            r.rpush(QUEUE_OUT, json.dumps(processed_event))
            QUEUE_ENQUEUE_COUNTER.inc()

            queue_out_length = r.llen(QUEUE_OUT)
            QUEUE_OUT_LENGTH_GAUGE.set(queue_out_length)

            print("Event processed and pushed to:", QUEUE_OUT)
            PROCESSING_COUNTER.labels(user_id=str(event.get("user_id", "unknown"))).inc()
            PROCESSING_LATENCY.labels(user_id=str(event.get("user_id", "unknown"))).observe(time.time() - start_time)

        except (json.JSONDecodeError, redis.RedisError) as e:
            print("Error processing event:", e)
            ERROR_COUNTER.inc()
            time.sleep(1)

if __name__ == "__main__":
    main()
