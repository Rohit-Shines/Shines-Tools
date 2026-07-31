# Workout Version 3.0.0

## Accuracy architecture

- Hierarchical body-orientation gates separate floor movements from upright movements.
- Push-up and squat can no longer compete across posture families.
- Shoulder presses require a true overhead wrist path.
- Biceps curls reject clearly overhead hand travel.
- Automatic recognition considers only exercises enabled in the dashboard.
- A two-exercise selection such as Push-up + Squat creates a focused recognition profile.
- Exercise names appear only after temporal confirmation; unstable guesses display as analysing.
- All exercise trackers run from the first frame, but high-risk confusion pairs require classifier agreement before saving a repetition.

## Modes

Only two modes are available:

1. Automatic mode
2. Manual keyboard mode

Priority manual keys:

- P — Push-up
- S — Squat
- H — Shoulder press
- B — Biceps curl
- T — Taekwondo kick

See README-FIRST.txt for the complete key map.
