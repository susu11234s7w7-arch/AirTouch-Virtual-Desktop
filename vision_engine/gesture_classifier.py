import math
import numpy as np


class GestureClassifier:
    """Scale-invariant rule-based hand gesture classifier using 21 landmarks."""

    ANGLE_THRESHOLD = 145.0
    PINCH_RATIO_THRESHOLD = 0.36

    def __init__(self):
        pass

    def _angle(self, a, b, c):
        """Calculate the interior angle (degrees) at vertex b formed by a-b-c."""
        a_vec = np.array([a["x"], a["y"]], dtype=float)
        b_vec = np.array([b["x"], b["y"]], dtype=float)
        c_vec = np.array([c["x"], c["y"]], dtype=float)

        ba = a_vec - b_vec
        bc = c_vec - b_vec

        denominator = np.linalg.norm(ba) * np.linalg.norm(bc)
        if denominator == 0:
            return 0.0

        cosine = float(np.dot(ba, bc) / denominator)
        cosine = float(np.clip(cosine, -1.0, 1.0))
        return math.degrees(math.acos(cosine))

    def _compute_palm_scale(self, landmarks):
        """Estimate palm scale from wrist-to-middle-MCP and palm width."""
        wrist = landmarks[0]
        index_mcp = landmarks[5]
        middle_mcp = landmarks[9]
        pinky_mcp = landmarks[17]

        wrist_to_middle = math.dist(
            [wrist["x"], wrist["y"]],
            [middle_mcp["x"], middle_mcp["y"]],
        )
        palm_width = math.dist(
            [index_mcp["x"], index_mcp["y"]],
            [pinky_mcp["x"], pinky_mcp["y"]],
        )
        return max(wrist_to_middle, palm_width, 1e-6)

    def _compute_confidence(self, gesture, finger_angles, expected_states, pinch_ratio):
        """Compute a bounded geometric confidence score in [0.60, 0.99]."""
        if gesture == "UNKNOWN":
            return 0.0

        margins = []
        for name, should_extend in expected_states.items():
            angle = finger_angles[name]
            if should_extend:
                margin = min(1.0, max(0.0, (angle - self.ANGLE_THRESHOLD) / 35.0))
            else:
                margin = min(1.0, max(0.0, (self.ANGLE_THRESHOLD - angle) / 65.0))
            margins.append(margin)

        if gesture == "PINCH":
            pinch_margin = min(
                1.0,
                max(0.0, (self.PINCH_RATIO_THRESHOLD - pinch_ratio) / 0.24),
            )
            margins.append(pinch_margin)

        avg_margin = sum(margins) / max(1, len(margins))
        return round(min(0.99, 0.62 + 0.37 * avg_margin), 2)

    def classify(self, landmarks):
        if not isinstance(landmarks, list):
            raise TypeError("landmarks must be a list")

        if len(landmarks) != 21:
            raise ValueError("A hand must contain exactly 21 landmarks")

        palm_scale = self._compute_palm_scale(landmarks)

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
                landmarks[points[2]],
            )
            for name, points in fingers.items()
        }

        finger_states = {
            name: angle > self.ANGLE_THRESHOLD
            for name, angle in finger_angles.items()
        }

        wrist = landmarks[0]
        thumb_mcp = landmarks[2]
        thumb_ip = landmarks[3]
        thumb_tip = landmarks[4]
        index_mcp = landmarks[5]
        index_tip = landmarks[8]
        pinky_mcp = landmarks[17]

        # Scale-normalized distances relative to palm size
        thumb_tip_norm = (
            math.dist([thumb_tip["x"], thumb_tip["y"]], [pinky_mcp["x"], pinky_mcp["y"]])
            / palm_scale
        )
        thumb_ip_norm = (
            math.dist([thumb_ip["x"], thumb_ip["y"]], [pinky_mcp["x"], pinky_mcp["y"]])
            / palm_scale
        )
        thumb_extended = thumb_tip_norm > (thumb_ip_norm + 0.04)

        thumb_angle = self._angle(thumb_mcp, thumb_ip, thumb_tip)
        thumb_raised = (
            (thumb_mcp["y"] - thumb_tip["y"]) / palm_scale > 0.12
            and thumb_angle > 120.0
        )

        pinch_distance = math.dist(
            [thumb_tip["x"], thumb_tip["y"]],
            [index_tip["x"], index_tip["y"]],
        )
        pinch_ratio = pinch_distance / palm_scale

        index_tip_reach = (
            math.dist([index_tip["x"], index_tip["y"]], [wrist["x"], wrist["y"]])
            / palm_scale
        )
        index_mcp_reach = (
            math.dist([index_mcp["x"], index_mcp["y"]], [wrist["x"], wrist["y"]])
            / palm_scale
        )
        index_reaching_out = index_tip_reach > (index_mcp_reach * 1.15)

        finger_states["thumb"] = thumb_extended

        index = finger_states["index"]
        middle = finger_states["middle"]
        ring = finger_states["ring"]
        pinky = finger_states["pinky"]

        four_folded = not any(finger_states[name] for name in fingers)
        four_extended = all(finger_states[name] for name in fingers)

        is_pinching = pinch_ratio <= self.PINCH_RATIO_THRESHOLD and (
            (middle or ring or pinky) or index_reaching_out
        )

        # Gesture classification (order preserves specificity)
        expected_states = {}
        if is_pinching:
            gesture = "PINCH"
            expected_states = {"middle": middle, "ring": ring, "pinky": pinky}

        elif four_folded and thumb_raised and thumb_extended:
            gesture = "THUMBS_UP"
            expected_states = {name: False for name in fingers}

        elif four_extended and thumb_extended:
            gesture = "OPEN_PALM"
            expected_states = {name: True for name in fingers}

        elif four_folded and not thumb_extended:
            gesture = "FIST"
            expected_states = {name: False for name in fingers}

        elif index and middle and not ring and not pinky:
            gesture = "PEACE"
            expected_states = {
                "index": True,
                "middle": True,
                "ring": False,
                "pinky": False,
            }

        elif index and not middle and not ring and not pinky:
            gesture = "POINTING"
            expected_states = {
                "index": True,
                "middle": False,
                "ring": False,
                "pinky": False,
            }

        else:
            gesture = "UNKNOWN"

        confidence = self._compute_confidence(
            gesture=gesture,
            finger_angles=finger_angles,
            expected_states=expected_states,
            pinch_ratio=pinch_ratio,
        )

        return {
            "gesture": gesture,
            "confidence": confidence,
            "extended_fingers": sum(finger_states.values()),
            "finger_states": finger_states,
            "finger_angles": finger_angles,
            "thumb_angle": thumb_angle,
            "pinch_ratio": round(pinch_ratio, 3),
            "palm_scale": round(palm_scale, 4),
        }
