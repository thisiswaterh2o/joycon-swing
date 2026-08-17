"""
Entry point. Two modes for now:

  python main.py --raw     -> just stream raw accel/gyro to console
                               (use this FIRST to confirm connection + eyeball data)
  python main.py --game    -> run the pitch/swing/score loop

Start with --raw. Nothing else matters until that works.
"""

import argparse
import time

import config
from api_client import post_session
from joycon_reader import JoyConReader
from swing_detector import SwingDetector, accel_magnitude, gyro_magnitude

# Sport-specific game loops live under games/<sport>/game_loop.py.
# Only baseball is implemented right now — ping_pong and tennis are
# stubbed placeholders for when it's time to build them out.
SPORTS = {
    "baseball": "games.baseball.game_loop",
}


def load_game_loop(sport: str):
    import importlib

    module_path = SPORTS.get(sport)
    if module_path is None:
        raise ValueError(f"Unknown or unbuilt sport: {sport!r}. Available: {list(SPORTS)}")
    module = importlib.import_module(module_path)
    return module.GameLoop


def run_raw(reader: JoyConReader) -> None:
    print("Streaming raw accel/gyro. Ctrl+C to stop.")
    print("Sit the Joy-Con still for a few seconds first to see the resting baseline.\n")
    for sample in reader.stream():
        print(
            f"t={sample.timestamp:.3f}  "
            f"accel=({sample.accel_x:5d},{sample.accel_y:5d},{sample.accel_z:5d}) "
            f"mag={accel_magnitude(sample):8.1f}  "
            f"gyro=({sample.gyro_x:5d},{sample.gyro_y:5d},{sample.gyro_z:5d}) "
            f"mag={gyro_magnitude(sample):8.1f}  "
            f"batt={sample.battery_level}"
        )


def run_game(reader: JoyConReader, sport: str = "baseball", num_pitches: int = 5) -> None:
    GameLoop = load_game_loop(sport)
    detector = SwingDetector()
    loop = GameLoop()

    print(f"Starting {num_pitches}-pitch session. Swing when it feels right!\n")

    for i in range(num_pitches):
        delay = loop.start_pitch()
        print(f"Pitch {i + 1}/{num_pitches} incoming in {delay:.2f}s...")

        swing_event = None
        pitch_deadline = time.monotonic() + delay + (loop.CONTACT_WINDOW_MS / 1000)

        while time.monotonic() < pitch_deadline and swing_event is None:
            sample = reader.read()
            swing_event = detector.process(sample)
            time.sleep(config.POLL_INTERVAL_SEC)

        result = loop.resolve_pitch(swing_event)
        print(f"  -> {result.contact_quality.name} (offset {result.timing_offset_ms:+.0f}ms)\n")

    print(f"Session complete. Score: {loop.session.score()} / {num_pitches * 3}")
    post_session(loop.session)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", action="store_true", help="Stream raw IMU data only")
    parser.add_argument("--game", action="store_true", help="Run the pitch/swing loop")
    parser.add_argument("--sport", default="baseball", choices=list(SPORTS.keys()))
    parser.add_argument("--pitches", type=int, default=5)
    args = parser.parse_args()

    reader = JoyConReader()
    print("Connecting to Joy-Con...")
    reader.connect()
    print("Connected.\n")

    if args.game:
        run_game(reader, args.sport, args.pitches)
    else:
        run_raw(reader)


if __name__ == "__main__":
    main()
