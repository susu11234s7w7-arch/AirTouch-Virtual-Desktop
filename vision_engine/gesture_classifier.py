
import math
import numpy as np


class GestureClassifier:

    def __init__(self):
        pass

    def _angle(self, a, b, c):
        a = np.array([a["x"], a["y"]])
        b = np.array([b["x"], b["y"]])
        c = np.array([c["x"], c["y"]])

        ba = a - b
        bc = c - b

        denominator = np.linalg.norm(ba) * np.linalg.norm(bc)

        if denominator == 0:
            return 0.0

        cosine = np.dot(ba, bc) / denominator
        cosine = np.clip(cosine, -1.0, 1.0)

        return math.degrees(math.acos(cosine))

    def classify(self, landmarks):

        if not isinstance(landmarks, list):
            raise TypeError("landmarks must be a list")

        if len(landmarks) != 21:
            raise ValueError("A hand must contain exactly 21 landmarks")

        fingers = {
            "index": (5, 6, 7),
            "middle": (9, 10, 11),
            "ring": (13, 14, 15),
            "pinky": (17, 18, 19),
        }

        finger_angles = {
            name: self._angle(
                landmarks[points[0]],
                landmarks[points[1]],
                landmarks[points[2]]
            )
            for name, points in fingers.items()
        }

        finger_states = {
            name: angle > 145
            for name, angle in finger_angles.items()
        }

        thumb_tip = landmarks[4]
        thumb_ip = landmarks[3]
        thumb_mcp = landmarks[2]
        pinky_mcp = landmarks[17]

        thumb_tip_distance = math.dist(
            [thumb_tip["x"], thumb_tip["y"]],
            [pinky_mcp["x"], pinky_mcp["y"]]
        )

        thumb_base_distance = math.dist(
            [thumb_ip["x"], thumb_ip["y"]],
            [pinky_mcp["x"], pinky_mcp["y"]]
        )

        thumb_extended = thumb_tip_distance > thumb_base_distance

        thumb_angle = self._angle(
            landmarks[2],
            landmarks[3],
            landmarks[4]
        )

        thumb_raised = (
            thumb_tip["y"] < thumb_mcp["y"]
            and thumb_angle > 120
        )

        finger_states["thumb"] = thumb_extended

        index = finger_states["index"]
        middle = finger_states["middle"]
        ring = finger_states["ring"]
        pinky = finger_states["pinky"]

        four_folded = not any(finger_states[name] for name in fingers)
        four_extended = all(finger_states[name] for name in fingers)

        # Gesture classification
        if four_folded and thumb_raised and thumb_extended:
            gesture = "THUMBS_UP"

        elif four_extended and thumb_extended:
            gesture = "OPEN_PALM"

        elif four_folded and not thumb_extended:
            gesture = "FIST"

        elif index and middle and not ring and not pinky:
            gesture = "PEACE"

        elif index and not middle and not ring and not pinky:
            gesture = "POINTING"

        else:
            gesture = "UNKNOWN"

        return {
            "gesture": gesture,
            "confidence": 1.0 if gesture != "UNKNOWN" else 0.0,
            "extended_fingers": sum(finger_states.values()),
            "finger_states": finger_states,
            "finger_angles": finger_angles,
            "thumb_angle": thumb_angle,
        }
