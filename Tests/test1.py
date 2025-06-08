import json
import time
import requests

EVENT_FILE = "./Tests/dataset.json"
ENDPOINT = "http://event_receiver:8000/event" 

def main():
    with open(EVENT_FILE, "r") as f:
        events = json.load(f)

    for event in events:
        response = requests.post(ENDPOINT, json=event)
        print(f"Sent: {event}")
        print(f"Response: {response.status_code} - {response.text}")

if __name__ == "__main__":
    main()
