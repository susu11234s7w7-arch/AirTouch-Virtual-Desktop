import unittest

from vision_engine.middle_finger_click import MiddleFingerClickDetector


def pose(middle=False, ring=False, pinky=False, index=True):
    return {
        "index": index,
        "middle": middle,
        "ring": ring,
        "pinky": pinky,
    }


class TestMiddleFingerClickDetector(unittest.TestCase):
    def setUp(self):
        self.detector = MiddleFingerClickDetector()

    def arm(self, start=1.0):
        self.detector.update(pose(), now=start)
        self.detector.update(pose(), now=start + 0.05)

    def test_raises_and_lowers_middle_to_emit_exactly_one_click(self):
        self.arm()
        self.assertFalse(self.detector.update(pose(middle=True), now=1.10)["click_triggered"])
        raised = self.detector.update(pose(middle=True), now=1.15)
        self.assertTrue(raised["press_active"])
        self.assertFalse(raised["click_triggered"])

        self.assertFalse(self.detector.update(pose(), now=1.20)["click_triggered"])
        clicked = self.detector.update(pose(), now=1.25)
        self.assertTrue(clicked["click_triggered"])
        self.assertFalse(clicked["press_active"])
        self.assertFalse(self.detector.update(pose(), now=1.30)["click_triggered"])

    def test_peace_held_does_not_click_and_times_out_safely(self):
        self.arm()
        self.detector.update(pose(middle=True), now=1.10)
        self.detector.update(pose(middle=True), now=1.15)
        timed_out = self.detector.update(pose(middle=True), now=2.0)
        self.assertFalse(timed_out["click_triggered"])
        self.assertFalse(timed_out["press_active"])
        self.assertFalse(self.detector.update(pose(), now=2.1)["click_triggered"])

    def test_brief_middle_finger_flick_does_not_click(self):
        self.arm()
        self.detector.update(pose(middle=True), now=1.10)
        returned = self.detector.update(pose(), now=1.12)
        self.assertFalse(returned["click_triggered"])

    def test_tracking_loss_or_invalid_finger_pose_cancels_the_tap(self):
        self.arm()
        self.detector.update(pose(middle=True), now=1.10)
        self.detector.update(pose(middle=True), now=1.15)
        self.detector.update(None, tracking_available=False, now=1.20)
        self.assertFalse(self.detector.update(pose(), now=1.25)["click_triggered"])

        self.arm(start=2.0)
        invalid = pose(middle=True, ring=True)
        self.assertFalse(self.detector.update(invalid, now=2.1)["click_triggered"])

    def test_middle_tap_requires_pointing_as_its_start_pose(self):
        self.detector.update(pose(middle=True), now=1.0)
        self.detector.update(pose(middle=True), now=1.05)
        self.detector.update(pose(), now=1.10)
        result = self.detector.update(pose(), now=1.15)
        self.assertFalse(result["click_triggered"])


if __name__ == "__main__":
    unittest.main()
