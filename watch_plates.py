import os
import json
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

import requests

BASE_URL = "https://api.kiwiplates.nz/api/combination/v2/{combination}/"
PARAMS = {"vehicleTypeId": "1", "leadId": "0", "email": ""}

STATE_FILE = "watch_state.json"
PLATES_FILE = "plates.txt"

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

TIMEOUT_SECONDS = 20
RETRIES = 3
REQUEST_DELAY_SECONDS = 0.25  # delay between plates (be polite)


def now_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def load_plates() -> List[str]:
    with open(PLATES_FILE, "r", encoding="utf-8") as f:
        plates = []
        for line in f:
            p = line.strip().upper().replace(" ", "")
            if p:
                plates.append(p)
    # dedupe & sort
    return sorted(set(plates))


def load_state() -> Dict[str, Any]:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def send_discord(message: str) -> None:
    if not DISCORD_WEBHOOK_URL:
        print("DISCORD_WEBHOOK_URL not set; skipping Discord alert.")
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as e:
        print(f"Discord post failed: {e}")


def fetch_plate_status(session: requests.Session, plate: str) -> Tuple[Optional[bool], str]:
    url = BASE_URL.format(combination=plate)

    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            r = session.get(url, params=PARAMS, timeout=TIMEOUT_SECONDS)
            r.raise_for_status()
            payload = r.json()

            data = (payload or {}).get("Data") or {}
            available = data.get("Available")
            reason = data.get("Reason") or ""

            if isinstance(available, bool):
                return available, reason
            return None, "PARSE_ERROR"

        except (requests.RequestException, ValueError) as e:
            last_err = e

    return None, f"ERROR: {last_err}"


def main():
    plates = load_plates()
    state = load_state()

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (kiwiplates-github-watcher; respectful polling)"
    })

    changes = []
    newly_available = []

    run_time = now_str()
    for plate in plates:
        available, reason = fetch_plate_status(session, plate)

        prev = state.get(plate, {})
        prev_avail = prev.get("available")
        prev_reason = prev.get("reason")

        state[plate] = {"available": available, "reason": reason, "last_seen": run_time}

        if (available != prev_avail) or (reason != prev_reason):
            changes.append(f"{plate}: {prev_avail}/{prev_reason} → {available}/{reason}")

        if available is True and prev_avail is not True:
            newly_available.append(f"{plate} ✅")

        # polite delay
        import time
        time.sleep(REQUEST_DELAY_SECONDS)

    save_state(state)

    if newly_available:
        msg = "🚨 **KiwiPlates now AVAILABLE:** " + ", ".join(newly_available)
        send_discord(msg)
        print(msg)

    # Optional: notify on any change (uncomment if you want noisy alerts)
    # if changes:
    #     send_discord("🔁 KiwiPlates changes:\n" + "\n".join(changes))

    print(f"Run complete at {run_time}. Checked {len(plates)} plates. New available: {len(newly_available)}")


if __name__ == "__main__":
    main()
