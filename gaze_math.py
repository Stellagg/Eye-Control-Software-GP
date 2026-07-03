# gaze_math.py - all the math behind the eye tracking.
# Head angle from six face landmarks (solvePnP), iris position inside the
# eye opening, and the final decision whether someone is looking into the
# camera. Based on Jason Orlosky's open source eye tracking code.

import cv2
import numpy as np
import math

import settings


##
# state
##
# Small per-camera object that keeps the calibration offsets and the
# smoothed residuals between frames.

class FaceAngleState:
    def __init__(self, camera_label):
        self.camera_label = camera_label
        self.x_offset = 0.0
        self.y_offset = 0.0
        self.res_x_ema = None
        self.res_v_ema = None


##
# basic helpers
##
# Small utility functions used all over the place.

# Turn a list of landmark indexes into pixel (x, y) points.
def get_landmark_points(face_landmarks, idxs, w, h):
    pts = []
    for idx in idxs:
        if idx >= len(face_landmarks):
            continue
        lm = face_landmarks[idx]
        pts.append((int(lm.x * w), int(lm.y * h)))
    return pts


# Clamp a value into the 0..1 range.
def clamp01(v):
    return float(np.clip(v, 0.0, 1.0))


##
# head angle (solvePnP)
##
# Estimate yaw/pitch/roll of the head from six face landmarks.

# Convert a rotation matrix into pitch/yaw/roll in degrees.
def rotation_matrix_to_euler_angles(R):
    sy = math.sqrt(R[0, 0]**2 + R[1, 0]**2)
    if sy >= 1e-6:
        pitch = math.atan2(R[2, 1], R[2, 2])
        yaw = math.atan2(-R[2, 0], sy)
        roll = math.atan2(R[1, 0], R[0, 0])
    else:
        pitch = math.atan2(-R[1, 2], R[1, 1])
        yaw = math.atan2(-R[2, 0], sy)
        roll = 0.0
    return np.degrees([pitch, yaw, roll])


# Fold the raw pitch angle back into the -90..+90 range.
def normalize_pitch(raw_deg):
    p = float(raw_deg) % 360
    if p > 180:
        p -= 360
    if p > 90:
        p -= 180
    elif p < -90:
        p += 180
    return p


# Map an angle in degrees onto a -3..+3 scale.
def scale_degrees(value_deg, full_scale_deg):
    return float(np.clip((value_deg / full_scale_deg) * 3.0, -3.0, 3.0))


# Run solvePnP on the six head pose landmarks and return the head angles
# both in degrees and on the -3..+3 scale used by the gaze model.
def estimate_face_angle(face_landmarks, frame_width, frame_height, cam_num):
    image_points = []
    for idx in settings.head_pose_landmarks.values():
        if idx >= len(face_landmarks):
            return None
        lm = face_landmarks[idx]
        image_points.append((lm.x * frame_width, lm.y * frame_height))

    image_points = np.array(image_points, dtype=np.float64)
    fl = frame_width
    cx, cy = frame_width / 2.0, frame_height / 2.0
    camera_matrix = np.array([[fl, 0, cx], [0, fl, cy], [0, 0, 1]], dtype=np.float64)
    dist_coef = np.zeros((4, 1), dtype=np.float64)

    ok, rvec, _ = cv2.solvePnP(settings.head_pose_model_points, image_points,
                               camera_matrix, dist_coef, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return None

    R, _ = cv2.Rodrigues(rvec)
    raw_pitch, raw_yaw, raw_roll = rotation_matrix_to_euler_angles(R)

    yaw_sign = settings.camera_yaw_sign.get(cam_num, 1.0)
    signed_yaw = raw_yaw * settings.face_turn_sign * yaw_sign
    signed_pitch = (normalize_pitch(raw_pitch) * settings.pitch_sign) - settings.pitch_fixed_offset_degrees
    signed_roll = raw_roll * settings.roll_sign
    if abs(raw_roll) > 90.0:
        signed_roll = 0.0

    return {
        "yaw_scale": scale_degrees(signed_yaw, settings.yaw_degrees_for_full_scale),
        "pitch_scale": scale_degrees(signed_pitch, settings.pitch_degrees_for_full_scale),
        "roll_scale": scale_degrees(signed_roll, settings.roll_degrees_for_full_scale),
        "yaw_degrees": float(signed_yaw),
        "pitch_degrees": float(signed_pitch),
        "roll_degrees": float(signed_roll),
    }


##
# iris position
##
# Where does the iris sit inside the eye opening (left/right, up/down).

# Iris position inside one eye, normalized to roughly -1..+1 in x and y.
def calculate_one_eye_iris_position(iris_points, eye_points):
    if not iris_points or len(eye_points) < 4:
        return None
    iris_np = np.array(iris_points, dtype=np.float32)
    eye_np = np.array(eye_points, dtype=np.float32)
    iris_cx = float(np.mean(iris_np[:, 0]))
    iris_cy = float(np.mean(iris_np[:, 1]))
    eye_left = float(np.min(eye_np[:, 0]))
    eye_right = float(np.max(eye_np[:, 0]))
    eye_top = float(np.min(eye_np[:, 1]))
    eye_bot = float(np.max(eye_np[:, 1]))
    eye_w = max(eye_right - eye_left, 1.0)
    eye_h = max(eye_bot - eye_top, 1.0)
    x_ratio = (iris_cx - eye_left) / eye_w
    y_ratio = (iris_cy - eye_top) / eye_h
    return {
        "x_norm": float(np.clip((x_ratio - 0.5) * 2.0, -2.0, 2.0)),
        "y_norm": float(np.clip((y_ratio - 0.5) * 2.0, -2.0, 2.0)),
        "eye_width": eye_w, "eye_height": eye_h,
    }


# Combine both eyes into averaged iris positions plus the eye aspect ratio.
def calculate_iris_position_data(face_landmarks, w, h):
    if face_landmarks is None or len(face_landmarks) < 478:
        return None
    left_eye = get_landmark_points(face_landmarks, settings.left_eye_landmarks, w, h)
    right_eye = get_landmark_points(face_landmarks, settings.right_eye_landmarks, w, h)
    left_iris = get_landmark_points(face_landmarks, settings.left_iris_landmarks, w, h)
    right_iris = get_landmark_points(face_landmarks, settings.right_iris_landmarks, w, h)
    left_data = calculate_one_eye_iris_position(left_iris, left_eye)
    right_data = calculate_one_eye_iris_position(right_iris, right_eye)
    valid = [d for d in [left_data, right_data] if d is not None]
    if not valid:
        return None
    ear = float(np.mean([d["eye_height"] / max(d["eye_width"], 1.0) for d in valid]))
    return {
        "left": left_data, "right": right_data,
        "avg_x_norm": float(np.mean([d["x_norm"] for d in valid])),
        "avg_y_norm": float(np.mean([d["y_norm"] for d in valid])),
        "ear": ear,
        "left_eye_points": left_eye, "right_eye_points": right_eye,
        "left_iris_points": left_iris, "right_iris_points": right_iris,
    }


##
# gaze estimation
##
# Compare the measured iris position against what the fitted model expects
# for the current head pose. Small residual = looking into the camera.

# Main gaze decision: returns residuals, a 0..1 score and a direction label.
def estimate_gaze(cam_num, face_angle, iris_data, angle_state):
    if face_angle is None or iris_data is None:
        return None

    cal = settings.camera_gaze_calibration.get(cam_num, settings.camera_gaze_calibration[0])
    yaw = float(face_angle["yaw_scale"])
    pitch = float(face_angle["pitch_scale"])
    actual_x = float(iris_data["avg_x_norm"])
    actual_y = float(iris_data["avg_y_norm"])

    yaw_sign = 1.0 if yaw >= 0.0 else -1.0
    expected_x = (cal["x_yaw_slope"] * yaw
                  + cal.get("x_yaw2_slope", 0.0) * yaw_sign * yaw * yaw
                  + cal["x_pitch_slope"] * pitch + cal["x_intercept"])
    res_x = actual_x - expected_x - angle_state.x_offset

    expected_y = (cal["y_yaw_slope"] * yaw
                  + cal.get("y_yaw2_slope", 0.0) * yaw_sign * yaw * yaw
                  + cal["y_pitch_slope"] * pitch + cal["y_intercept"])
    iris_y_res = actual_y - expected_y

    actual_ear = float(iris_data.get("ear", 0.0))
    expected_ear = (cal["ear_pitch_slope"] * pitch + cal["ear_yaw_slope"] * yaw
                    + cal["ear_absyaw_slope"] * abs(yaw) + cal["ear_intercept"])
    ear_res = actual_ear - expected_ear

    iris_z = iris_y_res / max(cal["iris_y_res_std"], 1e-6)
    ear_z = ear_res / max(cal["ear_res_std"], 1e-6)
    res_v = 0.5 * iris_z + 0.5 * ear_z - angle_state.y_offset

    a = settings.residual_smoothing
    if angle_state.res_x_ema is None:
        angle_state.res_x_ema = res_x
        angle_state.res_v_ema = res_v
    else:
        angle_state.res_x_ema = a * res_x + (1.0 - a) * angle_state.res_x_ema
        angle_state.res_v_ema = a * res_v + (1.0 - a) * angle_state.res_v_ema
    res_x = angle_state.res_x_ema
    res_v = angle_state.res_v_ema

    in_x = abs(res_x) <= cal["x_direct_tolerance"]
    in_v = abs(res_v) <= cal["v_tolerance"]
    inside_direct = in_x and in_v

    x_score = clamp01(1.0 - abs(res_x) / cal["x_full_error"])
    v_score = clamp01(1.0 - abs(res_v) / cal["v_full_error"])
    direct_score = min(x_score, v_score)
    looking_into_camera = inside_direct and direct_score >= settings.min_green_score

    if looking_into_camera:
        gaze_direction = "looking_into_camera"
    elif inside_direct:
        gaze_direction = "almost_camera"
    else:
        x_norm_err = abs(res_x) / max(cal["x_direct_tolerance"], 1e-6)
        v_norm_err = abs(res_v) / max(cal["v_tolerance"], 1e-6)
        if v_norm_err > x_norm_err:
            if res_v >= cal["v_up_down_threshold"]:
                gaze_direction = "looking_above"
            elif res_v <= -cal["v_up_down_threshold"]:
                gaze_direction = "looking_below"
            elif res_v > 0:
                gaze_direction = "slightly_above"
            else:
                gaze_direction = "slightly_below"
        else:
            if res_x <= -cal["x_left_right_threshold"]:
                gaze_direction = "looking_left"
            elif res_x >= cal["x_left_right_threshold"]:
                gaze_direction = "looking_right"
            elif res_x < 0:
                gaze_direction = "slightly_left"
            else:
                gaze_direction = "slightly_right"

    return {
        "camera_num": cam_num, "yaw_scale": yaw, "pitch_scale": pitch,
        "x_residual": res_x, "v_residual": res_v,
        "direct_score": direct_score,
        "looking_into_camera": looking_into_camera, "gaze_direction": gaze_direction,
    }