# Workout Version 3 — Accuracy Test Guide

## First validation: Push-up and Squat only

1. Open the dashboard.
2. Click **Deselect all**.
3. Enable only **Push-up** and **Squat**.
4. Click **Save exercise preferences, order and goals**.
5. Choose **Automatic mode**.
6. Start the workout.

### Squat camera setup

- Use a front or 45-degree view.
- Keep shoulders, hips, knees, and ankles visible.
- Start upright.
- Perform five slow complete squats.

Expected result: the live title remains `TRACKING: SQUAT` while squatting.

### Push-up camera setup

- Use a side view.
- Keep shoulder, elbow, wrist, hip, knee, and ankle visible.
- Move the Mac 2–3 metres away.
- Begin in the top plank position.
- Perform five slow complete push-ups.

Expected result: the live title changes to `TRACKING: PUSH-UP`.
The hard body-orientation gate prevents a horizontal body from being labelled Squat.

## Shoulder press versus Biceps curl

For the first test, enable only **Shoulder press** and **Biceps curl**.

### Shoulder press

- Face the camera.
- Start with hand(s) at shoulder level.
- Move the wrist clearly above the shoulder/head line.
- Lower back to shoulder level.

Expected result: `TRACKING: SHOULDER PRESS`.

### Biceps curl

- Face the camera.
- Keep the upper arm near the torso.
- Curl the forearm without sending the wrist overhead.
- Lower fully.

Expected result: `TRACKING: BICEPS CURL`.

## Manual mode

Manual mode is deterministic and does not classify the exercise.

Priority keys:

- `P` Push-up
- `S` Squat
- `H` Shoulder press
- `B` Biceps curl
- `T` Taekwondo kick

Other keys:

- `J` Jumping jack
- `L` Lunge
- `R` Lateral raise
- `K` High knee
- `U` Sit-up
- `N` Plank
- `O` Squat hold
- `W` Overhead stretch
- `F` Forward fold
- `E` Head turn
- `A` Arm circle
- `I` Hip circle

Controls:

- `0` Automatic mode
- `M` Manual mode without a selected exercise
- `X` Reset current tracker
- `D` Open report dashboard
- `Q` Finish and save
