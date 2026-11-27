"""One-shot mouse click detector for a middle-finger lift-and-lower tap."""


class MiddleFingerClickDetector:
    """Recognize a short middle-finger pulse while the index is pointing.

    A tap must start from a stable POINTING pose (index extended, middle,
    ring, and pinky curled), hold the middle finger up for two frames, then
    return it for two frames. A held PEACE pose never clicks.
    """

    def __init__(
        self,
        baseline_frames=2,
        rise_frames=2,
        lower_frames=2,
        min_press_seconds=0.045,
        max_press_seconds=0.8,
        cooldown_seconds=0.35,
    ):
        self.baseline_frames = max(1, int(baseline_frames))
        self.rise_frames = max(1, int(rise_frames))
        self.lower_frames = max(1, int(lower_frames))
        self.min_press_seconds = max(0.0, float(min_press_seconds))
        self.max_press_seconds = max(
            self.min_press_seconds, float(max_press_seconds)
        )
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.reset()

    def reset(self):
        self.armed = False
        self.pointing_frames = 0
        self.phase = "WAIT_POINTING"
        self.rise_frames_seen = 0
        self.lower_frames_seen = 0
        self.press_started_at = None
        self.last_click_at = -1e9

    def _cancel_tap(self):
        self.armed = False
        self.pointing_frames = 0
        self.phase = "WAIT_POINTING"
        self.rise_frames_seen = 0
        self.lower_frames_seen = 0
        self.press_started_at = None

    def update(self, finger_states, tracking_available=True, now=0.0):
        """Return a single click event only after a valid middle-finger tap."""
        now = float(now)
        if not tracking_available or not isinstance(finger_states, dict):
            self._cancel_tap()
            return {"click_triggered": False, "press_active": False}

        index = bool(finger_states.get("index", False))
        middle = bool(finger_states.get("middle", False))
        ring = bool(finger_states.get("ring", False))
        pinky = bool(finger_states.get("pinky", False))

        # Only the pointing/peace pair is accepted; the thumb does not matter.
        if not index or ring or pinky:
            self._cancel_tap()
            return {"click_triggered": False, "press_active": False}

        if middle:
            self.pointing_frames = 0
            if self.phase == "WAIT_POINTING":
                if self.armed:
                    self.phase = "RAISING"
                    self.rise_frames_seen = 1
                    self.press_started_at = now
                return {"click_triggered": False, "press_active": False}

            if self.phase == "RAISING":
                self.rise_frames_seen += 1
                if self.rise_frames_seen >= self.rise_frames:
                    self.phase = "RAISED"
                return {
                    "click_triggered": False,
                    "press_active": self.phase == "RAISED",
                }

            if self.phase == "RAISED":
                if now - self.press_started_at > self.max_press_seconds:
                    self._cancel_tap()
                    return {"click_triggered": False, "press_active": False}
                return {"click_triggered": False, "press_active": True}

            if self.phase == "LOWERING":
                # A fresh lift before the lower phase completed cancels the tap.
                self._cancel_tap()
                return {"click_triggered": False, "press_active": False}

        # The middle finger is down. Count the return phase and click once.
        if self.phase == "RAISING":
            self._cancel_tap()
        elif self.phase == "RAISED":
            self.phase = "LOWERING"
            self.lower_frames_seen = 1
            return {"click_triggered": False, "press_active": True}
        elif self.phase == "LOWERING":
            self.lower_frames_seen += 1
            elapsed = now - self.press_started_at
            if self.lower_frames_seen >= self.lower_frames:
                valid_duration = (
                    self.min_press_seconds <= elapsed <= self.max_press_seconds
                )
                cooldown_elapsed = now - self.last_click_at
                triggered = valid_duration and cooldown_elapsed >= self.cooldown_seconds
                if triggered:
                    self.last_click_at = now
                self._cancel_tap()
                return {"click_triggered": triggered, "press_active": False}
            return {"click_triggered": False, "press_active": True}

        self.pointing_frames += 1
        if self.pointing_frames >= self.baseline_frames:
            self.armed = True
            self.phase = "WAIT_POINTING"
        return {"click_triggered": False, "press_active": False}
