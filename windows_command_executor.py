import ctypes
import os
import shutil
import subprocess
from pathlib import Path


class WindowsCommandExecutor:
    """Execute explicitly approved desktop and application commands on Windows."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("This executor supports Windows only.")

        self.user32 = ctypes.windll.user32

    def minimize_all(self):
        """Send Win + D to show the Windows desktop."""
        VK_LWIN = 0x5B
        VK_D = 0x44
        KEYUP = 0x0002

        self.user32.keybd_event(VK_LWIN, 0, 0, 0)
        self.user32.keybd_event(VK_D, 0, 0, 0)
        self.user32.keybd_event(VK_D, 0, KEYUP, 0)
        self.user32.keybd_event(VK_LWIN, 0, KEYUP, 0)

        return "MINIMIZE_ALL executed"

    def find_vscode(self):
        """Find the Visual Studio Code executable."""
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Programs/Microsoft VS Code/Code.exe",
            Path(os.environ.get("ProgramFiles", ""))
            / "Microsoft VS Code/Code.exe",
            Path(os.environ.get("ProgramFiles(x86)", ""))
            / "Microsoft VS Code/Code.exe",
        ]

        for path in candidates:
            if path.is_file():
                return str(path)

        return shutil.which("code")

    def _launch_system_app(self, executable, command_name):
        """Launch a standard Windows executable via subprocess."""
        subprocess.Popen([executable])
        return f"{command_name} executed"

    def open_vscode(self):
        """Launch VS Code or display a missing-installation warning."""
        vscode_path = self.find_vscode()

        if not vscode_path:
            self.user32.MessageBoxW(
                0,
                "Visual Studio Code is not installed or could not be found.",
                "AirTouch Virtual Desktop",
                0x30,
            )
            return "VSCODE_NOT_FOUND"

        return self._launch_system_app(vscode_path, "OPEN_VSCODE")

    def open_explorer(self):
        """Launch Windows File Explorer."""
        return self._launch_system_app("explorer.exe", "OPEN_EXPLORER")

    def open_calculator(self):
        """Launch Windows Calculator."""
        return self._launch_system_app("calc.exe", "OPEN_CALCULATOR")

    def open_notepad(self):
        """Launch Windows Notepad."""
        return self._launch_system_app("notepad.exe", "OPEN_NOTEPAD")


if __name__ == "__main__":
    import sys

    executor = WindowsCommandExecutor()

    cli_actions = {
        "minimize": executor.minimize_all,
        "vscode": executor.open_vscode,
        "explorer": executor.open_explorer,
        "calculator": executor.open_calculator,
        "notepad": executor.open_notepad,
    }

    if len(sys.argv) != 2:
        print("Usage:")
        for key in cli_actions:
            print(f"python windows_command_executor.py {key}")
        raise SystemExit(1)

    command = sys.argv[1].lower()
    action = cli_actions.get(command)
    if action is None:
        print(f"Unknown command: {command}")
        raise SystemExit(1)

    print(action())
