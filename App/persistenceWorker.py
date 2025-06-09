# src/persistenceWorker.py

import redis
import json
import time
import os
import psycopg2
from datetime import datetime
from prometheus_client import start_http_server, Counter, Histogram, Gauge
import threading

# Load config from env
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_QUEUE = "events_processed"

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", 5432))
PG_DB = os.getenv("POSTGRES_DB", "events_db")
PG_USER = os.getenv("POSTGRES_USER", "postgres")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")

# Prometheus metrics
STORING_COUNTER = Counter("persistence_worker_events_stored_total", "Total events stored in the database", ["user_id"])
ERROR_COUNTER = Counter("persistence_worker_errors_total", "Total errors during persistence", ["user_id"])
STORING_LATENCY = Histogram("persistence_worker_storing_latency_seconds", "Time taken to store an event", ["user_id"])

QUEUE_DEQUEUE_COUNTER = Counter("persistence_worker_dequeue_total", "Total events dequeued from events_processed")
QUEUE_LENGTH_GAUGE = Gauge("persistence_worker_queue_length", "Current length of events_processed queue")

END_TO_END_LATENCY = Histogram("end_to_end_event_latency_seconds", "Time from event reception to DB persistence", ["user_id"])

def start_metrics_server():
    port = int(os.environ.get("PORT", 8080))  
    start_http_server(port)

threading.Thread(target=start_metrics_server, daemon=True).start()

def connect_redis():
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

def connect_postgres(retries=5, delay=2):
    for attempt in range(retries):
        try:
            return psycopg2.connect(
                dbname=PG_DB,
                user=PG_USER,
                password=PG_PASSWORD,
                host=PG_HOST,
                port=PG_PORT,
            )
        except psycopg2.OperationalError as e:
            print(f"[DB ERROR] Attempt {attempt+1}: {e}")
            time.sleep(delay)
    raise Exception("Could not connect to Postgres after several retries.")

def save_to_db(conn, event: dict):
    with conn.cursor() as cur:
        processed_at = datetime.fromtimestamp(event.get("processed_at"))
        total_latency = time.time() - event.get("received_at")
        print("Total latency for event:", total_latency)
        cur.execute("""
            INSERT INTO events (user_id, event_type, processed_at, total_latency)
            VALUES (%s, %s, %s, %s)
        """, (event["user_id"], event["event_type"], processed_at, total_latency))
        conn.commit()
        print("Event saved to database:", event)

def main():
    r = connect_redis()
    db = connect_postgres()
    print("Persistence worker started. Waiting for processed events...")

    while True:
        try:
            _, raw_event = r.blpop(REDIS_QUEUE)
            QUEUE_DEQUEUE_COUNTER.inc()
            QUEUE_LENGTH_GAUGE.set(r.llen(REDIS_QUEUE))

            print("Received event:", raw_event)
            event = json.loads(raw_event)

            start_time = time.time()
            save_to_db(db, event)
            STORING_LATENCY.labels(user_id=str(event.get("user_id", "unknown"))).observe(time.time() - start_time)

            print("Event persisted successfully.")
            STORING_COUNTER.labels(user_id=str(event.get("user_id", "unknown"))).inc()

            print("Persisting:", event)
            total_latency = time.time() - event["received_at"]
            print(f"Total end-to-end latency: {total_latency} seconds")
            END_TO_END_LATENCY.labels(user_id=str(event.get("user_id", "unknown"))).observe(total_latency)

        except (json.JSONDecodeError, redis.RedisError, psycopg2.Error) as e:
            print("Error in persistence worker:", e)
            ERROR_COUNTER.inc()
            time.sleep(2)

if __name__ == "__main__":
    main()
