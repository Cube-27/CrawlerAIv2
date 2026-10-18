"""The capture enumerations of shared by the `capture` table and the capture bundle."""

from typing import Literal

CaptureMethod = Literal["http", "browser", "api"]
BlockClass = Literal["ok", "blocked", "shell", "not_found", "error"]  #
