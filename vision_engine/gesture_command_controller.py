
import time

class GestureCommandController:
    def __init__(self, sequence_timeout=2.0):
        self.sequence_timeout = sequence_timeout
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
            "message": "No action"
        }

        if gesture == "UNKNOWN":
            self.armed = True
            self.sequence_started_at = None
            self.previous_gesture = "UNKNOWN"
            result["message"] = "Controller re-armed"
            return result

        if not self.armed:
            result["message"] = "Waiting for neutral gesture"
            self.previous_gesture = gesture
            return result

        if gesture == "OPEN_PALM":
            if self.sequence_started_at is None:
                self.sequence_started_at = now
                result["message"] = "Sequence candidate"
            self.previous_gesture = gesture
            return result

        if gesture == "FIST":
            if self.sequence_started_at is not None:
                elapsed = now - self.sequence_started_at
                if 0 <= elapsed <= self.sequence_timeout:
                    result["command"] = "MINIMIZE_ALL"
                    result["executed"] = True
                    result["message"] = "WIN + D requested"
                    self.armed = False
                    self.last_command = "MINIMIZE_ALL"
                else:
                    result["message"] = "Sequence expired"
                self.sequence_started_at = None
            self.previous_gesture = gesture
            return result

        if gesture == "PEACE":
            result["command"] = "OPEN_VSCODE"
            result["executed"] = True
            result["message"] = "VS Code launch requested"
            self.armed = False
            self.last_command = "OPEN_VSCODE"
            self.sequence_started_at = None
            self.previous_gesture = gesture
            return result

        self.sequence_started_at = None
        self.previous_gesture = gesture
        result["message"] = "Gesture not assigned"
        return result
