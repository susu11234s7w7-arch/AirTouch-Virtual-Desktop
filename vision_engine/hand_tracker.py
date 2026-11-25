
import cv2
import mediapipe as mp

from mediapipe.tasks import python
from mediapipe.tasks.python import vision


class HandTracker:
    def __init__(self, model_path="models/hand_landmarker.task"):
        base_options = python.BaseOptions(
            model_asset_path=model_path
        )

        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5
        )

        self.detector = vision.HandLandmarker.create_from_options(
            options
        )
        self._last_timestamp_ms = -1

    @staticmethod
    def extract_handedness(result, hand_index=0):
        """Return primary MediaPipe handedness label if available."""
        handedness_list = getattr(result, "handedness", None)
        if not handedness_list or hand_index >= len(handedness_list):
            return "N/A"
        hand_cats = handedness_list[hand_index]
        if not hand_cats:
            return "N/A"
        category = hand_cats[0]
        label = getattr(category, "category_name", None) or getattr(category, "display_name", "N/A")
        score = getattr(category, "score", None)
        if score is not None:
            return f"{label} ({score:.2f})"
        return str(label)

    def process(self, frame, timestamp_ms):
        if timestamp_ms <= self._last_timestamp_ms:
            timestamp_ms = self._last_timestamp_ms + 1
        self._last_timestamp_ms = timestamp_ms

        rgb_frame = cv2.cvtColor(
            frame, cv2.COLOR_BGR2RGB
        )

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=rgb_frame
        )

        result = self.detector.detect_for_video(
            mp_image, timestamp_ms
        )

        annotated = frame.copy()

        if result.hand_landmarks:
            for hand_landmarks in result.hand_landmarks:
                for landmark in hand_landmarks:
                    x = int(landmark.x * frame.shape[1])
                    y = int(landmark.y * frame.shape[0])

                    cv2.circle(
                        annotated,
                        (x, y),
                        5,
                        (0, 255, 0),
                        -1
                    )

                for connection in vision.HandLandmarksConnections.HAND_CONNECTIONS:
                    start = hand_landmarks[connection.start]
                    end = hand_landmarks[connection.end]

                    p1 = (
                        int(start.x * frame.shape[1]),
                        int(start.y * frame.shape[0])
                    )

                    p2 = (
                        int(end.x * frame.shape[1]),
                        int(end.y * frame.shape[0])
                    )

                    cv2.line(
                        annotated,
                        p1,
                        p2,
                        (255, 0, 0),
                        2
                    )

        return annotated, result

    def close(self):
        self.detector.close()
