"""One-shot gesture commands for the native desktop dock."""

import time


class GestureCommandController:
    """Map stabilized hand gestures to safe desktop actions.

    Overlay visibility commands are consumed by ``DesktopOverlayController``.
    App selection is handled by the index-finger hover timer. Other gestures do
    not directly launch applications.
    """

    def __init__(self, sequence_timeout=3.5):
        # Kept for compatibility with callers that still configure this value.
        self.sequence_timeout = float(sequence_timeout)
        self.reset()

    def reset(self):
        self.armed = True
        self.previous_gesture = "UNKNOWN"
        self.sequence_started_at = None
        self.last_command = None

    def process(self, gesture, now=None):
        if not isinstance(gesture, str):
            raise TypeError("gesture must be a string")

        gesture = gesture.strip().upper()
        now = time.monotonic() if now is None else now
        result = {
            "gesture": gesture,
            "command": None,
            "executed": False,
            "message": "No action",
        }

        if gesture == "UNKNOWN":
            self.armed = True
            self.previous_gesture = gesture
            self.sequence_started_at = None
            result["message"] = "Safe neutral state - controller ready"
            return result

        if gesture == "OPEN_PALM":
            result.update(
                command="SHOW_OVERLAY",
                executed=True,
                message="Desktop overlay shown",
            )
            self.last_command = "SHOW_OVERLAY"
        elif gesture == "FIST":
            result.update(
                command="HIDE_OVERLAY",
                executed=True,
                message="Desktop overlay hidden",
            )
            self.last_command = "HIDE_OVERLAY"
        elif gesture == "PEACE":
            result["message"] = "Use POINTING to hover over an application"
        elif gesture == "POINTING":
            result["message"] = "Desktop air cursor active when overlay is visible"
        elif gesture == "PINCH":
            result["message"] = "PINCH does not activate desktop applications"
        elif gesture == "THUMBS_UP":
            result["message"] = "Confirmed - System Ready"
        else:
            result["message"] = "Gesture not assigned"

        self.previous_gesture = gesture
        self.sequence_started_at = None
        return result
