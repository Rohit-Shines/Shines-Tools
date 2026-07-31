# Third-party references and notices

This project contains original implementation code. Design ideas were reviewed from the two user-supplied MIT-licensed projects:

1. **Exercise_Recognition_AI** — Chris Prasanna, 2022, MIT License. Concepts reviewed: temporal exercise classification, joint-angle visualization, and exercise-specific rep-state logic.
2. **Motion Tracker** — Motion Tracker Contributors, 2026, MIT License. Concepts reviewed: modular pose/geometry architecture, 3-D angle calculation, posture metrics and skeleton visualization.

The project uses these external libraries/models under their respective licences:

- Google MediaPipe Pose Landmarker.
- OpenCV and OpenCV Zoo YuNet/SFace models.
- NumPy.
- Matplotlib.

No TensorFlow/LSTM model from the supplied repository is redistributed. That model only covers curl, press and squat, uses an older dependency stack, and does not solve the push-up false-positive problem. The new automatic recognition layer is conservative and implemented independently.
