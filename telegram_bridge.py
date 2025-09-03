from __future__ import annotations
import json, threading, asyncio
from typing import Optional, Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from utils import log_once

class TelegramBridge:
    def __init__(self, chat_service, owner_id: int, bot_token: str,
                 forum_chat_id: Optional[int] = None, topics_db: str = "topics.json"):
        self.cs = chat_service
        self.owner_id = int(owner_id)
        self.bot_token = bot_token
        self.forum_chat_id = int(forum_chat_id) if forum_chat_id else None
        self.current_target_key: Optional[str] = None
        self.app = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.topics_db = topics_db
        self.topics: Dict[str, int] = self._load_topics()
        self.topic_to_friend: Dict[int, str] = {}
        self._rebuild_reverse_index()

    def _rebuild_reverse_index(self):
        topics = getattr(self, "topics", {}) or {}
        self.topic_to_friend = {tid: fk for fk, tid in topics.items() if isinstance(tid, int)}

    def _load_topics(self) -> Dict[str, int]:
        try:
            with open(self.topics_db, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_topics(self):
        try:
            with open(self.topics_db, 'w', encoding='utf-8') as f:
                json.dump(self.topics, f, ensure_ascii=False, indent=2)
            self._rebuild_reverse_index()
        except Exception:
            pass

    def _build(self):
        self.app = ApplicationBuilder().token(self.bot_token).build()
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler(["to", "who", "friends"], self._cmd_router))
        self.app.add_handler(CallbackQueryHandler(self._on_select_friend, pattern=r"^to:"))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))

    def start_in_thread(self):
        def _runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._build()
            log_once("TG", f"loop ready: {id(loop)}")
            self.app.run_polling(allowed_updates=Update.ALL_TYPES)
        threading.Thread(target=_runner, daemon=True).start()
        log_once("TG", "Telegram bridge thread started")

    async def _only_owner(self, update: Update) -> bool:
        if update.effective_user and update.effective_user.id == self.owner_id:
            return True
        try:
            await update.effective_message.reply_text("Yetkin yok.")
        except Exception:
            pass
        return False

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._only_owner(update): return
        await update.message.reply_text("LoL ↔ Telegram köprü aktif. /to <isim>, /friends, /who.")

    async def _cmd_router(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._only_owner(update): return
        cmd = update.message.text.split()[0].lower()

        if cmd == "/who":
            if self.current_target_key:
                name = self.cs.friend_display_name(self.current_target_key)
                await update.message.reply_text(f"Aktif hedef: {name}")
            else:
                await update.message.reply_text("Aktif hedef yok. /to <isim>")
            return

        if cmd == "/to":
            parts = update.message.text.split(" ", 1)
            if len(parts) < 2:
                await update.message.reply_text("Kullanım: /to <kullanıcı-adı>")
                return
            name = parts[1].strip()

            f = None
            for fr in self.cs.list_friends():
                dn = fr.get('name') or fr.get('gameName') or fr.get('displayName') or ''
                if dn.lower() == name.lower(): f = fr; break
            if not f:
                for fr in self.cs.list_friends():
                    dn = fr.get('name') or fr.get('gameName') or fr.get('displayName') or ''
                    if dn.lower().startswith(name.lower()): f = fr; break
            if not f:
                await update.message.reply_text("Arkadaş bulunamadı"); return

            key = (f.get('pid') or '').split('@',1)[0] or (f.get('puuid') or '')
            if not key:
                await update.message.reply_text("Arkadaş anahtarı yok"); return

            self.current_target_key = key
            await update.message.reply_text(f"Hedef: {self.cs.friend_display_name(key)}")
            return

        if cmd == "/friends":
            friends = self.cs.list_friends_online()
            if not friends:
                await update.message.reply_text("Şu an online arkadaş yok."); return
            kb, row = [], []
            for fr in friends:
                dn = self.cs.friend_display_label(fr)
                key = (fr.get('pid') or '').split('@',1)[0] or (fr.get('puuid') or '')
                if not key: continue
                row.append(InlineKeyboardButton(dn[:32], callback_data=f"to:{key}"))
                if len(row)==2: kb.append(row); row=[]
                if len(kb)>=25: break
            if row: kb.append(row)
            await update.message.reply_text("Hedef seç (online):", reply_markup=InlineKeyboardMarkup(kb))
            return

    async def _on_select_friend(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._only_owner(update): return
        key = update.callback_query.data.split(':', 1)[1]
        self.current_target_key = key
        await update.callback_query.answer()
        await update.effective_message.reply_text(f"Hedef: {self.cs.friend_display_name(key)}")

    async def _on_text(self, update, context):
        if not await self._only_owner(update): return
        text = update.message.text
        chat = update.effective_chat
        thread_id = update.effective_message.message_thread_id

        if self.forum_chat_id and chat and chat.id == self.forum_chat_id and thread_id:
            fk = self.topic_to_friend.get(thread_id)
            if fk:
                ok = self.cs.dm_send(fk, text)
                await update.message.reply_text("ME=>YOU gönderildi" if ok else "Gönderilemedi")
                return

        if not self.current_target_key:
            await update.message.reply_text("Önce /to veya /friends ile hedef seç"); return
        ok = self.cs.dm_send(self.current_target_key, text)
        await update.message.reply_text("ME=>YOU gönderildi" if ok else "Gönderilemedi")

    # ---- LoL → Telegram DM akışı ----
    def on_dm_from_lol(self, friend_key: str, friend_name: str, body: str, is_me: bool):
        async def _send():
            text = (f"[ME=>YOU] : {body}" if is_me else f"[YOU=>ME] : {body}")
            await self.app.bot.send_message(chat_id=self.owner_id, text=f"[{friend_name}] {text}")
        if not (self._loop and self.app):
            log_once("TG", "loop not ready; dropping DM"); return
        asyncio.run_coroutine_threadsafe(_send(), self._loop)
