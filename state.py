# state.py - the one object that is shared between the camera thread and
# the Flask (python library that runs the web server) thread,
# plus the reference to the ESP32 controller.
# Other files do "import state" and use state.shared / state.esp so that
# everybody sees the same objects.

import threading


##
# shared state
##
# Holds the latest jpeg frame, the latest gaze result and the calibration
# handshake between the web page and the camera thread.

class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.jpeg = None
        self.gaze = None
        self.camera_active = False
        self.calib_request = False
        self.calib_event = threading.Event()
        self.calib_result = None

    # Store the newest encoded frame.
    def set_jpeg(self, data):
        with self.lock:
            self.jpeg = data

    # Grab the newest encoded frame (or None if nothing yet).
    def get_jpeg(self):
        with self.lock:
            return self.jpeg


shared = SharedState()
esp = None   # set in web_iriun.py main()