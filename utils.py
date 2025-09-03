from __future__ import annotations
import time
from datetime import datetime

ASCII_LOGO = r"""
 _      _                   _             _        _         
| |    | |                 | |           | |      | |        
| | ___| | __ _  ___   ___ | | __   ___  | |  ___ | |_  ___  
| |/ __| |/ _` |/ __| / _ \| |/ /  / _ \ | | / _ \| __|/ _ \
| | (__| | (_| |\__ \|  __/|   <  | (_) || ||  __/| |_| (_) |
|_|\___|_|\__,_||___/ \___||_|\_\  \___/ |_| \___| \__|\___/
"""

def log_once(tag: str, text: str) -> None:
    print(f"[{tag}] {text}")

def parse_ts_iso(ts: str | None) -> float:
    if not ts:
        return time.time()
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).timestamp()
    except Exception:
        return time.time()

def status_tag(avail: str | None) -> str:
    a = (avail or "").lower()
    if a in ("chat","online","available","ingame","in_game","inchampselect","inlobby","in_lobby"):
        return "[ON]"
    if a in ("dnd","busy","away","mobile"):
        return "[BSY]"
    return "[OFF]"
