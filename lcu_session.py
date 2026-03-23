from __future__ import annotations
import os, base64, re, requests, urllib3
from typing import Optional, Tuple
from utils import log_once

urllib3.disable_warnings()

# ---------------------------------------------------------------------------
# Lockfile path candidates (Windows-centric; additive, checked in order).
# Drive-letter glob covers custom installs on D:, E:, F:, etc.
# ---------------------------------------------------------------------------
def _build_lockfile_guesses() -> list[str]:
    paths: list[str] = []

    # Standard Riot / Riot Client locations on common drive letters
    for drive in "CDEF":
        paths.append(rf"{drive}:\Riot Games\League of Legends\lockfile")
        paths.append(rf"{drive}:\Riot Games\Riot Client\Config\lockfile")

    # %LOCALAPPDATA% — most common on default installs
    paths.append(os.path.expandvars(r"%LOCALAPPDATA%\Riot Games\League of Legends\lockfile"))
    paths.append(os.path.expandvars(r"%LOCALAPPDATA%\Riot Games\Riot Client\Config\lockfile"))

    # %ProgramFiles% / %ProgramFiles(x86)%
    paths.append(os.path.expandvars(r"%ProgramFiles%\Riot Games\League of Legends\lockfile"))
    paths.append(os.path.expandvars(r"%ProgramFiles(x86)%\Riot Games\League of Legends\lockfile"))

    # Linux / macOS / Wine / Lutris paths
    home = os.path.expanduser("~")
    paths += [
        f"{home}/.local/share/lutris/runners/wine/League of Legends/drive_c/Riot Games/League of Legends/lockfile",
        "/opt/wine/drive_c/Riot Games/League of Legends/lockfile",
        f"{home}/Games/league-of-legends/drive_c/Riot Games/League of Legends/lockfile",
    ]

    return paths


LOCKFILE_GUESSES: list[str] = _build_lockfile_guesses()

# Regex for extracting port/token from LeagueClientUx process args
_RE_PORT  = re.compile(r"--app-port=(\d+)")
_RE_TOKEN = re.compile(r"--remoting-auth-token=([^\s]+)")


def _discover_via_process() -> Optional[Tuple[str, str]]:
    """Return (port, token) by inspecting the LeagueClientUx process args.

    Uses psutil (already in requirements.txt). Falls through to None on any
    error (permissions, process gone, psutil unavailable, etc.).
    """
    try:
        import psutil  # local import — avoids hard dep at module load time
    except ImportError:
        return None

    target_names = {"leagueclientux.exe", "leagueclientux"}
    try:
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name not in target_names:
                    continue
                cmdline = proc.info.get("cmdline") or []
                args = " ".join(cmdline)
                m_port  = _RE_PORT.search(args)
                m_token = _RE_TOKEN.search(args)
                if m_port and m_token:
                    return m_port.group(1), m_token.group(1)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return None


class LcuSession:
    def __init__(self) -> None:
        self._tuple: Optional[Tuple[str, str, str, str]] = None  # (pid, port, pw, proto)
        self._sess: Optional[requests.Session] = None
        self._base: Optional[str] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_lockfile(self) -> Optional[str]:
        """Return the path of the first existing lockfile candidate, or None."""
        # 1. Env-var override — highest priority, skips all discovery
        env_path = os.environ.get("LOCKFILE_PATH", "").strip()
        if env_path:
            if os.path.exists(env_path):
                log_once("LCU", f"LOCKFILE_PATH env override kullanıldı: {env_path}")
                return env_path
            log_once("LCU", f"LOCKFILE_PATH env override mevcut değil: {env_path}")

        # 2. Static path list
        for p in LOCKFILE_GUESSES:
            if os.path.exists(p):
                log_once("LCU", f"lockfile bulundu (static liste): {p}")
                return p

        return None

    def _build_session(self, port: str, pw: str, proto: str) -> tuple[requests.Session, str]:
        b64 = base64.b64encode(f"riot:{pw}".encode()).decode()
        s = requests.Session()
        s.verify = False
        s.headers.update({"Authorization": f"Basic {b64}"})
        base = f"https://127.0.0.1:{port}"
        return s, base

    # ------------------------------------------------------------------
    # Public API — signature unchanged
    # ------------------------------------------------------------------

    def get(self) -> tuple[Optional[requests.Session], Optional[str]]:
        # --- Path 1: lockfile on disk ---
        p = self._read_lockfile()
        if p:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    name, pid, port, pw, proto = f.read().split(":")
                cur = (pid, port, pw, proto.strip())
                if self._tuple == cur and self._sess is not None:
                    return self._sess, self._base
                s, base = self._build_session(port, pw, proto.strip())
                self._tuple, self._sess, self._base = cur, s, base
                log_once("LCU", f"lockfile: port={port} proto={proto.strip()} pid={pid}")
                return s, base
            except Exception:
                pass

        # --- Path 2: process-based discovery via psutil ---
        result = _discover_via_process()
        if result:
            port, token = result
            cur = ("proc", port, token, "https")
            if self._tuple == cur and self._sess is not None:
                return self._sess, self._base
            s, base = self._build_session(port, token, "https")
            self._tuple, self._sess, self._base = cur, s, base
            log_once("LCU", f"process discovery: port={port} (LeagueClientUx args)")
            return s, base

        return None, None
