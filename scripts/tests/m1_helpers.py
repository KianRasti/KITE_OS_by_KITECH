from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if sys.platform == "win32":
    BASH_EXE = r"C:\Program Files\Git\bin\bash.exe"
    POWERSHELL_EXE = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
else:
    BASH_EXE = shutil.which("bash") or "bash"
    POWERSHELL_EXE = shutil.which("pwsh") or "pwsh"
