
from vision_engine.gesture_classifier import GestureClassifier


class GestureRecognition:
    """Connect MediaPipe hand landmarks to GestureClassifier."""

    def __init__(self):
        self.classifier = GestureClassifier()

    def recognize(self, hand_landmarks):
        if hand_landmarks is None or len(hand_landmarks) != 21:
            self.classifier.reset()
            return {
                "gesture": "UNKNOWN",
                "confidence": 0.0,
                "extended_fingers": 0,
                "finger_states": {},
                "finger_angles": {},
                "finger_geometry": {},
                "pinch_ratio": 1.0,
                "palm_scale": 0.0,
                "pinch_distance": 0.0,
            }

        landmarks = [
            {
                "x": float(point.x),
                "y": float(point.y),
            }
            for point in hand_landmarks
        ]

        return self.classifier.classify(landmarks)
