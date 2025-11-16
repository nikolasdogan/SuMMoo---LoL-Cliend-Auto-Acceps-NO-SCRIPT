# main_telegram.py
import os, time, threading
from lcu_session import LcuSession
from chat_service import ChatService
from telegram_bridge import TelegramBridge

BOT = os.getenv("TELEGRAM_BOT_TOKEN", "")
OWNER = int(os.getenv("TELEGRAM_OWNER_ID", "0") or 0)
FORUM = os.getenv("TELEGRAM_FORUM_ID", "-CHAR_ID")  # opsiyonel

if not BOT or not OWNER:
    raise SystemExit("TELEGRAM_BOT_TOKEN ve TELEGRAM_OWNER_ID gerekli.")

lcu = LcuSession()
cs = ChatService(lcu)
cs.refresh_me()

tb = TelegramBridge(cs, owner_id=OWNER, bot_token=BOT, forum_chat_id=(int(FORUM) if FORUM else None))
tb.start_in_thread()

# *** KRİTİK ***: DM watcher'ı kesinlikle başlat
threading.Thread(target=cs.watch_dms, args=(tb.on_dm_from_lol,), daemon=True).start()

print("Bridge çalışıyor. Telegram’da /start, /friends veya /to <isim> ile hedef seç.")
try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    pass
