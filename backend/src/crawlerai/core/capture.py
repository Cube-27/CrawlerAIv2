"""The capture enumerations of ARCHITECTURE §6, shared by the `capture` table and the capture bundle."""

from typing import Literal

CaptureMethod = Literal["http", "browser", "api"]
BlockClass = Literal["ok", "blocked", "shell", "not_found", "error"]  # ARCHITECTURE §7.1
