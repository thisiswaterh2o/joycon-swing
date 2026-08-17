# joycon-swing

Python prototype for swing detection using a Nintendo Switch Joy-Con.
Standalone repo — reads raw IMU data over Bluetooth, detects swings,
runs a simple pitch/hit loop, and (later) POSTs results to the main
Scoutin/Whatcha Doin Flask app.

This is the prototyping ground. Once swing detection is tuned here,
the logic gets ported to JS/WebHID so friends can use it straight from
the browser with no install.

## Setup

```bash
pip install joycon-python hidapi
```

On Windows, `hidapi` sometimes needs `hid` instead if `cython-hidapi`
can't find the Joy-Con:

```bash
pip install hid
```

### Pairing

1. Put dongle in a USB port (extension cable recommended — see project notes).
2. Windows Settings > Bluetooth & devices > Add device.
3. Hold the small sync button on the Joy-Con (between SL/SR rails) until
   the LEDs animate.
4. Pair like any BT device.

### Run

```bash
python main.py
```

## Structure

Core engine — sport-agnostic, shared by every sport:
- `joycon_reader.py` — wraps pyjoycon, handles connection + polling loop
- `swing_detector.py` — threshold/orientation-fusion logic, emits generic `SwingEvent`
- `api_client.py` — POSTs session results to the Flask backend (stub for now)
- `config.py` — thresholds, constants, API URL
- `main.py` — entry point, picks a sport via `--sport`, wires everything together

Per-sport game loops (own scoring/timing rules, same engine underneath):
- `games/baseball/game_loop.py` — pitch timing, contact quality, scoring (built)
- `games/ping_pong/game_loop.py` — rally timing + spin (placeholder, not built)
- `games/tennis/game_loop.py` — forehand/backhand/serve classification (placeholder, not built)

Run a sport with `python main.py --game --sport baseball`. New sports just need
a `GameLoop` class dropped into `games/<sport>/game_loop.py` and a line added
to `SPORTS` in `main.py` — the detection/connection layer never changes.

## Status

- [ ] Confirm Joy-Con pairs and `get_status()` returns live data
- [ ] Log raw accel/gyro to console, eyeball sample rate
- [ ] Establish resting/noise baseline (Joy-Con sitting still)
- [ ] First-pass swing threshold (peak accel magnitude)
- [ ] Orientation fusion (complementary filter) for swing angle
- [ ] Wire into basic pitch/hit loop
- [ ] api_client stub -> real endpoint once Flask side exists
