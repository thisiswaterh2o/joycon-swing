"""
Posts session results to the Flask backend. Stub for now — endpoint
doesn't exist yet on the Scoutin side. Kept isolated so swapping this
out (or later replacing the whole local app with the JS/WebHID port)
doesn't touch detection or game logic.
"""

import json
from dataclasses import asdict
from typing import Optional

import config
from game_loop import GameSession


def build_payload(session: GameSession, user_token: Optional[str] = None) -> dict:
    return {
        "user_token": user_token or config.API_KEY,
        "pitches_thrown": session.pitches_thrown,
        "score": session.score(),
        "results": [
            {
                "contact_quality": r.contact_quality.name,
                "timing_offset_ms": r.timing_offset_ms,
                "peak_accel_magnitude": r.swing.peak_accel_magnitude if r.swing else None,
                "peak_gyro_magnitude": r.swing.peak_gyro_magnitude if r.swing else None,
                "estimated_angle_deg": r.swing.estimated_angle_deg if r.swing else None,
            }
            for r in session.results
        ],
    }


def post_session(session: GameSession, user_token: Optional[str] = None) -> None:
    payload = build_payload(session, user_token)

    try:
        import requests
    except ImportError:
        print("[api_client] 'requests' not installed — printing payload instead:")
        print(json.dumps(payload, indent=2))
        return

    url = config.API_BASE_URL + config.SWING_SESSION_ENDPOINT
    try:
        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
        print(f"[api_client] Session posted OK -> {url}")
    except Exception as e:
        print(f"[api_client] Failed to post session (endpoint likely not built yet): {e}")
        print(json.dumps(payload, indent=2))
