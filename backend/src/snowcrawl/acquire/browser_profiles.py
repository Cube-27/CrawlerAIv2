"""Browser profiles (profiles): the browser
rung renders each site in a Chromium profile of its own, as a user's browser keeps its state, rather than in an
incognito context, which pages can tell apart (a storage quota a fraction of a profile's).

- One profile per site (its registrable domain, HTML Standard §7.1.1), proxy pool and endpoint (`profile_name`), so
  what a site set through one route never goes out through another. The directory is
  named by a digest, never by the host.
- Kept under `SNOWCRAWL_BROWSER_PROFILES`, across jobs and processes; deleting that directory resets every profile. A
  profile is opened by one process at a time, under an OS lock on its `.lock` file that the OS releases when the
  process ends. A profile another process or fetch holds, a fetch with the caller's own cookies (which are no site's
  state), and every fetch when no directory is configured, get a fresh profile in a temporary directory, deleted when
  it closes.
- A kept profile is the browser's cookie store for its site: its cookies, challenge and clearance cookies
  included, are Chromium's own, in plaintext under the operator-managed `SNOWCRAWL_BROWSER_PROFILES`, and nothing
  else writes them. Only a temporary profile of a site starts with the site's live session or encrypted stored cookie
  state, and only its `ok` writes that state (`acquire.session`).
- Before each launch the profile's preferences get Chromium's WebRTC IP handling policy `disable_non_proxied_udp`
  (Chromium `prefs::kWebRTCIPHandlingPolicy`, with non-proxied UDP and multiple routes off), so WebRTC sends no UDP
  around the SSRF guard's SOCKS proxy. Chromium 153 ignores the `--force-webrtc-ip-handling-policy` switch:
  a STUN request still left the machine directly with it.
- Before each launch of a kept profile its HTTP cache and service workers (with their caches) are deleted, so no
  response a page captures is one an earlier job's visit left: a later page reads what the site serves now. Cookies
  and storage stay.
- A profile whose page was refused (`blocked`) is deleted (`discard_profile`), and the refusal drops the site's stored
  cookie state (`acquire.session`): their cookies and storage carry the refusal.
"""

import hashlib
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Final

from snowcrawl.core.proxy import ProxyEndpoint

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

__all__ = ["Profile", "discard_profile", "open_profile", "profile_name"]

# Chromium's preference names (chrome/common/pref_names.h: `webrtc.ip_handling_policy`,
# `webrtc.multiple_routes_enabled`, `webrtc.nonproxied_udp_enabled`), as an enterprise policy or the extensions'
# privacy API sets them.
_WEBRTC: Final = {
    "ip_handling_policy": "disable_non_proxied_udp",
    "multiple_routes_enabled": False,
    "nonproxied_udp_enabled": False,
}
# Chromium's profile layout: the first profile of a user data directory, and its preferences file (JSON).
_PREFERENCES: Final = Path("Default") / "Preferences"
_TEMPORARY_PREFIX: Final = "snowcrawl-profile-"
# The profile's HTTP disk cache and its service workers (registrations, scripts and their Cache Storage), as Chromium
# lays them out in a profile directory; a browser recreates them empty, as in a new profile.
_CACHES: Final = (Path("Default") / "Cache", Path("Default") / "Service Worker")


def profile_name(site: str, pool: str | None, proxy: ProxyEndpoint | None) -> str:
    """The directory name of the profile of `site` through `pool` and its endpoint: a digest, so no host or proxy
    appears on disk; the endpoint's password stays out of it."""
    endpoint = "" if proxy is None else f"{proxy.host}:{proxy.port}:{proxy.username or ''}"
    return hashlib.sha256(f"{site}\n{pool or ''}\n{endpoint}".encode()).hexdigest()[:32]


@dataclass
class Profile:
    """A profile directory to launch in, and the lock this process holds on it (None: a temporary directory)."""

    directory: Path
    lock: IO[bytes] | None
    discarded: bool = False

    def close(self) -> None:
        """Release the profile; a temporary or discarded one is deleted first, while its lock is still held."""
        if self.lock is None or self.discarded:
            shutil.rmtree(self.directory, ignore_errors=True)
        if self.lock is not None:
            self.lock.close()


def open_profile(root: Path | None, name: str | None) -> Profile:
    """The named profile under `root` when this process can lock it, its caches emptied, else a temporary one; its
    WebRTC policy set."""
    lock = None if root is None or name is None else _locked(root, name)
    if root is not None and name is not None and lock is not None:
        profile = Profile(root / name, lock)
    else:
        profile = Profile(Path(tempfile.mkdtemp(prefix=_TEMPORARY_PREFIX)), None)
    try:
        if profile.lock is not None:
            for cache in _CACHES:
                shutil.rmtree(profile.directory / cache, ignore_errors=True)
        _set_webrtc_policy(profile.directory)
    except BaseException:  # any failure releases the lock, as no caller holds the profile yet
        profile.close()
        raise
    return profile


def discard_profile(root: Path | None, name: str) -> None:
    """Delete the named profile under `root`, unless a process (this one too) holds it open."""
    if root is None:
        return
    lock = _locked(root, name)
    if lock is not None:
        Profile(root / name, lock, discarded=True).close()


def _locked(root: Path, name: str) -> IO[bytes] | None:
    """The profile's lock file, locked by this open file (`flock` on POSIX, `msvcrt.locking` on Windows); None
    when another open file holds it, in this process or another."""
    root.mkdir(parents=True, exist_ok=True)
    handle = (root / f"{name}.lock").open("a+b")
    try:
        if sys.platform == "win32":
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _set_webrtc_policy(directory: Path) -> None:
    """Write the WebRTC policy into the profile's preferences, keeping every other preference Chromium wrote."""
    path = directory / _PREFERENCES
    try:
        preferences = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        preferences = {}
    if not isinstance(preferences, dict):
        preferences = {}
    webrtc = preferences.get("webrtc")
    preferences["webrtc"] = {**(webrtc if isinstance(webrtc, dict) else {}), **_WEBRTC}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(preferences), encoding="utf-8")
