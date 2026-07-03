# esp_controller.py - everything that talks to the ESP32 over WiFi.
# One EspController object owns all the output state (motor, LEDs) and
# sends it in a single /state request every settings.esp32_poll_s.
# Note: the LED outputs were not incorporated in the final prototype,
# but they are still sent so the code is ready if they come back.

import threading
import time
import urllib.request

import settings


##
# esp32 controller (single /state endpoint)
##
# Owns all ESP32 output state and sends it in one /state request every
# esp32_poll_s. Reads back the physical button presses from the reply.

class EspController:
    # Set up state, remember the ESP address and start the background loop.
    def __init__(self, host, port, timeout):
        self._base = f"http://{host}:{port}"
        self._timeout = timeout
        self._lock = threading.Lock()

        # gaze input + timing
        self._looking = False
        self._look_start = None
        self._last_look = 0.0

        # motor bursts
        self._burst_until = 0.0       # gaze-triggered 20 s run
        self._timed_until = 0.0       # manual 10/20/60 s button
        self._speed = settings.speed_normal

        # gates / latches
        self._estop = False
        self._calibrated = False
        self._run_without_calib = False
        self._pending_clear = False

        # connection
        self._connected = False
        self._last_ok = 0.0
        self._rssi = 0

        # callback when the physical calibrate button is pressed
        self.on_calib_button = None

        threading.Thread(target=self._loop, daemon=True).start()
        print(f"[ESP] controller started -> {self._base}")

    # Called by the camera loop every frame: is the user making eye contact right now?
    def set_looking(self, looking: bool):
        with self._lock:
            self._looking = bool(looking)

    # The motor is only allowed to run after calibration (or with the override on).
    def _allowed(self):
        return self._calibrated or self._run_without_calib

    # Start a manual timed run from the web buttons (10/20/60 s).
    def start_timed(self, seconds: float):
        with self._lock:
            if self._estop:
                return False, "emergency stop is active"
            if not self._allowed():
                return False, "not calibrated (enable 'Run without calibration')"
            self._timed_until = time.monotonic() + float(seconds)
            return True, None

    # Switch between the normal and fast PWM speed.
    def set_speed_fast(self, fast: bool):
        with self._lock:
            self._speed = settings.speed_fast if fast else settings.speed_normal

    # Toggle the "run without calibration" override from the web page.
    def set_run_without_calib(self, on: bool):
        with self._lock:
            self._run_without_calib = bool(on)

    # Called after a calibration finished so the motor gate opens.
    def mark_calibrated(self):
        with self._lock:
            self._calibrated = True

    # Kill everything: latch the e-stop and cancel any running bursts.
    def emergency_stop(self):
        with self._lock:
            self._estop = True
            self._burst_until = 0.0
            self._timed_until = 0.0

    # Release the e-stop again (also tells the ESP32 to clear its own latch).
    def clear_estop(self):
        with self._lock:
            self._estop = False
            self._pending_clear = True

    # Snapshot of the current state for the /status endpoint and prints.
    def status(self):
        with self._lock:
            now = time.monotonic()
            burst = now < self._burst_until
            timed = now < self._timed_until
            motor = (burst or timed) and not self._estop and self._allowed()
            left = max(self._burst_until, self._timed_until) - now
            return {
                "connected": self._connected,
                "calibrated": self._calibrated,
                "run_without_calib": self._run_without_calib,
                "estopped": self._estop,
                "speed_mode": "fast" if self._speed >= settings.speed_fast else "normal",
                "rssi": self._rssi,
                "motor": {"spinning": motor, "timed_left": round(left, 1) if motor else 0.0},
            }

    # Turn the current internal state into the set of /state query parameters.
    # Also handles the eye-contact hold timing and firing the 20 s burst.
    def _compute_outputs(self):
        now = time.monotonic()

        if self._looking:
            self._last_look = now
            if self._look_start is None:
                self._look_start = now
        else:
            if self._look_start is not None and (now - self._last_look) > settings.look_grace_s:
                self._look_start = None

        held = (now - self._look_start) if self._look_start is not None else 0.0

        # trigger a fresh 20 s burst when contact crosses 1.5 s (and allowed)
        if (held >= settings.eye_trigger_s and not self._estop and self._allowed()
                and now >= self._burst_until):
            self._burst_until = now + settings.eye_run_s

        burst = now < self._burst_until
        timed = now < self._timed_until
        motor = (burst or timed) and not self._estop and self._allowed()

        eye = self._looking                 # instant built-in LED
        if burst:                           # during a gaze burst keep both eye LEDs on
            e05 = True
            e15 = True
        else:
            e05 = held >= settings.eye_led1_s
            e15 = held >= settings.eye_led2_s

        clear = self._pending_clear
        self._pending_clear = False

        return {
            "motor": 1 if motor else 0,
            "speed": self._speed if motor else 0,
            "eye": 1 if eye else 0,
            "cal": 1 if self._calibrated else 0,
            "e05": 1 if e05 else 0,
            "e15": 1 if e15 else 0,
            "clear": 1 if clear else 0,
        }

    # Background thread: send /state to the ESP32 forever and read the reply
    # (rssi + physical e-stop / calibrate button events).
    def _loop(self):
        while True:
            with self._lock:
                params = self._compute_outputs()
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{self._base}/state?{qs}"
            try:
                with urllib.request.urlopen(url, timeout=self._timeout) as r:
                    import json
                    data = json.loads(r.read().decode("utf-8"))
                now = time.monotonic()
                with self._lock:
                    self._connected = True
                    self._last_ok = now
                    self._rssi = int(data.get("rssi", 0))
                    if int(data.get("estop_event", 0)) or int(data.get("estopped", 0)):
                        self._estop = True
                    fire_calib = int(data.get("calib_event", 0)) == 1
                if fire_calib and self.on_calib_button:
                    self.on_calib_button()
            except Exception:
                with self._lock:
                    if time.monotonic() - self._last_ok > 3.0:
                        self._connected = False
            time.sleep(settings.esp32_poll_s)