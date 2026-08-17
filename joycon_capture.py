"""
Dual Joy-Con (gen 1) IMU capture — run this LOCALLY on your PC.
Requires: pip install hidapi

Tap ZR on the RIGHT Joy-Con to arm a capture window; both Joy-Cons log
data during that window so you can cross-reference L/R motion.

Ctrl+C to stop.
"""

import hid
import time
import struct
import csv
import os
import threading

VENDOR_ID = 0x057E
PRODUCT_ID_L = 0x2006
PRODUCT_ID_R = 0x2007

ACCEL_SCALE = 0.000244  # g per LSB
GYRO_SCALE = 0.0700     # deg/s per LSB

CAPTURE_WINDOW_SEC = 2.5

# Shared state between the two reader threads
armed_until = 0.0
armed_lock = threading.Lock()
csv_lock = threading.Lock()


def find_joycons():
    """Returns (path_left, path_right) — either may be None if not found."""
    devices = hid.enumerate(VENDOR_ID)
    path_l, path_r = None, None
    for d in devices:
        if d["product_id"] == PRODUCT_ID_L:
            path_l = d["path"]
            print(f"Found LEFT Joy-Con: {d['product_string']}")
        elif d["product_id"] == PRODUCT_ID_R:
            path_r = d["path"]
            print(f"Found RIGHT Joy-Con: {d['product_string']}")
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
    """Byte 3: bit0=Y bit1=X bit2=B bit3=A bit4=SR bit5=SL bit6=R bit7=ZR"""
    return bool(data[3] & 0b10000000)


def parse_imu_frame(data, offset):
    ax, ay, az, gx, gy, gz = struct.unpack_from("<hhhhhh", data, offset)
    return {
        "accel": (ax * ACCEL_SCALE, ay * ACCEL_SCALE, az * ACCEL_SCALE),
        "gyro": (gx * GYRO_SCALE, gy * GYRO_SCALE, gz * GYRO_SCALE),
    }


def reader_thread(path, side, writer, is_right):
    global armed_until

    device = hid.device()
    device.open_path(path)
    device.set_nonblocking(False)
    enable_imu(device)
    print(f"{side} Joy-Con streaming...")

    last_keepalive = time.time()
    prev_zr = False

    while True:
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

        # Only the RIGHT Joy-Con's ZR arms the shared capture window
        if is_right:
            zr_held = parse_right_buttons(data)
            if zr_held and not prev_zr:
                with armed_lock:
                    armed_until = now + CAPTURE_WINDOW_SEC
                print(">>> ARMED — swing now <<<")
            prev_zr = zr_held

        with armed_lock:
            swing = now < armed_until

        frame = parse_imu_frame(data, 13)
        ax, ay, az = frame["accel"]
        gx, gy, gz = frame["gyro"]

        with csv_lock:
            writer.writerow([now, side, ax, ay, az, gx, gy, gz, int(swing)])


def main():
    path_l, path_r = find_joycons()
    if not path_l or not path_r:
        print("Need BOTH Joy-Cons paired and connected. Missing one or both.")
        return

    csv_path = "joycon_dual_swings.csv"
    write_header = not os.path.exists(csv_path)
    csv_file = open(csv_path, "a", newline="")
    writer = csv.writer(csv_file)
    if write_header:
        writer.writerow(
            ["timestamp", "side", "ax", "ay", "az", "gx", "gy", "gz", "swing"]
        )

    print(f"Logging to {csv_path}.")
    print(f"Tap ZR on the RIGHT Joy-Con — arms a {CAPTURE_WINDOW_SEC}s window for BOTH controllers.")
    print("Ctrl+C to stop.\n")

    t_left = threading.Thread(target=reader_thread, args=(path_l, "L", writer, False), daemon=True)
    t_right = threading.Thread(target=reader_thread, args=(path_r, "R", writer, True), daemon=True)
    t_left.start()
    t_right.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        csv_file.close()


if __name__ == "__main__":
    main()