"""Detect a deliberate palm-to-back-of-hand flip for clean app shutdown."""

import math


def _xy(point):
    if isinstance(point, dict):
        return float(point["x"]), float(point["y"])
    return float(point.x), float(point.y)


class HandOrientationDetector:
    """Learn the initial open-palm orientation, then detect its sustained flip.

    The signed screen-space area of the wrist/index-MCP/pinky-MCP triangle
    changes sign when the user turns the hand from palm-facing to back-facing.
    The first confident OPEN_PALM frame establishes the session reference so
    either anatomical hand and mirrored-camera input work the same way.
    """

    MIN_ORIENTATION_MAGNITUDE = 0.18

    def __init__(self):
        self.front_sign = None

    @classmethod
    def orientation_score(cls, landmarks):
        if landmarks is None or len(landmarks) != 21:
            return None
        wrist = _xy(landmarks[0])
        index_mcp = _xy(landmarks[5])
        pinky_mcp = _xy(landmarks[17])
        index_vector = (index_mcp[0] - wrist[0], index_mcp[1] - wrist[1])
        pinky_vector = (pinky_mcp[0] - wrist[0], pinky_mcp[1] - wrist[1])
        denominator = math.hypot(*index_vector) * math.hypot(*pinky_vector)
        if denominator <= 1e-9:
            return None
        cross = (
            index_vector[0] * pinky_vector[1]
            - index_vector[1] * pinky_vector[0]
        ) / denominator
        if abs(cross) < cls.MIN_ORIENTATION_MAGNITUDE:
            return None
        return cross

    def update(self, landmarks, gesture):
        """Return BACK_OF_HAND after a confident flip from the initial palm pose."""
        gesture = gesture.strip().upper() if isinstance(gesture, str) else "UNKNOWN"
        score = self.orientation_score(landmarks)
        if score is None:
            return gesture

        sign = 1 if score > 0 else -1
        if self.front_sign is None:
            if gesture == "OPEN_PALM":
                self.front_sign = sign
            return gesture

        if sign != self.front_sign:
            return "BACK_OF_HAND"
        return gesture
