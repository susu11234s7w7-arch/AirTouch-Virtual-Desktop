"""Debounce consecutive raw gesture labels into stable interaction events."""


GESTURE_STABILIZATION = {
    "OPEN_PALM": {"frames": 2, "seconds": 0.020},
    "FIST": {"frames": 2, "seconds": 0.020},
    "PEACE": {"frames": 2, "seconds": 0.020},
    "POINTING": {"frames": 2, "seconds": 0.020},
    "PINCH": {"frames": 2, "seconds": 0.015},
    "THUMBS_UP": {"frames": 2, "seconds": 0.020},
    "UNKNOWN": {"frames": 3, "seconds": 0.090},
}


class GestureStabilizer:
    """Per-gesture debounce that ignores brief classification flicker."""

    def __init__(self, settings=None):
        self.settings = settings or GESTURE_STABILIZATION
        self.candidate = "UNKNOWN"
        self.candidate_count = 0
        self.candidate_since = None
        self.stable_gesture = "UNKNOWN"

    def update(self, raw_gesture, now):
        raw_gesture = (
            raw_gesture.strip().upper()
            if isinstance(raw_gesture, str)
            else "UNKNOWN"
        )
        if raw_gesture not in self.settings:
            raw_gesture = "UNKNOWN"

        if raw_gesture == self.candidate:
            if self.candidate_since is None:
                self.candidate_since = now
            self.candidate_count += 1
        else:
            self.candidate = raw_gesture
            self.candidate_count = 1
            self.candidate_since = now

        threshold = self.settings[raw_gesture]
        elapsed = (
            now - self.candidate_since
            if self.candidate_since is not None
            else 0.0
        )
        accepted = (
            self.candidate_count >= threshold["frames"]
            and elapsed >= threshold["seconds"]
        )
        changed = False
        if accepted and self.stable_gesture != self.candidate:
            self.stable_gesture = self.candidate
            changed = True

        return {
            "stable_gesture": self.stable_gesture,
            "changed": changed,
            "candidate": self.candidate,
            "candidate_count": self.candidate_count,
            "required_frames": threshold["frames"],
            "elapsed": elapsed,
        }
