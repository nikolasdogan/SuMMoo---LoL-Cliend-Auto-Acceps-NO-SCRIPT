from __future__ import annotations
import os, base64, requests, urllib3
from typing import Optional, Tuple
from utils import log_once

urllib3.disable_warnings()

LOCKFILE_GUESSES = [
    r"C:\\Riot Games\\League of Legends\\lockfile",
    os.path.expandvars(r"%LOCALAPPDATA%\\Riot Games\\Riot Client\\Config\\lockfile"),
]

class LcuSession:
    def __init__(self) -> None:
        self._tuple: Optional[Tuple[str,str,str,str]] = None  # (pid, port, pw, proto)
        self._sess: Optional[requests.Session] = None
        self._base: Optional[str] = None

    def _read_lockfile(self) -> Optional[str]:
        for p in LOCKFILE_GUESSES:
            if os.path.exists(p):
                return p
        return None

    def get(self) -> tuple[Optional[requests.Session], Optional[str]]:
        p = self._read_lockfile()
        if not p:
            return None, None
        try:
            with open(p, "r", encoding="utf-8") as f:
                name, pid, port, pw, proto = f.read().split(":")
            cur = (pid, port, pw, proto.strip())
            if self._tuple == cur and self._sess is not None:
                return self._sess, self._base
            b64 = base64.b64encode(f"riot:{pw}".encode()).decode()
            s = requests.Session(); s.verify = False
            s.headers.update({"Authorization": f"Basic {b64}"})
            base = f"https://127.0.0.1:{port}"
            self._tuple, self._sess, self._base = cur, s, base
            log_once("LCU", f"lockfile bulundu: port={port} proto={proto.strip()} pid={pid}")
            return s, base
        except Exception:
            return None, None
