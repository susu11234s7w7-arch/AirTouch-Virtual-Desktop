import tempfile
import unittest
from pathlib import Path

from tests.test_virtual_interface import _make_landmarks
from vision_engine.pinch_calibrator import PinchCalibrationConfig, PinchCalibrator


def _landmarks_with_pinch_ratio(target_ratio, scale=1.0, other_up=True):
    """Create valid 21 landmarks where thumb-index ratio matches target_ratio."""
    pts = _make_landmarks(
        index_up=True,
        middle_up=other_up,
        ring_up=other_up,
        pinky_up=other_up,
        scale=scale,
    )
    # In _make_landmarks(scale=1.0), wrist(0)=(0.50,0.82), middle_mcp(9)=(0.50,0.70) => dist=0.12
    # palm_width = dist(index_mcp(0.42,0.70), pinky_mcp(0.70,0.70)) = 0.28 -> palm_scale = 0.28 * scale
    palm_scale = 0.28 * scale
    ix, iy = pts[8]["x"], pts[8]["y"]
    pts[4] = {"x": ix + target_ratio * palm_scale, "y": iy}
    return pts


class TestPinchCalibrator(unittest.TestCase):
    def test_config_validation_and_json_roundtrip(self):
        with self.assertRaises(ValueError):
            PinchCalibrationConfig(enter_ratio=0.45, exit_ratio=0.35).validate()
        with self.assertRaises(ValueError):
            PinchCalibrationConfig(enter_ratio=0.0, exit_ratio=0.35).validate()
        with self.assertRaises(ValueError):
            PinchCalibrationConfig(cooldown_seconds=-1.0).validate()

        cfg = PinchCalibrationConfig(
            enter_ratio=0.28,
            exit_ratio=0.40,
            cooldown_seconds=1.5,
            min_confirm_frames=2,
            source="unit_test",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pinch_cfg.json"
            cfg.save(path)
            loaded = PinchCalibrationConfig.load(path)
            self.assertEqual(loaded, cfg)

    def test_hysteresis_prevents_boundary_oscillation(self):
        cfg = PinchCalibrationConfig(
            enter_ratio=0.30,
            exit_ratio=0.42,
            cooldown_seconds=0.5,
            min_confirm_frames=2,
        )
        cal = PinchCalibrator(cfg)

        # Open hand -> OPEN
        res = cal.update(_landmarks_with_pinch_ratio(0.60), now=1.0)
        self.assertEqual(res["state"], "OPEN")
        self.assertFalse(res["is_pinching"])

        # Frame 1 below enter_ratio -> still OPEN (needs 2 confirm frames)
        res = cal.update(_landmarks_with_pinch_ratio(0.26), now=1.05)
        self.assertEqual(res["state"], "OPEN")
        self.assertFalse(res["click_triggered"])

        # Frame 2 below enter_ratio -> transitions to PINCHING and fires click
        res = cal.update(_landmarks_with_pinch_ratio(0.26), now=1.10)
        self.assertEqual(res["state"], "PINCHING")
        self.assertTrue(res["is_pinching"])
        self.assertTrue(res["click_triggered"])

        # Jitter inside hysteresis band (0.35 in (0.30, 0.42)) MUST stay PINCHING
        res = cal.update(_landmarks_with_pinch_ratio(0.35), now=1.20)
        self.assertEqual(res["state"], "PINCHING")
        self.assertTrue(res["is_pinching"])
        self.assertFalse(res["click_triggered"])
        self.assertEqual(cal.hysteresis_holds, 1)

        # Moves above exit_ratio (0.45 >= 0.42) -> transitions cleanly to OPEN
        res = cal.update(_landmarks_with_pinch_ratio(0.45), now=1.30)
        self.assertEqual(res["state"], "OPEN")
        self.assertFalse(res["is_pinching"])

    def test_cooldown_suppresses_rapid_reclick(self):
        cfg = PinchCalibrationConfig(
            enter_ratio=0.30,
            exit_ratio=0.42,
            cooldown_seconds=2.0,
            min_confirm_frames=1,
        )
        cal = PinchCalibrator(cfg)

        first = cal.update(_landmarks_with_pinch_ratio(0.25), now=10.0)
        self.assertTrue(first["click_triggered"])

        # Release
        cal.update(_landmarks_with_pinch_ratio(0.55), now=10.2)

        # Re-pinch inside cooldown window (11.0 - 10.0 = 1.0s < 2.0s)
        second = cal.update(_landmarks_with_pinch_ratio(0.25), now=11.0)
        self.assertTrue(second["is_pinching"])
        self.assertFalse(second["click_triggered"])
        self.assertTrue(second["cooldown_blocked"])
        self.assertEqual(cal.cooldown_suppressed, 1)

        # Release & pinch after cooldown (12.5 - 10.0 = 2.5s >= 2.0s)
        cal.update(_landmarks_with_pinch_ratio(0.55), now=12.1)
        third = cal.update(_landmarks_with_pinch_ratio(0.25), now=12.5)
        self.assertTrue(third["click_triggered"])
        self.assertEqual(cal.successful_clicks, 2)

    def test_false_activation_and_hand_loss_reset(self):
        cfg = PinchCalibrationConfig(
            enter_ratio=0.30,
            exit_ratio=0.42,
            cooldown_seconds=1.0,
            min_confirm_frames=2,
        )
        cal = PinchCalibrator(cfg)

        # Closed fist with folded index tip inside palm -> rejected as false activation
        fist = _make_landmarks(index_up=False, middle_up=False, ring_up=False, pinky_up=False)
        fist[4] = {"x": fist[8]["x"] + 0.02, "y": fist[8]["y"]}
        res_fist = cal.update(fist, now=1.0, other_fingers_open=False)
        self.assertFalse(res_fist["is_pinching"])
        self.assertEqual(cal.false_activations, 1)

        # Single-frame transient dip followed by open -> counted as brief spike false candidate
        cal.update(_landmarks_with_pinch_ratio(0.25), now=2.0)
        cal.update(_landmarks_with_pinch_ratio(0.60), now=2.05)
        self.assertEqual(cal.false_activations, 2)

        # Hand loss while pinching resets state cleanly
        cal.update(_landmarks_with_pinch_ratio(0.25), now=3.0)
        cal.update(_landmarks_with_pinch_ratio(0.25), now=3.05)
        self.assertTrue(cal.is_pinching)

        lost = cal.update(None, now=3.10)
        self.assertEqual(lost["state"], "HAND_LOST")
        self.assertFalse(cal.is_pinching)

    def test_scale_invariance_and_empirical_calibration(self):
        cal = PinchCalibrator(PinchCalibrationConfig(min_confirm_frames=1))

        # Small and large hands with same normalized ratio behave identically
        for scale in (0.5, 1.8):
            res = cal.update(_landmarks_with_pinch_ratio(0.24, scale=scale), now=1.0 + scale * 3)
            self.assertTrue(res["is_pinching"])
            cal.update(_landmarks_with_pinch_ratio(0.60, scale=scale), now=1.5 + scale * 3)

        # Insufficient samples must raise ValueError (no guessed thresholds)
        with self.assertRaises(ValueError):
            cal.calibrate_from_samples(min_samples_per_class=10)

        for _ in range(10):
            cal.record_sample("open", _landmarks_with_pinch_ratio(0.65))
            cal.record_sample("pinch", _landmarks_with_pinch_ratio(0.22))

        tuned = cal.calibrate_from_samples(min_samples_per_class=10)
        self.assertLess(tuned.enter_ratio, tuned.exit_ratio)
        self.assertGreater(tuned.enter_ratio, 0.20)
        self.assertLess(tuned.exit_ratio, 0.65)
        self.assertIn("empirical_10open_10pinch", tuned.source)


if __name__ == "__main__":
    unittest.main()
