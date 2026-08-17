"""
Thin wrapper around pyjoycon: handles connection and yields raw
accel/gyro samples with timestamps. Nothing swing-specific lives here —
this is just "give me clean data."
"""

import time
from dataclasses import dataclass

import config


@dataclass
class ImuSample:
    timestamp: float  # time.monotonic() seconds
    accel_x: int
    accel_y: int
    accel_z: int
    gyro_x: int
    gyro_y: int
    gyro_z: int
    battery_level: int


class JoyConReader:
    """
    Wraps pyjoycon.JoyCon. Connect once, then call read() in a loop
    to get the latest ImuSample.
    """

    def __init__(self, use_left: bool = config.USE_LEFT_JOYCON):
        self.use_left = use_left
        self._joycon = None

    def connect(self) -> None:
        # Deferred import so the rest of the project can be explored/tested
        # without pyjoycon + hidapi installed yet.
        from pyjoycon import JoyCon, get_L_id, get_R_id

        joycon_id = get_L_id() if self.use_left else get_R_id()

        if joycon_id[0] is None:
            raise RuntimeError(
                "No Joy-Con found. Check it's paired in Windows Bluetooth "
                "settings and powered on (press any button to wake it)."
            )

        self._joycon = JoyCon(*joycon_id)

    def read(self) -> ImuSample:
        if self._joycon is None:
            raise RuntimeError("Call connect() before read().")

        status = self._joycon.get_status()
        accel = status["accel"]
        gyro = status["gyro"]
        battery = status["battery"]["level"]

        return ImuSample(
            timestamp=time.monotonic(),
            accel_x=accel["x"],
            accel_y=accel["y"],
            accel_z=accel["z"],
            gyro_x=gyro["x"],
            gyro_y=gyro["y"],
            gyro_z=gyro["z"],
            battery_level=battery,
        )

    def stream(self):
        """Generator: yields ImuSample forever at config.POLL_INTERVAL_SEC cadence."""
        while True:
            yield self.read()
            time.sleep(config.POLL_INTERVAL_SEC)
