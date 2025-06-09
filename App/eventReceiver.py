# src/App/eventReceiver.py

import redis
import os
import json
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import time
import uvicorn

load_dotenv()

redis_host = os.getenv("REDIS_HOST", "localhost")
redis_port = int(os.getenv("REDIS_PORT", 6379))
redis_queue = os.getenv("REDIS_QUEUE", "events_preprocessed")

r = redis.Redis(host=redis_host, port=redis_port, db=0)

REQUEST_COUNTER = Counter("event_receiver_requests_total", "Total event receiver requests", ["user_id"])
ERROR_COUNTER = Counter("event_receiver_errors_total", "Total event receiver errors", ["user_id"])

QUEUE_ENQUEUE_COUNTER = Counter("event_receiver_enqueue_total", "Total number of events enqueued to Redis")
QUEUE_LENGTH_GAUGE = Gauge("event_receiver_queue_length", "Current length of the Redis events_preprocessed queue")

# def start_metrics_server():
#     start_http_server(8002)  # Prometheus metrics port

# threading.Thread(target=start_metrics_server, daemon=True).start()

def enqueue_event(data: dict) -> dict:
    if "event_type" not in data:
        ERROR_COUNTER.labels(user_id=str(data.get("user_id", "unknown"))).inc()
        return {"error": "Missing required fields"}
    r.rpush(redis_queue, json.dumps(data))
    QUEUE_ENQUEUE_COUNTER.inc()
    # Update queue length gauge
    queue_length = r.llen(redis_queue)
    QUEUE_LENGTH_GAUGE.set(queue_length)
    return {"status": "queued", "queue": redis_queue, "queue_length": queue_length}

app = FastAPI()

@app.post("/event")
async def receive_event(request: Request):
    try:
        data = await request.json()
        REQUEST_COUNTER.labels(user_id=str(data.get("user_id", "unknown"))).inc()
        data["received_at"] = time.time()
        result = enqueue_event(data)
        return result
    except Exception as e:
        ERROR_COUNTER.labels(user_id=str(data.get("user_id", "unknown"))).inc()
        return {"error": str(e)}
    
@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))  # Fallback for local dev
    uvicorn.run(app, host="0.0.0.0", port=port)