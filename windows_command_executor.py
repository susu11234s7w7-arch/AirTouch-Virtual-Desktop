
import ctypes
import shutil
import subprocess
import os
from pathlib import Path


class WindowsCommandExecutor:
    """Execute approved desktop commands on Windows."""

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

    def open_vscode(self):
        """Launch VS Code or display a missing-installation warning."""
        vscode_path = self.find_vscode()

        if not vscode_path:
            self.user32.MessageBoxW(
                0,
                "Visual Studio Code is not installed "
                "or could not be found.",
                "AI Vision Control Center",
                0x30
            )
            return "VSCODE_NOT_FOUND"

        subprocess.Popen([vscode_path])
        return "OPEN_VSCODE executed"


if __name__ == "__main__":
    import sys

    executor = WindowsCommandExecutor()

    if len(sys.argv) != 2:
        print("Usage:")
        print("python windows_command_executor.py minimize")
        print("python windows_command_executor.py vscode")
        raise SystemExit(1)

    command = sys.argv[1].lower()

    if command == "minimize":
        print(executor.minimize_all())

    elif command == "vscode":
        print(executor.open_vscode())

    else:
        print(f"Unknown command: {command}")
        raise SystemExit(1)
