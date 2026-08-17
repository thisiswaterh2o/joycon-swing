"""
Home Run Derby WebSocket bridge — run LOCALLY on your PC.
Requires: pip install hidapi websockets

Tap ZR on the RIGHT Joy-Con to "step into the box" and call for a pitch.
The script then watches ~2.5s of motion from BOTH Joy-Cons, finds your
actual swing peak, and sends the result (power + timing offset) to any
connected browser client over WebSocket.

Run this first, then open derby_ui.html in your browser.
"""

import hid
import time
import struct
import threading
import asyncio
import json
import websockets

VENDOR_ID = 0x057E
PRODUCT_ID_L = 0x2006
PRODUCT_ID_R = 0x2007

ACCEL_SCALE = 0.000244
GYRO_SCALE = 0.0700

CAPTURE_WINDOW_SEC = 3.5  # max window — real swings resolve much faster via threshold detection below
BASE_SPEED_MPH = 75
BASE_IDEAL_CONTACT_MS = 1600   # ideal contact timing at the base (medium) pitch speed
current_ideal_contact_ms = BASE_IDEAL_CONTACT_MS  # updated live from the client's selected difficulty
SWING_THRESHOLD_DPS = 700  # gyro magnitude that counts as "a swing started" — raised to match your real swing floor
DETECTION_BLACKOUT_SEC = 0.35  # ignore motion right after the tap — lets you settle into stance without a false trigger
BURST_SETTLE_SEC = 0.35   # fallback finalize time if no clear decline is ever seen (safety net)
DECLINE_RATIO = 0.7       # a sample below this fraction of the current peak counts toward a decline
REQUIRED_DECLINE_SAMPLES = 2  # decline must be sustained this many samples in a row — filters out a brief mid-swing dip

def set_difficulty(speed_mph):
    global current_ideal_contact_ms
    speed_mph = max(30, min(120, float(speed_mph)))
    current_ideal_contact_ms = BASE_IDEAL_CONTACT_MS * (BASE_SPEED_MPH / speed_mph)
    print(f"Difficulty set: {speed_mph}mph -> ideal contact {current_ideal_contact_ms:.0f}ms")

samples_lock = threading.Lock()
current_window = []  # list of (t_ms_since_arm, gyro_mag, accel_mag)
armed_at = None
swing_triggered = False
burst_peak_gyro = 0.0
decline_count = 0
resolving = False
window_timer = None
burst_timer = None
connected_clients = set()
main_loop = None


def find_joycons():
    devices = hid.enumerate(VENDOR_ID)
    path_l, path_r = None, None
    for d in devices:
        if d["product_id"] == PRODUCT_ID_L:
            path_l = d["path"]
        elif d["product_id"] == PRODUCT_ID_R:
            path_r = d["path"]
    return path_l, path_r


def enable_imu(device):
    packet = bytearray(12)
    packet[0] = 1
    packet[10] = 0x40
    packet[11] = 0x01
    device.write(bytes(packet))
    time.sleep(0.05)
    packet = bytearray(12)
    packet[0] = 1
    packet[10] = 0x03
    packet[11] = 0x30
    device.write(bytes(packet))
    time.sleep(0.05)


def parse_right_buttons(data):
    return bool(data[3] & 0b10000000)


def parse_imu_frame(data, offset):
    ax, ay, az, gx, gy, gz = struct.unpack_from("<hhhhhh", data, offset)
    gyro_mag = (gx**2 + gy**2 + gz**2) ** 0.5 * GYRO_SCALE
    accel_mag = (ax**2 + ay**2 + az**2) ** 0.5 * ACCEL_SCALE
    return gyro_mag, accel_mag


def parse_imu_components(data, offset):
    """Signed, scaled gyro components (deg/sec). The browser integrates
    these into a live bat orientation so the on-screen bat mirrors the
    actual Joy-Con instead of playing a canned swing animation."""
    ax, ay, az, gx, gy, gz = struct.unpack_from("<hhhhhh", data, offset)
    return (
        gx * GYRO_SCALE, gy * GYRO_SCALE, gz * GYRO_SCALE,
        ax * ACCEL_SCALE, ay * ACCEL_SCALE, az * ACCEL_SCALE,
    )


def broadcast(message):
    if main_loop is None:
        return
    for ws in list(connected_clients):
        asyncio.run_coroutine_threadsafe(safe_send(ws, message), main_loop)


async def safe_send(ws, message):
    try:
        await ws.send(json.dumps(message))
    except Exception:
        pass


def close_window_and_score():
    """Called either once the swing burst has settled (no new peak for
    BURST_SETTLE_SEC), or as a timeout fallback if no swing was ever
    detected in the full window."""
    global armed_at, swing_triggered, burst_peak_gyro, decline_count, resolving, window_timer, burst_timer
    with samples_lock:
        if armed_at is None and not window_timer and not burst_timer and not current_window:
            return  # already finalized by another thread — nothing to do
        window = list(current_window)
        current_window.clear()
        armed_at = None
        swing_triggered = False
        burst_peak_gyro = 0.0
        decline_count = 0
        resolving = False
        if window_timer:
            window_timer.cancel()
            window_timer = None
        if burst_timer:
            burst_timer.cancel()
            burst_timer = None

    if not window:
        broadcast({"type": "result", "peak_gyro": 0, "offset_ms": 999999})
        return

    peak_t, peak_gyro, peak_accel = max(window, key=lambda s: s[1])
    offset_ms = peak_t - current_ideal_contact_ms
    broadcast({
        "type": "result",
        "peak_gyro": round(peak_gyro, 1),
        "peak_accel": round(peak_accel, 2),
        "offset_ms": round(offset_ms),
    })


def reader_thread(path, side, is_right):
    global armed_at, swing_triggered, burst_peak_gyro, decline_count, resolving, window_timer, burst_timer

    device = hid.device()
    device.open_path(path)
    device.set_nonblocking(False)
    enable_imu(device)

    last_keepalive = time.time()
    prev_zr = False

    while True:
      try:
        now = time.time()
        if now - last_keepalive > 1.0:
            keepalive = bytearray(10)
            keepalive[0] = 0x10
            device.write(bytes(keepalive))
            last_keepalive = now

        data = device.read(49, timeout_ms=1000)
        if not data:
            continue
        data = bytes(data)
        if data[0] != 0x30:
            continue

        now = time.time()

        if is_right:
            zr_held = parse_right_buttons(data)
            if zr_held and not prev_zr:
                # Double-tap guard: if a pitch window is already live, ignore
                # the tap entirely. Re-arming mid-flight used to blow away the
                # in-progress capture and desync the browser's ball animation.
                with samples_lock:
                    already_armed = armed_at is not None
                if already_armed:
                    prev_zr = zr_held
                    continue
                with samples_lock:
                    armed_at = now
                    swing_triggered = False
                    burst_peak_gyro = 0.0
                    decline_count = 0
                    resolving = False
                    current_window.clear()
                    if window_timer:
                        window_timer.cancel()
                    # Fallback timeout scales with the current pitch speed —
                    # a fixed window would leave a dead gap before the whiff
                    # registers on fast pitches, or cut off slow ones early.
                    fallback_sec = min(5.0, max(1.5, (current_ideal_contact_ms / 1000.0) * 2 + 0.3))
                    window_timer = threading.Timer(fallback_sec, close_window_and_score)
                    window_timer.daemon = True
                    window_timer.start()
                broadcast({"type": "pitch_start"})
            prev_zr = zr_held

        gyro_mag, accel_mag = parse_imu_frame(data, 13)

        # Live motion stream — the browser integrates these into the bat's
        # orientation every frame. Sent continuously (not just while armed)
        # so the bat tracks the controller during the stance too.
        if is_right and connected_clients:
            gx, gy, gz, axc, ayc, azc = parse_imu_components(data, 13)
            broadcast({
                "type": "motion",
                "gx": round(gx, 2), "gy": round(gy, 2), "gz": round(gz, 2),
                "ax": round(axc, 3), "ay": round(ayc, 3), "az": round(azc, 3),
            })

        should_finalize = False
        with samples_lock:
            if armed_at is not None:
                t_ms = (now - armed_at) * 1000
                current_window.append((t_ms, gyro_mag, accel_mag))

                # Threshold-triggered early resolution: once real swing motion
                # is detected (after the blackout period), keep extending the
                # confirm window every time a new (higher) peak shows up, so
                # we don't cut off mid-swing. Only finalize once settled.
                if t_ms > (DETECTION_BLACKOUT_SEC * 1000):
                    if gyro_mag > SWING_THRESHOLD_DPS or swing_triggered:
                        if not swing_triggered:
                            swing_triggered = True
                        if gyro_mag > burst_peak_gyro:
                            burst_peak_gyro = gyro_mag
                            decline_count = 0
                            if burst_timer:
                                burst_timer.cancel()
                            burst_timer = threading.Timer(BURST_SETTLE_SEC, close_window_and_score)
                            burst_timer.daemon = True
                            burst_timer.start()
                        elif (not resolving and burst_peak_gyro > SWING_THRESHOLD_DPS
                              and gyro_mag < burst_peak_gyro * DECLINE_RATIO):
                            # Real swings can have a brief mid-swing dip (e.g.
                            # during a grip/wrist transition) before the true
                            # peak — require the decline to hold for a couple
                            # of samples, not just one, before locking it in.
                            decline_count += 1
                            if decline_count >= REQUIRED_DECLINE_SAMPLES:
                                resolving = True
                                if burst_timer:
                                    burst_timer.cancel()
                                    burst_timer = None
                                should_finalize = True
                        else:
                            decline_count = 0

        if should_finalize:
            close_window_and_score()
      except Exception as e:
        print(f"[{side}] reader thread error (continuing): {e}")
        continue


async def ws_handler(websocket):
    connected_clients.add(websocket)
    print("Browser client connected.")
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("type") == "set_difficulty":
                    set_difficulty(data.get("speed_mph", BASE_SPEED_MPH))
            except Exception as e:
                print(f"Bad message from client (ignored): {e}")
    finally:
        connected_clients.discard(websocket)


async def main():
    global main_loop
    main_loop = asyncio.get_running_loop()

    path_l, path_r = find_joycons()
    if not path_l or not path_r:
        print("Need BOTH Joy-Cons paired and connected. Missing one or both.")
        return

    threading.Thread(target=reader_thread, args=(path_l, "L", False), daemon=True).start()
    threading.Thread(target=reader_thread, args=(path_r, "R", True), daemon=True).start()

    print("Joy-Cons connected. WebSocket server running on ws://localhost:8765")
    print("Open derby_ui.html in your browser, then tap ZR to call for a pitch.")

    async with websockets.serve(ws_handler, "localhost", 8765):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())