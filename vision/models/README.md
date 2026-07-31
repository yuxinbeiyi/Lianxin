# Visual Model Setup

This directory is intentionally empty in the public repository. The optional
MediaPipe vision features load model files from this exact directory at runtime.
Download the following upstream files when you enable the related capability:

| File name | Used by | Official download |
| --- | --- | --- |
| `blaze_face_short_range.tflite` | Face detector | https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite |
| `face_landmarker.task` | Face landmarks | https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task |
| `hand_landmarker.task` | Gesture detector | https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task |
| `pose_landmarker_lite.task` | Pose tracking | https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task |

Place each downloaded file directly in `vision/models/` without changing its
name. These files are ignored by Git and remain local to each user.

The files originate from MediaPipe. Read and comply with the upstream license
and any model-specific terms before downloading or redistributing them.
