from __future__ import annotations
import sys, threading, time, os, importlib.util
from typing import Optional, Callable
from utils import log_once, ASCII_LOGO
from lcu_session import LcuSession
from chat_service import ChatService
def _ensure_dependency(module: str, package_hint: str = "") -> None:
    if importlib.util.find_spec(module) is None:
        hint = f" (örn. {package_hint})" if package_hint else ""
        sys.stderr.write(
            f"Gerekli '{module}' modülü bulunamadı{hint}.\n"
            "Lütfen 'pip install -r requirements.txt' komutunu çalıştırın veya modülü manuel olarak yükleyin.\n"
        )
        sys.exit(1)


_ensure_dependency("pynput", "pip install pynput")
from pynput import keyboard
from telegram_bridge import TelegramBridge

IS_WINDOWS = os.name == "nt"
CLICKER_AVAILABLE = IS_WINDOWS

if IS_WINDOWS:
    from ui_clicker import clicker_worker, state as CLICK_STATE
else:
    CLICK_STATE = {"active": False}

    def clicker_worker():
        """No-op clicker for non-Windows platforms."""
        log_once("CLICK", "UI clicker devre dışı (yalnızca Windows).")

# ------------ Yardım ------------
def _print_help():
    print(
        "Komutlar:\n"
        "  /friends | /online-friend | /offline-friend\n"
        "  /chat-groups | /chat-group <ad|id> | /group-log | /sayg <mesaj>\n"
        "  /dm <kisi> <mesaj> | /dm-log <kisi>\n"
        "  /geo | /geo-json\n"
        "  /auto-ready [on|off]\n"
        "  /auto-pick [on|off|Ahri,Annie,...]\n"
        "  /auto-pick-lock [on|off]\n"
        "  /announce [on|off] | /silent-group [on|off] | /quiet [on|off]\n"
        "  /sayl <mesaj>  (lobiye yaz)\n"
        "  status | exit | help"
    )

# ------------ Acil durdurma ------------
def emergency_hotkey(stop_flag: dict):
    COMBO = {keyboard.Key.ctrl_l, keyboard.Key.shift, keyboard.KeyCode.from_char('q')}
    pressed = set()
    def on_press(k):
        pressed.add(k)
        if all(x in pressed for x in COMBO):
            stop_flag['stop'] = True
    def on_release(k):
        if k in pressed: pressed.remove(k)
    with keyboard.Listener(on_press=on_press, on_release=on_release) as L:
        L.join()

# ------------ Paylaşılan lobi / DM komutları ------------
def handle_party_management_command(
    cs: ChatService,
    txt: str,
    from_name: str,
    send_feedback: Callable[[str], None],
    *,
    context: str = "group",
    sender_puuid: Optional[str] = None,
) -> bool:
    text = (txt or "").strip()
    if not text:
        return False
    low = text.lower()

    def reply(msg: str):
        if send_feedback and msg:
            send_feedback(msg)

    # BASLAT / START
    if low in ("baslat", "start", "/l"):
        log_once("GRP-CMD", f"{from_name} → BASLAT")
        if context == "dm" and not cs.is_puuid_in_lobby(sender_puuid):
            reply("lobbye katilmadiginiz icin oyun baslatma yetkini bulunmamaktadir")
            return True
        if cs.is_party_leader():
            reply("Matchmaking başlatılıyor…")
            ok = cs.start_matchmaking()
            log_once("QUEUE", f"START_CALL={'OK' if ok else 'FAIL'}")
        else:
            reply(f"{from_name} başlat dedi ama lider değilim.")
        return True

    # BAN <isim>
    if low.startswith("ban "):
        target = text.split(" ", 1)[1].strip()
        log_once("GRP-CMD", f"{from_name} → BAN \"{target}\"")
        if not cs.is_party_leader():
            reply(f"{from_name} ban istedi ama lider değilim.")
            return True
        m = cs.find_member_by_name(target)
        if not m:
            reply(f'Kullanıcı bulunamadı: "{target}"')
            return True
        ok = cs.kick_member_by_id(m.get("summonerId"))
        reply(
            f'{m.get("summonerName")} lobiden atıldı.' if ok else "Ban başarısız."
        )
        return True

    # ODADEVRET [isim]
    if low.startswith("odadevret"):
        parts = text.split(" ", 1)
        target = parts[1].strip() if len(parts) == 2 else (from_name or "")
        log_once("GRP-CMD", f"{from_name} → ODADEVRET \"{target}\"")
        if not cs.is_party_leader():
            reply(f"{from_name} devir istedi ama lider değilim.")
            return True
        if not target:
            reply("ODADEVRET için hedef yok.")
            return True
        m = cs.find_member_by_name(target)
        if not m:
            reply(f'Liderlik devri için kullanıcı yok: "{target}"')
            return True
        ok = cs.promote_member_by_id(m.get("summonerId"))
        reply(
            f'Liderlik {m.get("summonerName")} kullanıcısına devredildi.'
            if ok
            else "Devir başarısız."
        )
        return True

    return False


def handle_dm_party_command(cs: ChatService, friend_key: str, friend_name: str, body: str) -> bool:
    name = friend_name or friend_key or "?"

    def dm_feedback(msg: str):
        if msg:
            cs.dm_send(friend_key, msg)

    return handle_party_management_command(
        cs,
        body,
        name,
        dm_feedback,
        context="dm",
        sender_puuid=friend_key,
    )


# ------------ Grup komutları (Lobby sohbeti) ------------
def handle_group_command(cs: ChatService, conv_id: str, body: str, from_name: str, cfg: dict):
    txt = (body or "").strip()
    low = txt.lower()

    def info_to_group(msg: str):
        if not cfg.get("silent_group", False):
            cs.send(conv_id, msg)

    if handle_party_management_command(cs, txt, from_name, info_to_group):
        return

    # DURDUR / STOP
    if low in ("durdur","stop"):
        log_once("GRP-CMD", f'{from_name} → DURDUR')
        if cs.is_party_leader():
            ok = cs.stop_matchmaking()
            info_to_group("Matchmaking durduruldu." if ok else "Durdurma başarısız.")
            log_once("QUEUE", f"STOP_CALL={'OK' if ok else 'FAIL'}")
        else:
            info_to_group(f"{from_name} durdur dedi ama lider değilim.")
        return

    # GEO (kısa geoinfo)
    if low in ("geo","bolge"):
        info = cs.geoinfo_quick()
        log_once("GRP-CMD", f'{from_name} → GEO')
        info_to_group(f"GeoInfo: {info}")
        return

        # --- AUTO-PICK (sadece lobi sohbetinden kontrol) ---
        # PICKLIST Shaco,Teemo,Trundle
    if low.startswith("picklist "):
        names_str = txt.split(" ", 1)[1].strip()
        names = [s.strip() for s in names_str.split(",") if s.strip()]
        # İsimleri id'ye çevir
        ids = []
        bad = []
        for nm in names:
            cid = cs.champion_id_from_text(nm)
            if cid and cid not in ids:
                ids.append(cid)
            else:
                if not cid:
                    bad.append(nm)
        cfg["auto_pick_list"] = ",".join(names)
        cfg["auto_pick_ids"] = ids
        log_once("PICK", f"list={cfg['auto_pick_list']} ids={ids}")
        ok_part = (", ".join(names) if names else "∅")
        msg = f"Auto-pick listesi güncellendi: {ok_part}"
        if bad:
            msg += f" | Bilinmeyen: {', '.join(bad)}"
        info_to_group(msg)
        return

        # PICK ON / PICK OFF  → otomatik seçim aç/kapat
    if low in ("pick on", "pick aç", "pick ac"):
        cfg["auto_pick_enabled"] = True
        log_once("PICK", "auto-pick = ON")
        info_to_group("Auto-pick: ON")
        return
    if low in ("pick off", "pick kapat"):
        cfg["auto_pick_enabled"] = False
        log_once("PICK", "auto-pick = OFF")
        info_to_group("Auto-pick: OFF")
        return

        # LOCK ON / LOCK OFF  → pick sonrası lock davranışı
    if low in ("lock on", "kilit on", "kilit aç", "kilit ac"):
        cfg["auto_pick_lock"] = True
        log_once("PICK", "auto-pick-lock = ON")
        info_to_group("Auto-pick lock: ON (hover + lock)")
        return
    if low in ("lock off", "kilit off", "kilit kapat"):
        cfg["auto_pick_lock"] = False
        log_once("PICK", "auto-pick-lock = OFF")
        info_to_group("Auto-pick lock: OFF (sadece hover)")
        return

# ------------ Ready-Check watcher (auto-accept) ------------
def ready_check_watcher(cs: ChatService, cfg: dict, stop_flag: dict):
    """
    Auto-ready mantığı:
      - Sadece phase == ReadyCheck ve state == InProgress iken dener.
      - 1.0 sn cooldown ile yeniden dener.
      - Başarısızlıkta HTTP kodu ve response loglar.
      - (opsiyonel) 3 başarısızlıktan sonra kısa süre tıklayıcı fallback.
    """
    import time
    last_phase = ""
    last_state = ""
    last_attempt_ts = 0.0
    fail_streak = 0

    fallback_click = cfg.get("fallback_click", False) and CLICKER_AVAILABLE
    click_burst_sec = 6.0

    while not stop_flag.get("stop"):
        try:
            phase = cs.gameflow_phase()
            if phase != last_phase:
                log_once("PHASE", phase)
                last_phase = phase

            info = cs.ready_check_status() or {}
            state = (info.get("state") or "").lower()
            my_resp = (info.get("playerResponse") or "").lower()

            if state and state != last_state:
                log_once("READY", f"state={info.get('state')} my={info.get('playerResponse')}")
                last_state = state

            now = time.time()
            if (
                cfg.get("auto_ready", False)
                and phase == "ReadyCheck"
                and state in ("inprogress", "in_progress")
                and my_resp in ("", "none")
                and (now - last_attempt_ts) >= 1.0
            ):
                last_attempt_ts = now
                ok, code, text = cs.ready_check_accept_verbose()
                if ok:
                    log_once("READY", "✔ Otomatik kabul gönderildi.")
                    fail_streak = 0
                else:
                    fail_streak += 1
                    log_once("READY", f"✖ Kabul POST başarısız (code={code}) {text[:120].strip()}")
                    if fallback_click and fail_streak >= 3:
                        log_once("READY", "↪ Fallback: clicker ACCEPT denemesi başlatıldı (kısa süre).")
                        CLICK_STATE["active"] = True
                        t_end = time.time() + click_burst_sec
                        while time.time() < t_end and phase == "ReadyCheck" and my_resp in ("", "none"):
                            time.sleep(0.25)
                            phase = cs.gameflow_phase()
                            j = cs.ready_check_status() or {}
                            my_resp = (j.get("playerResponse") or "").lower()
                        CLICK_STATE["active"] = False
                        fail_streak = 0
        except Exception as e:
            log_once("READY", f"err={e}")

        time.sleep(0.25)

# ------------ Champ Select watcher (auto-pick) ------------
def champ_select_watcher(cs: ChatService, cfg: dict, stop_flag: dict):
    """
    ChampSelect'te otomatik şampiyon seçer.
    - Phase == 'ChampSelect' iken çalışır.
    - Her yeni actionId için bir kez dener; başarısızsa bekler.
    """
    import time
    last_phase = ""
    last_action_id = None
    last_try_ts = 0.0

    while not stop_flag.get("stop"):
        try:
            phase = cs.gameflow_phase()
            if phase != last_phase:
                log_once("PHASE", phase)
                last_phase = phase
                last_action_id = None

            if not cfg.get("auto_pick_enabled", False) or phase != "ChampSelect":
                time.sleep(0.3); continue

            act, _sess = cs.my_pick_action()
            if not act:
                time.sleep(0.3); continue

            aid = int(act.get("id"))
            if aid == last_action_id and (time.time() - last_try_ts) < 0.8:
                time.sleep(0.15); continue

            last_action_id = aid
            last_try_ts = time.time()

            ids = cfg.get("auto_pick_ids", []) or []
            if not ids:
                continue

            ok, how = cs.autopick_try_with_bench(ids, do_lock=cfg.get("auto_pick_lock", True))
            if ok:
                log_once("PICK", f"{how.upper()} (actionId={aid}) ids={ids}")
            else:
                if how not in ("not_my_turn", "not_in_progress"):
                    log_once("PICK", f"fail={how} (actionId={aid}) ids={ids}")
        except Exception as e:
            log_once("PICK", f"err={e}")

        time.sleep(0.25)

# ------------ Arkadaş listesi CLI dump ------------
def print_friends(cs: ChatService, only: Optional[str]=None):
    friends = cs.list_friends()
    on, bsy, off = [], [], []
    from utils import status_tag
    for f in friends:
        name = f.get('name') or f.get('gameName') or f.get('displayName') or 'Unknown'
        tag = status_tag(f.get('availability'))
        (on if tag=="[ON]" else off if tag=="[OFF]" else bsy).append(name)
    print("KING"); idx=1
    def dump(lst, marker):
        nonlocal idx
        for n in lst: print(f"[{idx}] {marker} {n}"); idx+=1
    if only=="online": dump(on,"[ON]")
    elif only=="offline": dump(off,"[OFF]")
    else: dump(on,"[ON]"); dump(off,"[OFF]"); dump(bsy,"[BSY]")

# ------------ Ana ------------
def main():
    try: sys.stdout.reconfigure(line_buffering=True)
    except Exception: pass
    print("RUNNING | Hotkey: Ctrl+Shift+Q"); print(ASCII_LOGO)

    lcu = LcuSession()
    cs = ChatService(lcu)
    cs.refresh_me(); log_once("SELF", str(cs.ME))

    # Ayarlar (ENV)
    cfg = {
        "announce":      os.getenv("ANNOUNCE_CMDS", "true").lower()  in ("1","true","on","yes"),
        "silent_group":  os.getenv("SILENT_GROUP",  "false").lower() in ("1","true","on","yes"),
        "quiet":         os.getenv("QUIET",         "false").lower() in ("1","true","on","yes"),
        "auto_ready":    os.getenv("AUTO_READY",    "false").lower() in ("1","true","on","yes"),
        "fallback_click":os.getenv("AUTO_READY_FALLBACK_CLICK","false").lower() in ("1","true","on","yes"),
        # --- AUTOPICK ---
        "auto_pick_enabled": os.getenv("AUTO_PICK_ENABLED", "false").lower() in ("1","true","on","yes"),
        "auto_pick_lock":    os.getenv("AUTO_PICK_LOCK",    "true").lower()  in ("1","true","on","yes"),
        "auto_pick_list":    os.getenv("AUTO_PICK",         "").strip(),   # "Ahri,Annie,Katarina"
        "auto_pick_ids":     [],  # isimler id'ye çevrilip buraya doldurulacak
    }

    # Auto-pick isimlerini id'ye çevir
    def _hydrate_pick_ids():
        names = [x.strip() for x in (cfg["auto_pick_list"] or "").split(",") if x.strip()]
        ids = []
        for nm in names:
            cid = cs.champion_id_from_text(nm)
            if cid and cid not in ids:
                ids.append(cid)
        cfg["auto_pick_ids"] = ids
    _hydrate_pick_ids()

    if cfg["fallback_click"] and not CLICKER_AVAILABLE:
        log_once("READY", "AUTO_READY_FALLBACK_CLICK sadece Windows'ta desteklenir; devre dışı bırakıldı.")
        cfg["fallback_click"] = False

    log_once("CFG",
        f"announce={cfg['announce']} silent_group={cfg['silent_group']} "
        f"quiet={cfg['quiet']} auto_ready={cfg['auto_ready']} "
        f"fallback_click={cfg['fallback_click']} "
        f"auto_pick_enabled={cfg['auto_pick_enabled']} "
        f"auto_pick_lock={cfg['auto_pick_lock']} "
        f"auto_pick_list={cfg['auto_pick_list']} ids={cfg['auto_pick_ids']}"
    )

    dm_callbacks = []

    def _dm_command_callback(friend_key: str, friend_name: str, body: str, is_me: bool):
        if is_me:
            return
        if handle_dm_party_command(cs, friend_key, friend_name, body):
            who = friend_name or friend_key
            log_once("DM-CMD", f"{who} → {body}")

    dm_callbacks.append(_dm_command_callback)

    # Telegram köprü (varsa)
    BOT = os.getenv("TELEGRAM_BOT_TOKEN", "")
    OWNER = int(os.getenv("TELEGRAM_OWNER_ID", "0") or 0)
    FORUM = os.getenv("TELEGRAM_FORUM_ID", "")  # -100... forum
    tb: Optional[TelegramBridge] = None
    if BOT and OWNER:
        tb = TelegramBridge(cs, owner_id=OWNER, bot_token=BOT,
                            forum_chat_id=(int(FORUM) if FORUM else None))
        tb.start_in_thread()
        dm_callbacks.append(tb.on_dm_from_lol)
        log_once("TG", "Telegram bridge aktif (main üzerinden).")
    else:
        log_once("TG", "Pasif: TELEGRAM_BOT_TOKEN / TELEGRAM_OWNER_ID set değil.")

    def _dm_dispatcher(friend_key: str, friend_name: str, body: str, is_me: bool):
        for cb in dm_callbacks:
            try:
                cb(friend_key, friend_name, body, is_me)
            except Exception as e:
                log_once("DM-CB", f"err={e}")

    threading.Thread(target=cs.watch_dms, args=(_dm_dispatcher,), daemon=True).start()
    log_once("DM", "DM watcher aktif.")

    # Lobby & queue watcher (ID/solo/phase/readycheck logları)
    # Lobby grup mesajlarını izle → komutları işle
    threading.Thread(
        target=lambda: cs.watch_group_messages(
            lambda cid, body, frm: handle_group_command(cs, cid, body, frm, cfg),
            0.8,  # interval
            True,  # include_self → SOLO desteği
            True  # debug → her mesajı GRP-SEE olarak yaz
        ),
        daemon=True
    ).start()

    # Ready-check watcher
    stop_flag = {'stop': False}
    threading.Thread(target=ready_check_watcher, args=(cs, cfg, stop_flag), daemon=True).start()

    # Champ Select watcher
    threading.Thread(target=champ_select_watcher, args=(cs, cfg, stop_flag), daemon=True).start()

    # Ekran tıklayıcı (şimdilik pasif)
    CLICK_STATE["active"] = False
    if CLICKER_AVAILABLE:
        threading.Thread(target=clicker_worker, daemon=True).start()
    else:
        log_once("CLICK", "UI clicker thread'i başlatılmadı (Windows dışı platform).")

    # Acil durdurma hotkey
    threading.Thread(target=emergency_hotkey, args=(stop_flag,), daemon=True).start()

    # Lobby sohbetini otomatik takip et ve ilk anonsu isteğe bağlı gönder
    def _auto_follow():
        last = None
        while not stop_flag['stop']:
            try:
                if cs.follow_lobby_chat() and cs.active_group_id != last:
                    log_once("GRP", f"Lobby sohbeti takipte: {cs.active_group_id}")
                    if cs.is_party_leader() and cfg.get("announce", True):
                        cs.send(cs.active_group_id,
                                "Komutlar: BASLAT | DURDUR | PICKLIST <ad,ad> | PICK ON|OFF | LOCK ON|OFF")
                        members = cs.group_members_with_status(cs.active_group_id)
                        for i, (name, tag) in enumerate(members, 1):
                            log_once("GRP-MEM", f"[{i}] {tag} {name}")
                    last = cs.active_group_id
            except Exception as e:
                log_once("GRP", f"auto err: {e}")
            time.sleep(2.0)
    threading.Thread(target=_auto_follow, daemon=True).start()

    # -------- CLI döngüsü --------
    while not stop_flag['stop']:
        try:
            cmd = input('> ').strip()
        except (EOFError, KeyboardInterrupt):
            break
        low = cmd.lower()

        if low in ("quit","exit","stop","dur","bitir"):
            break

        elif low in ("help","/help","?"):
            _print_help()

        elif low == "status":
            print({"me": cs.ME, "cfg": cfg})

        elif low in ("/friends","/friend","/all-friend"):
            print_friends(cs)

        elif low == "/online-friend":
            print_friends(cs, only="online")

        elif low == "/offline-friend":
            print_friends(cs, only="offline")

        elif low == "/chat-groups":
            groups = cs.list_groups()
            for i,g in enumerate(groups,1):
                print(f"[{i}] id={g.get('id')} name={g.get('name')}")

        elif low.startswith("/chat-group "):
            key = cmd.split(" ",1)[1].strip()
            g = cs.select_group(key)
            if not g:
                print("(grup bulunamadı)")
            else:
                members = cs.group_members_with_status(g['id'])
                print("KING")
                for i,(name, tag) in enumerate(members,1):
                    print(f"[{i}] {tag} {name}")

        elif low == "/group-log":
            if not cs.active_group_id:
                print("(aktif grup seçilmedi)")
            else:
                msgs = cs.messages(cs.active_group_id, limit=50)
                for m in msgs:
                    is_me = False
                    if m.get('isSelf') is True: is_me=True
                    if str(m.get('fromSummonerId') or '') == str(cs.ME.get('summonerId') or ''): is_me=True
                    pid = (m.get('fromPid') or '').split('@',1)[0]
                    if pid and pid == (cs.ME.get('puuid') or ''): is_me=True
                    body = (m.get('body') or '').replace('\r\n',' ').replace('\n',' ').replace('\r',' ')
                    print(("ME=>YOU " if is_me else "YOU=>ME ") + body)

        elif low.startswith("/sayg "):
            text = cmd.split(" ",1)[1]
            if not cs.active_group_id:
                print("(aktif grup yok)")
            else:
                ok = cs.send(cs.active_group_id, text)
                print("(gönderildi)" if ok else "(gönderilemedi)")

        elif low.startswith("/dm "):
            try:
                _, rest = cmd.split(" ", 1)
                name, text = rest.split(" ", 1)
            except ValueError:
                print("Kullanım: /dm <kullanıcı-adı> <mesaj>"); continue
            ok = cs.dm_send(name, text)
            print("(gönderildi)" if ok else "(gönderilemedi)")

        elif low.startswith("/dm-log "):
            name = cmd.split(" ",1)[1].strip()
            for line in cs.dm_log(name, limit=30):
                print(line)

        elif low == "/geo":
            print(cs.geoinfo_quick() or "(boş yanıt)")

        elif low == "/geo-json":
            import json
            data = cs.geoinfo()
            print(json.dumps(data, ensure_ascii=False, indent=2) if data else "(boş yanıt)")

        elif low == "/bench":
            ids = cs.cs_bench_list()
            if not ids:
                print("(bench boş)")
            else:
                cat = cs.champion_catalog()["by_id"]
                names = [cat.get(i, {}).get("name") or str(i) for i in ids]
                print("BENCH:", ", ".join(names))

        elif low.startswith("/bench-pick "):
            name = cmd.split(" ", 1)[1].strip()
            cid = cs.champion_id_from_text(name)
            if not cid:
                print(f'Bilinmeyen şampiyon: "{name}"');
            else:
                ok = cs.bench_swap(cid)
                print("(bench swap OK)" if ok else "(bench swap FAIL)")

        elif low.startswith("/auto-ready"):
            parts = cmd.split()
            if len(parts) == 1:
                print(f"auto-ready = {'on' if cfg['auto_ready'] else 'off'}")
            else:
                val = parts[1].lower()
                if val in ("on","true","1","yes","evet","aç","ac"):
                    cfg["auto_ready"] = True;  print("auto-ready ON")
                elif val in ("off","false","0","no","hayir","kapat","kapalı","kapali"):
                    cfg["auto_ready"] = False; print("auto-ready OFF")
                else:
                    print("Kullanım: /auto-ready on|off")

        elif low.startswith("/auto-pick-lock"):
            parts = cmd.split()
            if len(parts) == 1:
                print(f"auto-pick-lock = {'on' if cfg['auto_pick_lock'] else 'off'}")
            else:
                val = parts[1].lower()
                if val in ("on","true","1","yes","ac","aç"):
                    cfg["auto_pick_lock"] = True;  print("auto-pick-lock ON (hover + lock)")
                elif val in ("off","false","0","no","kapat"):
                    cfg["auto_pick_lock"] = False; print("auto-pick-lock OFF (sadece hover)")
                else:
                    print("Kullanım: /auto-pick-lock on|off")

        elif low.startswith("/auto-pick"):
            parts = cmd.split(" ", 1)
            if len(parts) == 1:
                print(f"auto-pick = {'on' if cfg['auto_pick_enabled'] else 'off'}, lock={'on' if cfg['auto_pick_lock'] else 'off'}, list={cfg['auto_pick_list']} ids={cfg['auto_pick_ids']}")
            else:
                arg = parts[1].strip()
                if arg.lower() in ("on","true","1","yes","ac","aç"):
                    cfg["auto_pick_enabled"] = True
                    print("auto-pick ON")
                elif arg.lower() in ("off","false","0","no","kapat"):
                    cfg["auto_pick_enabled"] = False
                    print("auto-pick OFF")
                else:
                    # Liste güncelle (virgüllü isimler)
                    cfg["auto_pick_list"] = arg
                    # id'leri güncelle
                    names = [x.strip() for x in arg.split(",") if x.strip()]
                    ids = []
                    for nm in names:
                        cid = cs.champion_id_from_text(nm)
                        if cid and cid not in ids:
                            ids.append(cid)
                    cfg["auto_pick_ids"] = ids
                    print(f"auto-pick list set → {cfg['auto_pick_list']}  ids={ids}")

        elif low.startswith("/announce"):
            val = (cmd.split(" ",1)[1].strip().lower() if " " in cmd else "")
            if   val in ("on","1","true","yes","ac","aç"): cfg["announce"]=True;  print("announce=ON")
            elif val in ("off","0","false","no","kapat"):  cfg["announce"]=False; print("announce=OFF")
            else: print(f"announce={cfg['announce']}")

        elif low.startswith("/silent-group"):
            val = (cmd.split(" ",1)[1].strip().lower() if " " in cmd else "")
            if   val in ("on","1","true","yes","ac","aç"): cfg["silent_group"]=True;  print("silent_group=ON")
            elif val in ("off","0","false","no","kapat"):  cfg["silent_group"]=False; print("silent_group=OFF")
            else: print(f"silent_group={cfg['silent_group']}")

        elif low.startswith("/quiet"):
            val = (cmd.split(" ",1)[1].strip().lower() if " " in cmd else "")
            if   val in ("on","1","true","yes","ac","aç"): cfg["quiet"]=True;  print("quiet=ON")
            elif val in ("off","0","false","no","kapat"):  cfg["quiet"]=False; print("quiet=OFF")
            else: print(f"quiet={cfg['quiet']}")

        elif low.startswith("/sayl "):  # say to lobby
            txt = cmd.split(" ", 1)[1]
            ok = cs.send_to_lobby(txt)
            print("(lobiye gönderildi)" if ok else "(lobi sohbeti bulunamadı)")

        else:
            if not cfg.get("quiet", False):
                _print_help()

if __name__ == "__main__":
    main()
