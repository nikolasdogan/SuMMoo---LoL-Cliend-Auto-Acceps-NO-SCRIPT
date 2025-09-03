import time, random
import pyautogui as pag
import pygetwindow as gw

CONFIDENCE = 0.86
AS_ACCEPT = "assets/accept_button.png"
AS_FIND = "assets/ara_button.png"
WINDOW_TITLES = ["League of Legends", "Riot Client"]

state = {"active": False, "stop": False, "last_click": 0.0}

def bring_front():
    for t in WINDOW_TITLES:
        ws = [w for w in gw.getWindowsWithTitle(t) if w.isVisible]
        if ws:
            w = ws[0]
            try:
                if w.isMinimized: w.restore()
                w.activate(); time.sleep(0.2); return True
            except Exception:
                pass
    return False

def click_img(path):
    try:
        loc = pag.locateCenterOnScreen(path, confidence=CONFIDENCE, grayscale=True)
        if loc:
            x = loc.x + random.randint(-2, 2)
            y = loc.y + random.randint(-2, 2)
            pag.moveTo(x, y, duration=random.uniform(0.10, 0.25))
            pag.click(); return True
    except Exception:
        pass
    return False

def clicker_worker():
    while not state["stop"]:
        time.sleep(random.uniform(1.1, 2.1))
        if not state["active"]: continue
        bring_front()
        now = time.time()
        if now - state["last_click"] > 3.5 and click_img(AS_ACCEPT):
            state["last_click"] = now; continue
        if now - state["last_click"] > 3.5 and click_img(AS_FIND):
            state["last_click"] = now; continue
