import unittest

from vision_engine.gesture_stabilizer import GESTURE_STABILIZATION, GestureStabilizer
from vision_engine.hand_orientation import HandOrientationDetector


def hand_with_palm_order(index_on_left=True):
    landmarks = [{"x": 0.5, "y": 0.5, "z": 0.0} for _ in range(21)]
    landmarks[0] = {"x": 0.5, "y": 0.8, "z": 0.0}
    landmarks[5] = {
        "x": 0.4 if index_on_left else 0.6,
        "y": 0.5,
        "z": 0.0,
    }
    landmarks[17] = {
        "x": 0.6 if index_on_left else 0.4,
        "y": 0.5,
        "z": 0.0,
    }
    return landmarks


class TestHandOrientationDetector(unittest.TestCase):
    def test_initial_open_palm_sets_reference_and_flip_is_detected(self):
        detector = HandOrientationDetector()
        self.assertEqual(
            detector.update(hand_with_palm_order(True), "OPEN_PALM"), "OPEN_PALM"
        )
        self.assertEqual(
            detector.update(hand_with_palm_order(False), "OPEN_PALM"), "BACK_OF_HAND"
        )

    def test_orientation_is_independent_of_left_or_right_hand(self):
        for palm_order in (True, False):
            with self.subTest(palm_order=palm_order):
                detector = HandOrientationDetector()
                front = hand_with_palm_order(palm_order)
                back = hand_with_palm_order(not palm_order)
                detector.update(front, "OPEN_PALM")
                self.assertEqual(detector.update(back, "POINTING"), "BACK_OF_HAND")

    def test_back_of_hand_exit_requires_stabilization(self):
        detector = HandOrientationDetector()
        front = hand_with_palm_order(True)
        back = hand_with_palm_order(False)
        detector.update(front, "OPEN_PALM")
        stabilizer = GestureStabilizer(GESTURE_STABILIZATION)
        outputs = [
            stabilizer.update(detector.update(back, "OPEN_PALM"), now)
            for now in (1.0, 1.1, 1.2, 1.3, 1.4)
        ]
        self.assertEqual(outputs[-1]["stable_gesture"], "BACK_OF_HAND")

    def test_unconfident_sideways_hand_does_not_trigger_exit(self):
        detector = HandOrientationDetector()
        landmarks = hand_with_palm_order(True)
        detector.update(landmarks, "OPEN_PALM")
        landmarks[5] = {"x": 0.5, "y": 0.6, "z": 0.0}
        landmarks[17] = {"x": 0.5, "y": 0.4, "z": 0.0}
        self.assertEqual(detector.update(landmarks, "OPEN_PALM"), "OPEN_PALM")


if __name__ == "__main__":
    unittest.main()
