# settings.py - all the settings and tuning values in one place.
# Change camera index, ESP32 address, motor timing etc. here.

import os
import numpy as np


##
# camera settings
##
# Which webcam to grab, what resolution to run at and whether to show
# a local preview window next to the web page.

camera_index  = 1
camera_width  = 640
camera_height = 480
camera_fps    = 30
mirror_camera = False
camera_backend = "auto"   # "auto", "dshow" (Windows), "v4l2" (Linux)
camera_warmup_seconds = 1.0
show_local_window = True

model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "face_landmarker.task")
camera_num = 0


##
# web server settings
##
# Where the Flask control page runs and how the calibration routine behaves.

web_host = "0.0.0.0"
web_port = 8000
jpeg_quality = 70
calib_frames = 15
calib_timeout_s = 4.0


##
# esp32 settings
##
# Address of the ESP32 on the network and how often we talk to it.

esp32_host           = "192.168.50.60"     # pama
#esp32_host           = "192.168.178.232"  # thuis
esp32_port           = 80
esp32_http_timeout_s = 0.4
esp32_poll_s         = 0.15                 # how often /state is sent


##
# motor / gaze behaviour
##
# Motor PWM speeds and the timing rules for eye contact and bursts.

speed_normal = 190
speed_fast   = 255

eye_led1_s       = 0.5     # first green eye LED after this hold
eye_led2_s       = 1.5     # second green eye LED after this hold
eye_trigger_s    = 1.5     # eye contact must be held this long to fire the burst
eye_run_s        = 20.0    # motor runs this long after the trigger
look_grace_s     = 0.3     # brief dropouts shorter than this don't reset the hold


##
# visual settings
##
# Colors and toggles for the overlay drawn on the camera frame.

text_color = (255, 255, 255)
angle_text_color = (0, 255, 0)
good_gaze_color = (0, 255, 0)
bad_gaze_color = (0, 165, 255)
eye_line_color = (255, 120, 0)
iris_circle_color = (0, 255, 255)
show_eye_outline = True
show_iris_circle = True


##
# data-fitted gaze model
##
# Fitted slopes/intercepts that predict where the iris should sit for a
# given head pose, plus tolerances for deciding "looking into camera".

camera_gaze_calibration = {
    0: {
        "x_yaw_slope":   0.1368, "x_yaw2_slope":  -0.0010, "x_pitch_slope": 0.0149,
        "x_intercept":   -0.0215,
        "y_yaw_slope":    0.0308, "y_yaw2_slope":  -0.0064, "y_pitch_slope": 0.0204,
        "y_intercept":   -0.1063,
        "ear_pitch_slope": -0.0556, "ear_yaw_slope": 0.0050, "ear_absyaw_slope": 0.0459,
        "ear_intercept":    0.3215, "iris_y_res_std": 0.0482, "ear_res_std": 0.0262,
        "x_direct_tolerance": 0.09, "v_tolerance": 1.4,
        "x_left_right_threshold": 0.15, "v_up_down_threshold": 0.80,
        "x_full_error": 0.28, "v_full_error": 4.0,
    },
}
camera_yaw_sign = {0: 1.0}

pitch_sign = -1.0
pitch_fixed_offset_degrees = 0.0
pitch_degrees_for_full_scale = 40.0
face_turn_sign = 1.0
roll_sign = 1.0
yaw_degrees_for_full_scale = 90.0
roll_degrees_for_full_scale = 90.0

min_green_score = 0.8
residual_smoothing = 0.3
print_interval_seconds = 0.5


##
# mediapipe landmark indexes
##
# Index numbers into Google's 478-point face mesh for the eyes, irises
# and the six points used for head pose.

left_eye_landmarks = [33, 7, 163, 144, 145, 153, 154, 155,
                      133, 173, 157, 158, 159, 160, 161, 246]
right_eye_landmarks = [362, 382, 381, 380, 374, 373, 390, 249,
                       263, 466, 388, 387, 386, 385, 384, 398]
left_iris_landmarks = [468, 469, 470, 471, 472]
right_iris_landmarks = [473, 474, 475, 476, 477]

head_pose_landmarks = {
    "nose_tip": 1, "chin": 152, "left_eye_outer": 33, "right_eye_outer": 263,
    "left_mouth_corner": 61, "right_mouth_corner": 291,
}
head_pose_model_points = np.array([
    (0.0, 0.0, 0.0), (0.0, -63.6, -12.5), (-43.3, 32.7, -26.0),
    (43.3, 32.7, -26.0), (-28.9, -28.9, -24.1), (28.9, -28.9, -24.1),
], dtype=np.float64)