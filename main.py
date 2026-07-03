# Stella Kaper 2026 - Bachelor Project Creative Technology
# main program, run this file to start everything.
#
# This code allows eye tracking through a phone camera. The phone and the
# computer should both have the Iriun Webcam application installed, so the
# phone shows up on the computer as a normal webcam. The program watches
# the camera and works out whether the person in front of it is looking
# straight into the lens. When eye contact is held for one and a half
# seconds, it tells an ESP32 over WiFi to run a motor for twenty seconds.
# There is also a small web page (served from this computer through Flask library)
# with buttons for running the motor manually, changing the speed, calibrating and an
# emergency stop, plus a live view of the camera. Calibration is done by
# simply looking into the camera and pressing the calibrate button, either
# on the web page or the physical button on the ESP32.
#
# The code also drives a calibration button and a set of status LEDs on the ESP32
# (eye contact, calibrated/uncalibrated, motor active, and two LEDs for the 0.5 s and
# 1.5 s eye-contact holds). These LEDs and button were not incorporated in the final
# prototype, but the code was left in place in case of future use.
#
# Credits:
#   - Gaze/eye tracking approach based on Jason Orlosky's open source
#     eye tracking code (https://github.com/JEOresearch/EyeTracker)
#   - Google's face landmark AI mesh model (face_landmarker.task)
#   - Google MediaPipe for the face landmark detection itself
#
# The project is split over a few files:
#   settings.py       - all settings and tuning values
#   state.py          - state shared between the threads
#   esp_controller.py - talking to the ESP32 (motor, LEDs, buttons)
#   gaze_math.py      - head angle, iris position, gaze estimation
#   camera.py         - webcam, MediaPipe, drawing, main camera loop
#   web_app.py        - the Flask control page and its endpoints
#
# Needs: pip install flask opencv-python mediapipe numpy

import cv2
import mediapipe as mp
import os
import threading

import settings
import state
from esp import EspController
from camera import camera_worker
from web_server import app


##
# main
##
# Wire everything together: ESP controller, camera thread, Flask thread
# and a small quit listener on stdin.

# Called when the physical calibrate button is pressed on the ESP32.
def request_calibration():
    with state.shared.lock:
        state.shared.calib_event.clear()
        state.shared.calib_result = None
        state.shared.calib_request = True
    print("Calibration requested by physical button.")


# Start all the threads and keep the main thread alive until quit.
def main():
    print("OpenCV:", cv2.__version__)
    print("MediaPipe:", mp.__version__)
    print("Starting gaze web server (Iriun webcam, single-state ESP control)...")
    print(f"  Camera index: {settings.camera_index}")
    print(f"  Web page:     http://<computer-ip>:{settings.web_port}/")
    print(f"  ESP32:        {settings.esp32_host}:{settings.esp32_port}")
    print("  Hold eye contact 1.5 s -> motor runs 20 s (when calibrated).")
    print("  Quit: type 'q' + Enter, or press 'q' in the preview window.")
    print()

    state.esp = EspController(settings.esp32_host, settings.esp32_port,
                              settings.esp32_http_timeout_s)
    state.esp.on_calib_button = request_calibration

    worker = threading.Thread(target=camera_worker, daemon=True)
    worker.start()

    stop_event = threading.Event()

    # Listens on stdin so typing 'q' + Enter also quits the program.
    def quit_listener():
        try:
            for line in __import__("sys").stdin:
                if line.strip().lower() == "q":
                    break
        except Exception:
            return
        stop_event.set()

    threading.Thread(target=quit_listener, daemon=True).start()

    flask_thread = threading.Thread(
        target=lambda: app.run(host=settings.web_host, port=settings.web_port,
                               threaded=True, debug=False, use_reloader=False),
        daemon=True)
    flask_thread.start()

    try:
        while not stop_event.wait(0.2):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        print("Shutting down...")
        if state.esp is not None:
            state.esp.emergency_stop()
        os._exit(0)


if __name__ == "__main__":
    main()