from fastapi import FastAPI, Query, Request, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import psycopg2
from psycopg2.extras import RealDictCursor
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from sse_starlette.sse import EventSourceResponse
import httpx
import asyncio
import json
import os
import time
import uvicorn

app = FastAPI()

REQUEST_COUNTER = Counter("event_publisher_requests_total", "Total event publisher requests", ["user_id"])
REQUEST_ERROR_COUNTER = Counter("event_publisher_errors_total", "Total event publisher errors", ["user_id"])
REQUEST_LATENCY = Histogram("event_publisher_request_latency_seconds", "Latency for event publisher requests (seconds)", ["user_id"])


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method == "OPTIONS":
            # Return a response to satisfy the preflight check
            origin = request.headers.get("origin", "*")
            headers = {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                "Access-Control-Allow-Headers": "Authorization,Content-Type",
            }
            return Response(status_code=204, headers=headers)
        
        response = await call_next(request)
        origin = request.headers.get("origin")
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type"
        return response

app.add_middleware(DynamicCORSMiddleware)

# Load database credentials from environment
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
POSTGRES_DB = os.getenv("POSTGRES_DB", "events_db")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")

# Function to connect to PostgreSQL
def get_db_connection():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        dbname=POSTGRES_DB,
        cursor_factory=RealDictCursor
    )

# API route to fetch events with optional filters
@app.get("/events")
def get_events(
    user_id: str = Query(None),
    event_type: str = Query(None),
    limit: int = Query(100, gt=0, le=1000),
    offset: int = Query(0, ge=0)
):
    REQUEST_COUNTER.labels(user_id=user_id).inc()
    start_time = time.time()
    query = "SELECT * FROM events WHERE TRUE"
    params = []

    if user_id is not None:
        query += " AND user_id = %s"
        params.append(user_id)

    if event_type is not None:
        query += " AND event_type = %s"
        params.append(event_type)

    query += " ORDER BY processed_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(query, tuple(params))
        events = cursor.fetchall()
        cursor.close()
        conn.close()
        return events
    except Exception as e:
        REQUEST_ERROR_COUNTER.labels(user_id=user_id).inc()
        return {"error": str(e)}
    finally:
        elapsed = time.time() - start_time
        REQUEST_LATENCY.labels(user_id=user_id).observe(elapsed)

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

async def fetch_prometheus_metric(metric: str, user_id: int):
    query = f'{metric}{{user_id="{user_id}"}}'
    url = f"{PROMETHEUS_URL}/api/v1/query"
    async with httpx.AsyncClient() as client:
        res = await client.get(url, params={"query": query})
        data = res.json()
        result = data.get("data", {}).get("result", [])
        return result[0]["value"][1] if result else None

@app.get("/events/stream")
async def stream(request: Request):
    async def event_generator():
        user_id = 123  # Or pull from query param
        event_id = 1

        while True:
            if await request.is_disconnected():
                break

            latency = await fetch_prometheus_metric("total_latency", user_id)
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

            event = {
                "id": event_id,
                "user_id": user_id,
                "event_type": "metrics_update",
                "processed_at": timestamp,
                "total_latency": float(latency or 0),
            }

            yield {
                "event": "metrics",
                "data": json.dumps(event),
            }

            event_id += 1
            await asyncio.sleep(3)

    return EventSourceResponse(event_generator())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))  # Fallback for local dev
    uvicorn.run(app, host="0.0.0.0", port=port)