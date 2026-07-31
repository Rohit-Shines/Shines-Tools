from __future__ import annotations

from pathlib import Path

DEFAULT_HOME = Path.home() / "Documents" / "Shines Tools" / "Workout Version 3"

# MediaPipe Pose landmark indexes.
NOSE = 0
LEFT_EYE = 2
RIGHT_EYE = 5
LEFT_EAR = 7
RIGHT_EAR = 8
LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_ELBOW, RIGHT_ELBOW = 13, 14
LEFT_WRIST, RIGHT_WRIST = 15, 16
LEFT_PINKY, RIGHT_PINKY = 17, 18
LEFT_INDEX, RIGHT_INDEX = 19, 20
LEFT_THUMB, RIGHT_THUMB = 21, 22
LEFT_HIP, RIGHT_HIP = 23, 24
LEFT_KNEE, RIGHT_KNEE = 25, 26
LEFT_ANKLE, RIGHT_ANKLE = 27, 28
LEFT_HEEL, RIGHT_HEEL = 29, 30
LEFT_FOOT_INDEX, RIGHT_FOOT_INDEX = 31, 32

# Dynamic exercises are measured in repetitions.
REP_EXERCISES = (
    "pushup",
    "squat",
    "curl",
    "shoulder_press",
    "jumping_jack",
    "lunge",
    "lateral_raise",
    "high_knee",
    "situp",
    "taekwondo_kick",
    "head_turn",
    "arm_circle",
    "hip_circle",
)

# Static holds and stretches are measured in whole seconds.
TIMED_EXERCISES = (
    "plank",
    "squat_hold",
    "overhead_stretch",
    "forward_fold",
)

EXERCISES = REP_EXERCISES + TIMED_EXERCISES

# Offline record-first mode remains limited to calibrated repetition exercises.
OFFLINE_EXERCISES = (
    "pushup",
    "squat",
    "curl",
    "shoulder_press",
    "jumping_jack",
)

DISPLAY_NAMES = {
    "pushup": "Push-up",
    "squat": "Squat",
    "curl": "Biceps curl",
    "shoulder_press": "Shoulder press",
    "jumping_jack": "Jumping jack",
    "lunge": "Lunge",
    "lateral_raise": "Lateral raise",
    "high_knee": "High knee",
    "situp": "Sit-up",
    "taekwondo_kick": "Taekwondo kick",
    "head_turn": "Head turn",
    "arm_circle": "Arm circle",
    "hip_circle": "Hip circle",
    "plank": "Plank",
    "squat_hold": "Squat hold",
    "overhead_stretch": "Overhead stretch",
    "forward_fold": "Forward fold",
}

EXERCISE_UNITS = {exercise: "reps" for exercise in REP_EXERCISES}
EXERCISE_UNITS.update({exercise: "seconds" for exercise in TIMED_EXERCISES})

# Number keys remain the familiar manual fallback. Timed holds and warm-ups use letters.
KEY_TO_EXERCISE = {
    # Priority manual controls requested for Workout Version 3.
    "p": "pushup",
    "s": "squat",
    "h": "shoulder_press",
    "b": "curl",
    "t": "taekwondo_kick",

    # Remaining exercises use unique single-letter shortcuts.
    "j": "jumping_jack",
    "l": "lunge",
    "r": "lateral_raise",
    "k": "high_knee",
    "u": "situp",
    "n": "plank",
    "o": "squat_hold",
    "w": "overhead_stretch",
    "f": "forward_fold",
    "e": "head_turn",
    "a": "arm_circle",
    "i": "hip_circle",
}

EXERCISE_SHORTCUTS = {
    "pushup": "P",
    "squat": "S",
    "shoulder_press": "H",
    "curl": "B",
    "taekwondo_kick": "T",
    "jumping_jack": "J",
    "lunge": "L",
    "lateral_raise": "R",
    "high_knee": "K",
    "situp": "U",
    "plank": "N",
    "squat_hold": "O",
    "overhead_stretch": "W",
    "forward_fold": "F",
    "head_turn": "E",
    "arm_circle": "A",
    "hip_circle": "I",
}


# Shortcut defaults can be customised independently for each profile.
# These keys remain reserved for application-level controls.
RESERVED_SHORTCUT_KEYS = {"0", "m", "x", "d", "q"}
DEFAULT_SHORTCUTS = dict(EXERCISE_SHORTCUTS)


DEFAULT_GOALS = {
    "pushup": 20,
    "squat": 30,
    "curl": 20,
    "shoulder_press": 15,
    "jumping_jack": 50,
    "lunge": 20,
    "lateral_raise": 20,
    "high_knee": 40,
    "situp": 20,
    "taekwondo_kick": 20,
    "head_turn": 10,
    "arm_circle": 10,
    "hip_circle": 10,
    "plank": 30,
    "squat_hold": 30,
    "overhead_stretch": 30,
    "forward_fold": 30,
}

# Accuracy-first defaults. New specialised movements are available but disabled
# initially to avoid affecting a user's existing automatic-recognition workflow.
DEFAULT_ENABLED = {exercise: True for exercise in (
    "pushup", "squat", "curl", "shoulder_press", "jumping_jack",
    "lunge", "lateral_raise", "high_knee", "situp",
)}
DEFAULT_ENABLED.update(
    {
        "taekwondo_kick": False,
        "head_turn": False,
        "arm_circle": False,
        "hip_circle": False,
        "plank": True,
        "squat_hold": True,
        "overhead_stretch": False,
        "forward_fold": False,
    }
)

DEFAULT_OVERALL_DAILY_GOAL = 100

# In-app reference material. These are practical camera/testing instructions,
# not medical prescriptions.
EXERCISE_GUIDES = {
    "pushup": {
        "setup": "Side view; keep shoulder, hip, knee and ankle visible.",
        "steps": "Start in a straight plank, lower under control, then return to straight arms.",
        "count_rule": "One top → down → top cycle counts.",
        "safety": "Use an incline if shoulder, wrist or chest pain appears.",
    },
    "squat": {
        "setup": "Front or 45° view with hips, knees and ankles visible.",
        "steps": "Sit hips back and down, keep knees tracking over toes, then stand.",
        "count_rule": "One standing → lowered → standing cycle counts.",
        "safety": "Use a comfortable depth; stop for sharp knee or back pain.",
    },
    "curl": {
        "setup": "Front view; keep at least one full arm visible.",
        "steps": "Keep upper arm near the torso, bend the elbow, then lower fully.",
        "count_rule": "One down → curl → down cycle counts.",
        "safety": "Avoid swinging the torso.",
    },
    "shoulder_press": {
        "setup": "Front view; keep shoulder, elbow and wrist visible.",
        "steps": "Start near shoulder height, press overhead, then lower.",
        "count_rule": "One shoulder → overhead → shoulder cycle counts.",
        "safety": "Use a pain-free range and light resistance.",
    },
    "jumping_jack": {
        "setup": "Front view with hands and feet inside the frame.",
        "steps": "Jump feet apart while arms rise, then return together.",
        "count_rule": "One closed → open → closed cycle counts.",
        "safety": "Use step-jacks for a lower-impact option.",
    },
    "lunge": {
        "setup": "Front or 45° view with both legs visible.",
        "steps": "Step or split stance, lower both knees, then return.",
        "count_rule": "One lowered → upright cycle counts.",
        "safety": "Keep the front knee aligned with the foot.",
    },
    "lateral_raise": {
        "setup": "Front view with both arms visible.",
        "steps": "Raise mostly straight arms sideways to shoulder height, then lower.",
        "count_rule": "One down → side raise → down cycle counts.",
        "safety": "Do not force above shoulder level.",
    },
    "high_knee": {
        "setup": "Front view with hips, knees and feet visible.",
        "steps": "Lift one knee toward hip level, lower, then alternate.",
        "count_rule": "Each completed knee lift counts.",
        "safety": "March instead of running if balance is limited.",
    },
    "situp": {
        "setup": "Side view with shoulders, hips and knees visible.",
        "steps": "Rise from the floor toward the knees and lower with control.",
        "count_rule": "One down → up → down cycle counts.",
        "safety": "Use a smaller curl-up range if the lower back is uncomfortable.",
    },
    "taekwondo_kick": {
        "setup": "Front or 45° view; leave space above and beside you. Enable this exercise first.",
        "steps": "Chamber either knee, extend the leg high, retract it, and return the foot to the floor.",
        "count_rule": "Either left or right high kick counts once after the foot returns.",
        "safety": "Warm up first, kick into open space, and do not force height.",
    },
    "head_turn": {
        "setup": "Face the camera with shoulders level and hands relaxed.",
        "steps": "Turn the head left or right within a comfortable range, then return to centre.",
        "count_rule": "Each side turn followed by a return to centre counts once.",
        "safety": "Use controlled left/right turns rather than forceful full neck circles.",
    },
    "arm_circle": {
        "setup": "Front view with one or both full arms visible.",
        "steps": "Keep the arm long and draw a large controlled circle forward or backward.",
        "count_rule": "Each approximately complete 360° arm loop counts once.",
        "safety": "Start with small circles if the shoulder is stiff or painful.",
    },
    "hip_circle": {
        "setup": "Front view from shoulders to knees; keep feet planted.",
        "steps": "Move the hips in a smooth circle while the upper body stays controlled.",
        "count_rule": "Each approximately complete clockwise or counter-clockwise loop counts once.",
        "safety": "Keep the movement gentle and avoid forcing the lower back.",
    },
    "plank": {
        "setup": "Side view with shoulder, hip and ankle visible.",
        "steps": "Hold a straight supported plank without letting the hips sag or pike.",
        "count_rule": "The live timer displays seconds while the pose remains valid.",
        "safety": "Use knees or an incline for an easier variation.",
    },
    "squat_hold": {
        "setup": "Side or 45° view with hip, knee and ankle visible.",
        "steps": "Lower into a comfortable squat and remain steady.",
        "count_rule": "The live timer displays seconds while the squat position remains valid.",
        "safety": "Use a shallower hold if knees or back feel uncomfortable.",
    },
    "overhead_stretch": {
        "setup": "Front view with arms visible.",
        "steps": "Reach one or both arms overhead while standing tall.",
        "count_rule": "Valid hold time is measured in seconds.",
        "safety": "Do not force painful shoulder elevation.",
    },
    "forward_fold": {
        "setup": "Side view with shoulders, hips and legs visible.",
        "steps": "Hinge forward at the hips within a comfortable range and hold.",
        "count_rule": "Valid hold time is measured in seconds.",
        "safety": "Keep knees soft and avoid bouncing.",
    },
}

POSE_HEAVY_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task"
)

POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_full/float16/latest/pose_landmarker_full.task"
)
YUNET_MODEL_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
SFACE_MODEL_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_recognition_sface/face_recognition_sface_2021dec.onnx"
)
