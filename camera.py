# camera.py - the camera side of the project.
# Opens the Iriun webcam, runs every frame through Google's MediaPipe face
# landmark model, draws the overlay, feeds the gaze result to the ESP32
# and publishes a jpeg for the web page. Also handles calibration requests
# coming from the web page or the physical button.

import cv2
import numpy as np
import mediapipe as mp
import math
import os
import time

from mediapipe.tasks import python
from mediapipe.tasks.python import vision

import settings
import state
from gaze_math import (FaceAngleState, estimate_face_angle,
                       calculate_iris_position_data, estimate_gaze)


##
# basic helpers
##
# Frame cropping and the placeholder image for a missing webcam.

# Center-crop the frame to the wanted aspect ratio and resize it.
def crop_to_aspect_ratio(image, width=640, height=480):
    h, w = image.shape[:2]
    desired_ratio = width / height
    current_ratio = w / h
    if current_ratio > desired_ratio:
        new_w = int(desired_ratio * h)
        offset = (w - new_w) // 2
        cropped = image[:, offset:offset + new_w]
    else:
        new_h = int(w / desired_ratio)
        offset = (h - new_h) // 2
        cropped = image[offset:offset + new_h, :]
    return cv2.resize(cropped, (width, height))


# Build a black placeholder frame with an error message when no webcam opens.
def make_missing_camera_frame(reason):
    frame = np.zeros((settings.camera_height, settings.camera_width, 3), dtype=np.uint8)
    for i, line in enumerate(["Webcam", "NOT FOUND", reason,
                              "Check camera_index and that Iriun is running."]):
        cv2.putText(frame, line, (25, 60 + i * 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, settings.text_color, 1, lineType=cv2.LINE_AA)
    return frame


##
# mediapipe / camera
##
# Loading Google's landmark model and opening the Iriun webcam.

# Load the face_landmarker.task model into a MediaPipe FaceLandmarker.
def create_face_landmarker():
    if not os.path.exists(settings.model_path):
        raise FileNotFoundError(
            f"Could not find {settings.model_path}. Place face_landmarker.task next to this script.")
    options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=settings.model_path),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1, output_face_blendshapes=False,
        output_facial_transformation_matrixes=False,
    )
    return vision.FaceLandmarker.create_from_options(options)


# Open the webcam with the configured backend, resolution and fps.
def open_webcam():
    if settings.camera_backend == "dshow":
        cap = cv2.VideoCapture(settings.camera_index, cv2.CAP_DSHOW)
    elif settings.camera_backend == "v4l2":
        cap = cv2.VideoCapture(settings.camera_index, cv2.CAP_V4L2)
    else:
        cap = cv2.VideoCapture(settings.camera_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.camera_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.camera_height)
    cap.set(cv2.CAP_PROP_FPS, settings.camera_fps)
    time.sleep(settings.camera_warmup_seconds)
    return cap


# Read one BGR frame from the capture, or None if it failed.
def read_frame_bgr(cap):
    ok, frame = cap.read()
    if not ok or frame is None:
        return None
    return frame


##
# drawing
##
# Text and shapes drawn on top of the camera frame.

# Draw the eye contour as a thin polyline.
def draw_eye_outline(frame, eye_points):
    if eye_points:
        cv2.polylines(frame, [np.array(eye_points, dtype=np.int32)],
                      True, settings.eye_line_color, 1, lineType=cv2.LINE_AA)


# Draw a circle around the iris based on its landmark points.
def draw_iris_circle(frame, iris_points):
    if not iris_points:
        return
    cx = int(np.mean([p[0] for p in iris_points]))
    cy = int(np.mean([p[1] for p in iris_points]))
    dists = [math.sqrt((p[0]-cx)**2 + (p[1]-cy)**2) for p in iris_points]
    r = int(np.clip(max(dists) * 0.9, 4, 50))
    cv2.circle(frame, (cx, cy), r, settings.iris_circle_color, 1, lineType=cv2.LINE_AA)


# Write the head angles and the gaze verdict onto the frame.
def draw_gaze_overlay(output, face_angle, gaze):
    if face_angle is None:
        cv2.putText(output, "No face detected", (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, settings.text_color, 2, lineType=cv2.LINE_AA)
        return
    y = 30
    for label, value in [("Yaw", face_angle["yaw_scale"]),
                         ("Pitch", face_angle["pitch_scale"]),
                         ("Roll", face_angle["roll_scale"])]:
        cv2.putText(output, f"{label}: {value:+.2f}", (20, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, settings.angle_text_color, 1, lineType=cv2.LINE_AA)
        y += 22
    if gaze is not None:
        color = settings.good_gaze_color if gaze["looking_into_camera"] else settings.bad_gaze_color
        score_pct = int(round(gaze["direct_score"] * 100))
        cv2.putText(output, f"{gaze['gaze_direction']}  {score_pct}%", (20, y + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, lineType=cv2.LINE_AA)


# Run one frame through the whole pipeline: landmarks, head angle, iris
# position, gaze estimate and the overlay drawing.
def process_frame(frame, landmarker, timestamp_ms, angle_state):
    frame = crop_to_aspect_ratio(frame, settings.camera_width, settings.camera_height)
    output = frame.copy()
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = landmarker.detect_for_video(mp_image, timestamp_ms)

    if not result.face_landmarks:
        draw_gaze_overlay(output, None, None)
        return output, None, None, None

    lm = result.face_landmarks[0]
    h, w = frame.shape[:2]
    face_angle = estimate_face_angle(lm, w, h, settings.camera_num)
    iris_data = calculate_iris_position_data(lm, w, h)
    gaze = estimate_gaze(settings.camera_num, face_angle, iris_data, angle_state)

    if settings.show_eye_outline and iris_data is not None:
        draw_eye_outline(output, iris_data["left_eye_points"])
        draw_eye_outline(output, iris_data["right_eye_points"])
    if settings.show_iris_circle and iris_data is not None:
        draw_iris_circle(output, iris_data["left_iris_points"])
        draw_iris_circle(output, iris_data["right_iris_points"])

    draw_gaze_overlay(output, face_angle, gaze)
    return output, face_angle, iris_data, gaze


##
# camera worker
##
# The main camera thread: grabs frames, runs the pipeline, feeds the ESP32,
# handles calibration requests and publishes the jpeg for the web page.

# Runs forever in its own thread until the window is closed with 'q'.
def camera_worker():
    print(f"Opening webcam index {settings.camera_index} ...")
    cap = open_webcam()
    if cap is None or not cap.isOpened():
        reason = f"index {settings.camera_index} would not open"
        print(f"Webcam: {reason}. Try a different camera_index (0/1/2).")
        ok, buf = cv2.imencode(".jpg", make_missing_camera_frame(reason))
        if ok:
            state.shared.set_jpeg(buf.tobytes())
        return

    with state.shared.lock:
        state.shared.camera_active = True

    landmarker = create_face_landmarker()
    angle_state = FaceAngleState("Webcam")
    calib_buf = None
    start_time = time.monotonic()
    last_print = 0.0
    latest_gaze = None
    last_ts = -1

    try:
        while True:
            now = time.monotonic()
            frame = read_frame_bgr(cap)
            if frame is None:
                time.sleep(0.01)
                continue
            if settings.mirror_camera:
                frame = cv2.flip(frame, 1)

            ts = int((now - start_time) * 1000)
            if ts <= last_ts:
                ts = last_ts + 1
            last_ts = ts

            output_frame, face_angle, iris_data, gaze = process_frame(
                frame, landmarker, ts, angle_state)

            looking = bool(gaze and gaze.get("looking_into_camera"))
            if state.esp is not None:
                state.esp.set_looking(looking)

            if gaze is not None:
                latest_gaze = gaze
                with state.shared.lock:
                    state.shared.gaze = {
                        "gaze_direction": gaze["gaze_direction"],
                        "looking_into_camera": gaze["looking_into_camera"],
                        "direct_score": round(gaze["direct_score"], 2),
                    }

            # ---- calibration request (web button OR physical button) ----
            with state.shared.lock:
                want_calib = state.shared.calib_request
            if want_calib and calib_buf is None:
                calib_buf = {"xs": [], "vs": []}
                print("Calibration started.")
            if calib_buf is not None and gaze is not None:
                calib_buf["xs"].append(gaze["x_residual"])
                calib_buf["vs"].append(gaze["v_residual"])
                if len(calib_buf["xs"]) >= settings.calib_frames:
                    angle_state.x_offset += float(np.mean(calib_buf["xs"]))
                    angle_state.y_offset += float(np.mean(calib_buf["vs"]))
                    result = {"ok": True, "frames": len(calib_buf["xs"]),
                              "x_offset": round(angle_state.x_offset, 4),
                              "y_offset": round(angle_state.y_offset, 4)}
                    with state.shared.lock:
                        state.shared.calib_request = False
                        state.shared.calib_result = result
                        state.shared.calib_event.set()
                    calib_buf = None
                    if state.esp is not None:
                        state.esp.mark_calibrated()
                    print(f"Calibrated. x_offset={result['x_offset']:+.4f}, "
                          f"y_offset={result['y_offset']:+.4f}")

            # ---- publish jpeg ----
            ok, buf = cv2.imencode(".jpg", output_frame,
                                   [cv2.IMWRITE_JPEG_QUALITY, settings.jpeg_quality])
            if ok:
                state.shared.set_jpeg(buf.tobytes())

            # ---- local preview window ----
            if settings.show_local_window:
                cv2.imshow("Gaze (Iriun)", output_frame)
                if (cv2.waitKey(1) & 0xFF) == ord("q"):
                    break

            if now - last_print >= settings.print_interval_seconds:
                if latest_gaze:
                    st = state.esp.status() if state.esp else {}
                    print(f"{latest_gaze['gaze_direction']} "
                          f"score={latest_gaze['direct_score']:.2f} "
                          f"motor={'ON' if st.get('motor',{}).get('spinning') else 'off'} "
                          f"esp={'up' if st.get('connected') else 'down'}")
                last_print = now

    finally:
        try:
            cap.release()
        except Exception:
            pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        print("Camera worker stopped.")