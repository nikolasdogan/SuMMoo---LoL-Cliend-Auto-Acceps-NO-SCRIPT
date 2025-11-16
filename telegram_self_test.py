"""Telegram köprüsü için dıştan tetikleme (smoke test) aracıdır.

Kullanım:
    TELEGRAM_BOT_TOKEN=... TELEGRAM_OWNER_ID=... python telegram_self_test.py --requester Summoo
"""
from __future__ import annotations
import argparse
import os
import time
import uuid
from typing import Optional, List, Dict, Any

from telegram_bridge import TelegramBridge


class DummyChatService:
    """TelegramBridge'in ihtiyaç duyduğu temel metotları sağlayan hafif sahte servis."""

    def friend_display_name(self, key: Optional[str]) -> str:
        return key or "?"

    def friend_display_label(self, friend: Dict[str, Any]) -> str:
        return friend.get("name") or friend.get("gameName") or friend.get("displayName") or "?"

    def list_friends(self) -> List[Dict[str, Any]]:
        return []

    def list_friends_online(self) -> List[Dict[str, Any]]:
        return []

    def dm_send(self, *_, **__) -> bool:
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Telegram köprüsünü LoL istemcisine ihtiyaç duymadan test et")
    parser.add_argument(
        "--requester",
        default="TestSummoner",
        help="Bildirimde görünecek davetçi adı",
    )
    parser.add_argument(
        "--availability",
        default="busy",
        help="Mesajda kullanılacak durum bilgisi (busy/idle/away)",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=90,
        help="Onay/ret sonucunu beklerken saniye cinsinden bloklama süresi",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    owner_id = os.getenv("TELEGRAM_OWNER_ID")
    forum_id = os.getenv("TELEGRAM_FORUM_ID")

    if not bot_token or not owner_id:
        raise SystemExit("TELEGRAM_BOT_TOKEN ve TELEGRAM_OWNER_ID olmadan test gönderilemez.")

    dummy = DummyChatService()
    bridge = TelegramBridge(
        dummy,
        owner_id=int(owner_id),
        bot_token=bot_token,
        forum_chat_id=int(forum_id) if forum_id else None,
    )
    bridge.start_in_thread()
    if not bridge.wait_until_ready(10.0):
        raise SystemExit("Telegram bot 10 sn içinde hazır hale gelmedi.")

    req_id = f"selftest-{uuid.uuid4().hex[:8]}"
    print(f"Telegram'a test BASLAT isteği gönderiliyor (request_id={req_id}).")

    result_holder = {"done": False, "approved": None}

    def _cb(approved: bool):
        result_holder["done"] = True
        result_holder["approved"] = approved
        print("Telegram yanıtı alındı:", "ONAY" if approved else "RED")

    ok = bridge.request_start_confirmation(
        request_id=req_id,
        requester=args.requester,
        availability=args.availability,
        callback=_cb,
    )
    if not ok:
        raise SystemExit("Telegram'a istek gönderilemedi. Bot token / owner id kontrol et.")

    timeout = time.time() + max(args.wait, 5)
    print("Yanıt bekleniyor… Telegram'da gelen bildirimi onay/ret et.")
    try:
        while time.time() < timeout and not result_holder["done"]:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    if not result_holder["done"]:
        print("Belirtilen sürede yanıt alınamadı (timeout).")
    else:
        print("Test tamamlandı. Sonuç terminalde görülebilir.")


if __name__ == "__main__":
    main()
