"""
Central config: thresholds, polling rate, API target.
Nothing here should require touching other files to tune during testing.
"""

# --- Connection ---
POLL_INTERVAL_SEC = 1 / 60  # pyjoycon polls internally; this is our read loop cadence
USE_LEFT_JOYCON = False      # swing hand — flip if a friend is left-handed / holds L

# --- Swing detection (placeholders — tune once we have real data tomorrow) ---
# Raw accel units from pyjoycon are NOT in g by default; log raw values first
# and calibrate a REST baseline before trusting these.
ACCEL_MAGNITUDE_SWING_THRESHOLD = 3000   # placeholder, raw units
GYRO_MAGNITUDE_SWING_THRESHOLD = 1500    # placeholder, raw units
SWING_WINDOW_MS = 350                    # max duration a single swing gesture spans
REFRACTORY_MS = 500                      # min time between two detected swings

# --- Orientation fusion (complementary filter) ---
COMPLEMENTARY_FILTER_ALPHA = 0.98  # weight toward gyro (vs accel) for orientation estimate

# --- API ---
API_BASE_URL = "http://localhost:5000"  # placeholder until Flask endpoint exists
SWING_SESSION_ENDPOINT = "/scoutin/swing-sessions"
API_KEY = None  # per-user token, set via env var later

# --- Debug ---
LOG_RAW_PACKETS = True
