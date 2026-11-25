from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import time


@dataclass
class PinchCalibrationConfig:
    """Configurable hysteresis and cooldown parameters for PINCH detection."""

    enter_ratio: float = 0.30
    exit_ratio: float = 0.42
    cooldown_seconds: float = 1.8
    min_confirm_frames: int = 2
    min_index_reach_ratio: float = 1.15
    source: str = "default_geometric_baseline"

    def validate(self):
        if not 0.0 < self.enter_ratio < self.exit_ratio <= 1.5:
            raise ValueError(
                "Thresholds must satisfy 0.0 < enter_ratio < exit_ratio <= 1.5"
            )
        if self.cooldown_seconds < 0.0:
            raise ValueError("cooldown_seconds must be non-negative")
        if self.min_confirm_frames < 1:
            raise ValueError("min_confirm_frames must be >= 1")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        cfg = cls(
            enter_ratio=float(data.get("enter_ratio", 0.30)),
            exit_ratio=float(data.get("exit_ratio", 0.42)),
            cooldown_seconds=float(data.get("cooldown_seconds", 1.8)),
            min_confirm_frames=int(data.get("min_confirm_frames", 2)),
            min_index_reach_ratio=float(data.get("min_index_reach_ratio", 1.15)),
            source=str(data.get("source", "loaded_config")),
        )
        cfg.validate()
        return cfg

    def save(self, path):
        self.validate()
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)


class PinchCalibrator:
    """Scale-normalized PINCH state machine with hysteresis, cooldown, and telemetry."""

    def __init__(self, config=None):
        self.config = config or PinchCalibrationConfig()
        self.config.validate()

        self.is_pinching = False
        self._enter_streak = 0
        self.last_click_at = -1e9

        self.total_updates = 0
        self.successful_clicks = 0
        self.cooldown_suppressed = 0
        self.false_activations = 0
        self.hysteresis_holds = 0
        self.transitions = 0
        self.false_activation_reasons = []

        self.min_observed_ratio = None
        self.max_observed_ratio = None

        # Recorded empirical samples (open vs pinch) for data-backed threshold tuning
        self.open_samples = []
        self.pinch_samples = []

    def reset_state(self):
        """Reset transient pinch state (e.g. when hand leaves frame)."""
        if self._enter_streak > 0 and not self.is_pinching:
            self._record_false_activation("transient_spike_before_confirm")
        self.is_pinching = False
        self._enter_streak = 0

    def _record_false_activation(self, reason):
        self.false_activations += 1
        self.false_activation_reasons.append(reason)

    @staticmethod
    def compute_pinch_metrics(landmarks):
        """Compute raw distance, palm scale, normalized pinch ratio, and reach guard."""
        if landmarks is None or len(landmarks) != 21:
            return None

        def _xy(pt):
            if isinstance(pt, dict):
                return float(pt["x"]), float(pt["y"])
            return float(pt.x), float(pt.y)

        wrist = _xy(landmarks[0])
        thumb_tip = _xy(landmarks[4])
        index_mcp = _xy(landmarks[5])
        index_tip = _xy(landmarks[8])
        middle_mcp = _xy(landmarks[9])
        pinky_mcp = _xy(landmarks[17])

        wrist_to_middle = math.dist(wrist, middle_mcp)
        palm_width = math.dist(index_mcp, pinky_mcp)
        palm_scale = max(wrist_to_middle, palm_width, 1e-6)

        raw_distance = math.dist(thumb_tip, index_tip)
        pinch_ratio = raw_distance / palm_scale

        index_tip_reach = math.dist(index_tip, wrist) / palm_scale
        index_mcp_reach = math.dist(index_mcp, wrist) / palm_scale
        index_extended_out = index_tip_reach > (index_mcp_reach * 1.15)

        return {
            "raw_distance": raw_distance,
            "palm_scale": palm_scale,
            "pinch_ratio": pinch_ratio,
            "index_extended_out": index_extended_out,
        }

    def update(self, landmarks, now=None, can_click=True, other_fingers_open=True):
        """Evaluate landmarks using hysteresis and cooldown; return state & click event."""
        now = time.monotonic() if now is None else now
        self.total_updates += 1

        metrics = self.compute_pinch_metrics(landmarks)
        if metrics is None:
            self.reset_state()
            return {
                "state": "HAND_LOST",
                "is_pinching": False,
                "click_triggered": False,
                "cooldown_blocked": False,
                "pinch_ratio": None,
                "raw_distance": None,
                "palm_scale": None,
                "hysteresis_band": (self.config.enter_ratio, self.config.exit_ratio),
                "false_activations": self.false_activations,
            }

        ratio = metrics["pinch_ratio"]
        self.min_observed_ratio = (
            ratio if self.min_observed_ratio is None else min(self.min_observed_ratio, ratio)
        )
        self.max_observed_ratio = (
            ratio if self.max_observed_ratio is None else max(self.max_observed_ratio, ratio)
        )

        # Prevent closed fist from triggering pinch
        reach_valid = other_fingers_open or metrics["index_extended_out"]

        click_triggered = False
        cooldown_blocked = False

        if self.is_pinching:
            if ratio >= self.config.exit_ratio:
                self.is_pinching = False
                self._enter_streak = 0
                self.transitions += 1
            elif self.config.enter_ratio < ratio < self.config.exit_ratio:
                self.hysteresis_holds += 1
        else:
            if ratio <= self.config.enter_ratio:
                if not reach_valid:
                    self._enter_streak = 0
                    self._record_false_activation("closed_fist_reach_guard")
                else:
                    self._enter_streak += 1
                    if self._enter_streak >= self.config.min_confirm_frames:
                        self.is_pinching = True
                        self._enter_streak = 0
                        self.transitions += 1

                        if can_click:
                            if (now - self.last_click_at) >= self.config.cooldown_seconds:
                                click_triggered = True
                                self.last_click_at = now
                                self.successful_clicks += 1
                            else:
                                cooldown_blocked = True
                                self.cooldown_suppressed += 1
            else:
                if self._enter_streak > 0:
                    self._record_false_activation("brief_dip_below_confirm_frames")
                self._enter_streak = 0

        return {
            "state": "PINCHING" if self.is_pinching else "OPEN",
            "is_pinching": self.is_pinching,
            "click_triggered": click_triggered,
            "cooldown_blocked": cooldown_blocked,
            "pinch_ratio": round(ratio, 4),
            "raw_distance": round(metrics["raw_distance"], 4),
            "palm_scale": round(metrics["palm_scale"], 4),
            "hysteresis_band": (self.config.enter_ratio, self.config.exit_ratio),
            "false_activations": self.false_activations,
        }

    def record_sample(self, label, landmarks):
        """Record an empirical open/pinch landmark sample for threshold calibration."""
        label = label.strip().lower()
        if label not in ("open", "pinch"):
            raise ValueError("label must be 'open' or 'pinch'")

        metrics = self.compute_pinch_metrics(landmarks)
        if metrics is None:
            return None

        ratio = metrics["pinch_ratio"]
        if label == "open":
            self.open_samples.append(ratio)
        else:
            self.pinch_samples.append(ratio)
        return ratio

    def calibrate_from_samples(self, min_samples_per_class=10):
        """Compute empirical enter/exit thresholds only when sufficient samples exist."""
        if (
            len(self.open_samples) < min_samples_per_class
            or len(self.pinch_samples) < min_samples_per_class
        ):
            raise ValueError(
                f"Need at least {min_samples_per_class} open and {min_samples_per_class} pinch samples; "
                f"have open={len(self.open_samples)}, pinch={len(self.pinch_samples)}"
            )

        pinch_max = max(self.pinch_samples)
        open_min = min(self.open_samples)
        pinch_mean = sum(self.pinch_samples) / len(self.pinch_samples)
        open_mean = sum(self.open_samples) / len(self.open_samples)

        if pinch_mean >= open_mean:
            raise ValueError(
                f"Invalid calibration data: pinch_mean ({pinch_mean:.3f}) >= open_mean ({open_mean:.3f})"
            )

        midpoint = (pinch_mean + open_mean) / 2.0
        enter_ratio = round(min(midpoint * 0.90, max(pinch_max * 1.05, pinch_mean + 0.04)), 3)
        exit_ratio = round(max(enter_ratio + 0.08, min(open_min * 0.95, midpoint * 1.15)), 3)

        enter_ratio = max(0.10, min(0.80, enter_ratio))
        exit_ratio = max(enter_ratio + 0.06, min(1.20, exit_ratio))

        self.config = PinchCalibrationConfig(
            enter_ratio=enter_ratio,
            exit_ratio=exit_ratio,
            cooldown_seconds=self.config.cooldown_seconds,
            min_confirm_frames=self.config.min_confirm_frames,
            min_index_reach_ratio=self.config.min_index_reach_ratio,
            source=f"empirical_{len(self.open_samples)}open_{len(self.pinch_samples)}pinch",
        )
        self.config.validate()
        return self.config

    def stats(self):
        return {
            "config": self.config.to_dict(),
            "total_updates": self.total_updates,
            "successful_clicks": self.successful_clicks,
            "cooldown_suppressed": self.cooldown_suppressed,
            "false_activations": self.false_activations,
            "hysteresis_holds": self.hysteresis_holds,
            "transitions": self.transitions,
            "min_observed_ratio": self.min_observed_ratio,
            "max_observed_ratio": self.max_observed_ratio,
            "open_samples_count": len(self.open_samples),
            "pinch_samples_count": len(self.pinch_samples),
            "false_activation_reasons": list(self.false_activation_reasons),
        }
