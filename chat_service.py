from __future__ import annotations
from typing import Optional, Dict, List, Callable
from urllib.parse import quote
from utils import log_once, parse_ts_iso, status_tag

class ChatService:
    """LCU Chat üst hizmet katmanı: DM / grup / arkadaş / presence / lobby / matchmaking."""

    def __init__(self, lcu_session):
        self.lcu = lcu_session
        self.ME: Dict = {}
        self._last_dm_ts: Dict[str, float] = {}
        self.active_group_id: Optional[str] = None  # aktif takip edilen grup (lobby chat vs.)

    # ---- raw helpers ----
    def _get(self, path: str, timeout: int = 3):
        s, base = self.lcu.get()
        if not s:
            return None
        return s.get(f"{base}{path}", timeout=timeout)

    def _post(self, path: str, json=None, timeout: int = 3):
        s, base = self.lcu.get()
        if not s:
            return None
        return s.post(f"{base}{path}", json=json, timeout=timeout)

    # ---- identity ----
    def refresh_me(self):
        r = self._get("/lol-summoner/v1/current-summoner")
        if r and r.status_code == 200:
            j = r.json() or {}
            self.ME = {
                "displayName": j.get("displayName") or j.get("gameName") or "",
                "summonerId": str(j.get("summonerId") or ""),
                "puuid": j.get("puuid") or "",
            }
            return
        r = self._get("/lol-chat/v1/me")
        if r and r.status_code == 200:
            j = r.json() or {}
            self.ME = {
                "displayName": j.get("name") or j.get("gameName") or "",
                "summonerId": str(j.get("summonerId") or ""),
                "puuid": j.get("puuid") or "",
            }

    # ---- conversations ----
    def list_conversations(self) -> List[dict]:
        r = self._get("/lol-chat/v1/conversations")
        if not r or r.status_code != 200:
            return []
        return r.json() or []

    def list_dms(self) -> List[dict]:
        return [c for c in self.list_conversations() if (c.get('type') or '').lower() == "chat"]

    def list_groups(self) -> List[dict]:
        return [c for c in self.list_conversations() if (c.get('type') or '').lower() == "groupchat"]

    # ---- friends & presence ----
    def list_friends(self) -> List[dict]:
        r = self._get("/lol-chat/v1/friends")
        if not r or r.status_code != 200:
            return []
        return r.json() or []

    def my_presence(self) -> Dict:
        """Aktif hesabın sohbet / presence bilgilerini döner."""
        r = self._get("/lol-chat/v1/me")
        if r and r.status_code == 200:
            return r.json() or {}
        return {}

    def my_availability(self) -> str:
        pres = self.my_presence() or {}
        return (pres.get('availability') or pres.get('availabilityStatus') or '').lower()

    def list_friends_online(self) -> List[dict]:
        out = []
        for f in self.list_friends():
            av = (f.get('availability') or f.get('availabilityStatus') or '').lower()
            if av in ('chat', 'online', 'mobile'):
                out.append(f)
        return out

    def friend_display_label(self, f: dict) -> str:
        dn = f.get('name') or f.get('gameName') or f.get('displayName') or 'Unknown'
        return f"{status_tag(f.get('availability'))} {dn}"

    def friend_by_key(self, key: str) -> Optional[dict]:
        # key: pid (preferred) veya puuid
        for f in self.list_friends():
            pid = (f.get('pid') or '').split('@', 1)[0]
            puuid = f.get('puuid') or ''
            if key == pid or key == puuid:
                return f
        return None

    def friend_key_from_conv_id(self, conv_id: str) -> str:
        return (conv_id or '').split('@', 1)[0]

    def friend_display_name(self, key: str) -> str:
        f = self.friend_by_key(key)
        return (f.get('name') or f.get('gameName') or f.get('displayName') or key) if f else key

    # ---- messaging ----
    def messages(self, conv_id: str, limit: int = 50) -> List[dict]:
        uid = quote(conv_id, safe='@._-')
        r = self._get(f"/lol-chat/v1/conversations/{uid}/messages")
        if not r or r.status_code != 200:
            return []
        data = r.json() or []
        return data[-limit:]

    def send(self, conv_id: str, text: str) -> bool:
        uid = quote(conv_id, safe='@._-')
        r = self._post(f"/lol-chat/v1/conversations/{uid}/messages", json={"body": text})
        return bool(r and r.status_code in (200, 201, 204))

    def participants(self, conv_id: str) -> List[dict]:
        uid = quote(conv_id, safe='@._-')
        r = self._get(f"/lol-chat/v1/conversations/{uid}/participants")
        if not r or r.status_code != 200:
            return []
        return r.json() or []

    # ---- formatting helpers ----
    @staticmethod
    def _fmt_ts_str(ts: str | None) -> str:
        if not ts:
            return ""
        return ts.replace('T', ' ').replace('Z', '')

    def _is_me(self, m: dict) -> bool:
        if m.get('isSelf') is True:
            return True
        if str(m.get('fromSummonerId') or '') == str(self.ME.get('summonerId') or ''):
            return True
        pid = (m.get('fromPid') or '').split('@', 1)[0]
        if pid and pid == (self.ME.get('puuid') or ''):
            return True
        return False

    @staticmethod
    def _sender_guess(m: dict) -> str:
        pid = (m.get('fromPid') or '').split('@', 1)[0]
        return (
            m.get('fromSummonerName')
            or m.get('fromName')
            or pid
            or str(m.get('fromSummonerId') or '?')
        )

    # ---- DM watcher (polling) ----
    def watch_dms(
        self,
        callback: Callable[[str, str, str, bool], None],
        interval: float = 2.0,
        recent_seconds: float = 120.0,
    ):
        """callback(friend_key, friend_name, body, is_me)

        recent_seconds>0 ise, yalnızca bu süre içerisindeki mesajları tetikler.
        """
        import time as _t

        while True:
            recent_cutoff = (_t.time() - recent_seconds) if recent_seconds and recent_seconds > 0 else None
            try:
                for c in self.list_dms():
                    cid = c.get('id')
                    if not cid:
                        continue
                    msgs = self.messages(cid, limit=30)
                    last = self._last_dm_ts.get(cid, 0.0)
                    if recent_cutoff and last < recent_cutoff:
                        last = recent_cutoff
                    for m in msgs:
                        ts = parse_ts_iso(m.get('timestamp'))
                        if recent_cutoff and ts < recent_cutoff:
                            continue
                        if ts <= last:
                            continue
                        is_me = self._is_me(m)
                        body = (m.get('body') or '').replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
                        friend_key = self.friend_key_from_conv_id(cid)
                        friend_name = self.friend_display_name(friend_key)
                        callback(friend_key, friend_name, body, is_me)
                        if ts > last:
                            last = ts
                    self._last_dm_ts[cid] = last
            except Exception as e:
                log_once("DM-WATCH", f"EXC {e}")
            finally:
                _t.sleep(interval)

    # ---- DM helpers for CLI (/dm-log) ----
    def _find_friend_by_name_or_key(self, name_or_key: str) -> Optional[dict]:
        key = name_or_key.strip()
        f = self.friend_by_key(key)
        if f:
            return f
        key_low = key.lower()
        for fr in self.list_friends():
            dn = fr.get('name') or fr.get('gameName') or fr.get('displayName') or ''
            if dn.lower() == key_low:
                return fr
        for fr in self.list_friends():
            dn = fr.get('name') or fr.get('gameName') or fr.get('displayName') or ''
            if dn.lower().startswith(key_low):
                return fr
        for c in self.list_dms():
            dn = c.get('name') or ''
            if dn.lower() == key_low or dn.lower().startswith(key_low):
                return {"name": dn, "pid": c.get('id')}
        return None

    def _ensure_dm_conversation(self, friend: dict) -> Optional[dict]:
        jid = friend.get('pid') or (friend.get('puuid') and f"{friend['puuid']}@pvp.net")
        if not jid:
            return None
        for c in self.list_dms():
            if c.get('id') == jid:
                return c
        self._post("/lol-chat/v1/conversations", json={"id": jid, "type": "chat"})
        for c in self.list_dms():
            if c.get('id') == jid:
                return c
        return None

    def dm_log(self, name_or_key: str, limit: int = 30) -> list[str]:
        friend = self._find_friend_by_name_or_key(name_or_key)
        if not friend:
            return [f"(arkadaş/DM bulunamadı: {name_or_key})"]
        conv = self._ensure_dm_conversation(friend)
        if not conv:
            return [f"(DM kanalı alınamadı: {name_or_key})"]
        msgs = self.messages(conv['id'], limit=limit)
        lines: list[str] = []
        for m in msgs:
            is_me = self._is_me(m)
            ts_str = self._fmt_ts_str(m.get('timestamp'))
            body = (m.get('body') or '').replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
            if is_me:
                lines.append(f"[ME=>YOU] [{ts_str}] : {body}")
            else:
                lines.append(f"[YOU=>ME] [{ts_str}] : {body}")
        return lines

    # ---- Lobby / Party helpers ----
    def _lget(self, path: str):
        r = self._get(path);  return r.json() if r and r.status_code==200 else {}

    def is_party_leader(self) -> bool:
        try:
            j = self._lget("/lol-lobby/v2/lobby")
            me = j.get("localMember", {}) or {}
            return bool(me.get("isLeader"))
        except Exception:
            return False

    def start_matchmaking(self) -> bool:
        r = self._post("/lol-lobby/v2/lobby/matchmaking/search");  return bool(r)

    def stop_matchmaking(self) -> bool:
        s, base = self.lcu.get()
        if not s: return False
        r = s.delete(f"{base}/lol-lobby/v2/lobby/matchmaking/search", timeout=3)
        return r.status_code in (200,204)

    def _lobby_members(self) -> list[dict]:
        j = self._lget("/lol-lobby/v2/lobby")
        return j.get("members", []) or []

    def is_puuid_in_lobby(self, puuid: str | None) -> bool:
        target = (puuid or "").lower().strip()
        if not target:
            return False
        for member in self._lobby_members():
            mp = (member.get("puuid") or "").lower().strip()
            if mp and mp == target:
                return True
        return False

    def find_member_by_name(self, name: str) -> Optional[dict]:
        n = (name or "").strip().lower()
        for m in self._lobby_members():
            if (m.get("summonerName") or "").lower() == n: return m
        return None

    def kick_member_by_id(self, summoner_id: int) -> bool:
        s, base = self.lcu.get()
        if not s: return False
        r = s.delete(f"{base}/lol-lobby/v2/lobby/members/{summoner_id}", timeout=3)
        return r.status_code in (200,204)

    def promote_member_by_id(self, summoner_id: int) -> bool:
        r = self._post(f"/lol-lobby/v2/lobby/members/{summoner_id}/promote")
        return bool(r)

    # ---- Group helpers ----
    def select_group(self, key: str) -> Optional[dict]:
        key = (key or "").strip().lower()
        for g in self.list_groups():
            if g.get("id")==key or (g.get("name") or "").lower()==key:
                self.active_group_id = g["id"];  return g
        return None

    def group_members_with_status(self, conv_id: str) -> list[tuple[str,str]]:
        names = []
        for p in self.participants(conv_id):
            nm = p.get('name') or p.get('gameName') or p.get('summonerName') or ''
            tag = status_tag(p.get('availability'))
            names.append((nm, tag))
        return names

    # chat_service.py  →  ChatService sınıfına koy
    def watch_group_messages(self, on_message, interval: float = 1.0, include_self: bool = True, debug: bool = True):
        """
        Grup sohbetlerini izler ve her yeni mesaj için on_message(conv_id, body, from_name) çağırır.
        - include_self=True: SOLO lobide kendi yazdıklarını da yakalar.
        - debug=True: Yakalanan HER mesajı terminale loglar (GRP-SEE).
        """
        import time
        from utils import log_once, parse_ts_iso

        # conv_id -> (last_ts: float, last_mid: str|int|None)
        last_seen = {}

        def _is_me(msg: dict) -> bool:
            if msg.get('isSelf') is True:
                return True
            me = self.ME or {}
            my_sid = str(me.get('summonerId') or '')
            my_puuid = (me.get('puuid') or '')
            if str(msg.get('fromSummonerId') or '') == my_sid:
                return True
            pid = (msg.get('fromPid') or '').split('@', 1)[0]
            return bool(pid and my_puuid and pid == my_puuid)

        def _sender(msg: dict) -> str:
            return (
                    msg.get("fromSummonerName")
                    or msg.get("fromName")
                    or msg.get("senderName")
                    or msg.get("sender")
                    or "Unknown"
            )

        while True:
            try:
                # Hangi groupchat'leri izleyeceğiz?
                if self.active_group_id:
                    conv_ids = [self.active_group_id]
                else:
                    conv_ids = [g.get("id") for g in (self.list_groups() or []) if g.get("id")]

                for cid in conv_ids:
                    msgs = self.messages(cid, limit=50) or []
                    # kronolojik sıraya al (timestamp varsa ona göre)
                    try:
                        msgs.sort(key=lambda m: parse_ts_iso(m.get("timestamp")))
                    except Exception:
                        pass

                    last_ts, last_mid = last_seen.get(cid, (0.0, None))

                    for m in msgs:
                        ts = parse_ts_iso(m.get("timestamp"))
                        mid = m.get("id")

                        # yeni mi?
                        is_new = (ts > last_ts) or (ts == last_ts and (last_mid is None or mid != last_mid))
                        if not is_new:
                            continue

                        is_self = _is_me(m)
                        if not include_self and is_self:
                            # kendi mesajlarını atla (SOLO'da kapatma — biz açık tutuyoruz)
                            continue

                        body = (m.get("body") or "").strip()
                        if not body:
                            continue

                        sender = _sender(m)

                        if debug:
                            log_once("GRP-SEE", f"cid={cid} from={sender} self={is_self} body={body}")

                        # callback (komut işleyici)
                        try:
                            on_message(cid, body, sender)
                        except Exception as cb_err:
                            log_once("GRP", f"on_message err: {cb_err}")

                        # ilerleme kaydı
                        last_ts, last_mid = ts, mid

                    last_seen[cid] = (last_ts, last_mid)

            except Exception as e:
                log_once("GRP", f"watch err: {e}")

            time.sleep(interval)

    # === Lobby sohbetini otomatik takip (grup id eşleme) ===
    def _lobby_member_names(self) -> set[str]:
        return {
            (m.get("summonerName") or "").lower()
            for m in self._lobby_members()
            if (m.get("summonerName") or "")
        }

    def get_lobby_group_id(self) -> Optional[str]:
        """
        Lobby üyeleri ile mevcut grup sohbetlerinin katılımcılarını kesiştirir,
        en çok eşleşen grubu döner. Solo iken de (tek eşleşme) id dönebilir.
        """
        try:
            lobby = self._lobby_member_names()
            if not lobby:
                return None

            best_gid, best_score = None, 0
            for g in self.list_groups():
                gid = g.get("id")
                if not gid:
                    continue
                in_group = {
                    (p.get('name') or p.get('gameName') or p.get('summonerName') or '').lower()
                    for p in self.participants(gid)
                }
                score = len(in_group & lobby)
                if score > best_score:
                    best_score, best_gid = score, gid

            # Eşik: solo/duo'da >=1, daha kalabalıkta >=2 denk üye varsa uygun kabul et
            if best_gid and (best_score >= (1 if len(lobby) <= 2 else 2)):
                return best_gid
            return None
        except Exception:
            return None

    def follow_lobby_chat(self) -> bool:
        gid = self.get_lobby_group_id()
        if gid and gid != self.active_group_id:
            self.active_group_id = gid
            return True
        return False

    def send_to_lobby(self, text: str) -> bool:
        if not self.active_group_id:
            self.follow_lobby_chat()
        return self.active_group_id and self.send(self.active_group_id, text)

    def ready_check_accept_verbose(self) -> tuple[bool, int, str]:
        """
        Ready-check accept için dayanıklı denemeler.
        Dönen: (ok, status_code, text)
        """
        s, base = self.lcu.get()
        if not s or not base:
            return (False, -1, "no session")

        url = f"{base}/lol-matchmaking/v1/ready-check/accept"
        tries = [
            lambda: s.post(url, json={}, timeout=3),
            lambda: s.post(url, data=b"{}", timeout=3),
            lambda: s.post(url, timeout=3),
            lambda: s.put(url, json={}, timeout=3),   # bazı build'lerde PUT kabul ediliyor
        ]
        last = None
        for call in tries:
            try:
                r = call()
                last = r
                if r.status_code in (200, 204):
                    return (True, r.status_code, r.text or "")
            except Exception as e:
                last = None
                err = str(e)
                # sıradaki varyanta geç
                continue

        if last is None:
            return (False, -1, "exception")
        return (False, getattr(last, "status_code", 0) or 0, getattr(last, "text", "") or "")

    # (isteğe bağlı ama kullanışlı) mevcut kısa yöntemi verbose'a yönlendir
    def ready_check_accept(self) -> bool:
        ok, _, _ = self.ready_check_accept_verbose()
        return ok


    # (isteğe bağlı ama kullanışlı) mevcut kısa yöntemi verbose'a yönlendir
    def ready_check_accept(self) -> bool:
        ok, _, _ = self.ready_check_accept_verbose()
        return ok

    def ready_check_accept_verbose(self) -> tuple[bool, int, str]:
        """
        Ready-check accept için dayanıklı denemeler.
        Dönen: (ok, status_code, text)
        """
        s, base = self.lcu.get()
        if not s or not base:
            return (False, -1, "no session")

        url = f"{base}/lol-matchmaking/v1/ready-check/accept"
        tries = [
            lambda: s.post(url, json={}, timeout=3),
            lambda: s.post(url, data=b"{}", timeout=3),
            lambda: s.post(url, timeout=3),
            lambda: s.put(url, json={}, timeout=3),   # bazı build'lerde PUT kabul ediliyor
        ]
        last = None
        for call in tries:
            try:
                r = call()
                last = r
                if r.status_code in (200, 204):
                    return (True, r.status_code, r.text or "")
            except Exception as e:
                last = None
                err = str(e)
                # sıradaki varyanta geç
                continue

        if last is None:
            return (False, -1, "exception")
        return (False, getattr(last, "status_code", 0) or 0, getattr(last, "text", "") or "")

    # (isteğe bağlı ama kullanışlı) mevcut kısa yöntemi verbose'a yönlendir
    def ready_check_accept(self) -> bool:
        ok, _, _ = self.ready_check_accept_verbose()
        return ok

    def dm_send(self, name_or_key: str, text: str) -> bool:
        fr = self._find_friend_by_name_or_key(name_or_key)
        if not fr:
            return False
        conv = self._ensure_dm_conversation(fr)
        if not conv:
            return False
        return self.send(conv['id'], text)

    # ============================
    # Matchmaking Ready-Check API
    # ============================
    def ready_check_status(self) -> dict:
        """/lol-matchmaking/v1/ready-check -> {state, playerResponse, ...} (yoksa boş dict)."""
        r = self._get("/lol-matchmaking/v1/ready-check")
        if r and r.status_code == 200:
            try:
                return r.json() or {}
            except Exception:
                return {}
        return {}

    def ready_check_accept(self) -> bool:
        r = self._post("/lol-matchmaking/v1/ready-check/accept")
        return bool(r and r.status_code in (200, 204))

    def ready_check_decline(self) -> bool:
        r = self._post("/lol-matchmaking/v1/ready-check/decline")
        return bool(r and r.status_code in (200, 204))

    def gameflow_phase(self) -> str:
        r = self._get("/lol-gameflow/v1/gameflow-phase")
        if r and r.status_code == 200:
            try:
                p = r.json()
                if isinstance(p, str):
                    return p.strip('"')
            except Exception:
                pass
        return ""

    def cs_session(self) -> dict:
        return self._lget("/lol-champ-select/v1/session") or {}

    def pickable_ids(self) -> set[int]:
        r = self._get("/lol-champ-select/v1/pickable-champion-ids")
        try:
            return set(r.json() or []) if r and r.status_code == 200 else set()
        except Exception:
            return set()

        # Şampiyon kataloğu (ad/alias → id)

    _champ_catalog: dict | None = None

    def champion_catalog(self) -> dict:
        if self._champ_catalog is not None:
            return self._champ_catalog
        r = self._get("/lol-game-data/assets/v1/champion-summary.json")
        by_name, by_alias, by_id = {}, {}, {}
        if r and r.status_code == 200:
            try:
                for c in (r.json() or []):
                    try:
                        cid = int(c.get("id"))
                    except Exception:
                        continue
                    name = (c.get("name") or "").strip()
                    alias = (c.get("alias") or "").strip().lower()
                    if name:  by_name[name.lower()] = cid
                    if alias: by_alias[alias] = cid
                    by_id[cid] = {"id": cid, "name": name, "alias": alias}
            except Exception:
                pass
        self._champ_catalog = {"by_name": by_name, "by_alias": by_alias, "by_id": by_id}
        return self._champ_catalog

    def champion_id_from_text(self, text: str) -> int | None:
        t = (text or "").strip().lower()
        if not t: return None
        cat = self.champion_catalog()
        return cat["by_name"].get(t) or cat["by_alias"].get(t)

    def my_pick_action(self) -> tuple[dict | None, dict]:
        """
        Döner: (action or None, full_session)
        action: {'id', 'type', 'actorCellId', 'isInProgress', 'completed', 'championId', ...}
        """
        sess = self.cs_session()
        if not sess: return None, {}
        me = sess.get("localPlayerCellId")
        for row in (sess.get("actions") or []):
            for act in row:
                if (
                        act.get("actorCellId") == me and
                        (act.get("type") or "").lower() == "pick" and
                        not act.get("completed", False)
                ):
                    return act, sess
        return None, sess

    def cs_hover(self, action_id: int, champ_id: int) -> bool:
        r = self._patch(f"/lol-champ-select/v1/session/actions/{action_id}", json={"championId": champ_id})
        return bool(r and r.status_code in (200, 204))

    def cs_lock(self, action_id: int, champ_id: int) -> bool:
        r = self._post(f"/lol-champ-select/v1/session/actions/{action_id}/complete", json={"championId": champ_id})
        return bool(r and r.status_code in (200, 204))

    def autopick_try(self, pref_ids: list[int], do_lock: bool = True) -> tuple[bool, str, int | None]:
        """
        Tercih listesinden uygun ilk şampiyonu pick'lemeyi dener.
        Döner: (ok, 'locked|hovered|reason', action_id)
        """
        act, _sess = self.my_pick_action()
        if not act:
            return False, "not_my_turn", None
        if not act.get("isInProgress", False):
            return False, "not_in_progress", act.get("id")
        action_id = int(act.get("id"))

        pickables = self.pickable_ids()
        for cid in pref_ids:
            if cid not in pickables:
                continue
            if not self.cs_hover(action_id, cid):
                continue
            if do_lock:
                if self.cs_lock(action_id, cid):
                    return True, "locked", action_id
                # lock olmazsa en azından hover yapılmıştır; başka adaya geçmiyoruz
                return True, "hovered", action_id
            else:
                return True, "hovered", action_id

        return False, "no_candidate", action_id
    # ============================
    # LOBBY & MATCHMAKING WATCHER
    # ============================
    def _lobby(self) -> dict:
        return self._lget("/lol-lobby/v2/lobby") or {}

    def _lobby_id_any(self, lobby_obj: dict) -> str | None:
        for k in ("lobbyId", "partyId", "id", "lobbyID", "partyID"):
            v = lobby_obj.get(k)
            if v is not None:
                return str(v)
        q = (lobby_obj.get("gameConfig") or {}).get("queueId")
        return f"lobby:{q}:{len(lobby_obj.get('members', []) or [])}"

    def get_lobby_id(self) -> str | None:
        return self._lobby_id_any(self._lobby())

    def _search_state(self) -> dict:
        j = self._lget("/lol-lobby/v2/lobby/matchmaking/search-state") or {}
        phase = self.gameflow_phase() or ""
        if isinstance(phase, str):
            phase = phase.strip('"')
        return {"search": j, "phase": phase}

    def watch_lobby_and_queue(self, interval: float = 1.0):
        """
        Terminal logları:
          - [LOBBY] LOBBY_CREATED id=...
          - [LOBBY] LOBBY_LEFT
          - [LOBBY] MEMBERS_CHANGED count=N
          - [LOBBY] SOLO / NOT_SOLO
          - [QUEUE] MATCHMAKING_STARTED / MATCHMAKING_STOPPED
          - [QUEUE] SEARCH_STATE=...
          - [PHASE] Matchmaking/ReadyCheck/...
          - [QUEUE] ACCEPT_WINDOW (maç bulundu)
        """
        import time
        last_lobby_id = None
        last_member_count = -1
        last_is_solo = None
        last_searching = None
        last_search_state = None
        last_phase = None

        while True:
            try:
                lob = self._lobby() or {}
                lobby_id = self._lobby_id_any(lob) if lob else None

                # Lobby create / left
                if lobby_id and lobby_id != last_lobby_id:
                    log_once("LOBBY", f"LOBBY_CREATED id={lobby_id}")
                    last_lobby_id = lobby_id
                if not lobby_id and last_lobby_id:
                    log_once("LOBBY", "LOBBY_LEFT")
                    last_lobby_id = None

                # Members & solo
                mems = (lob.get("members") or []) if lob else []
                mc = len(mems)
                if mc != last_member_count:
                    log_once("LOBBY", f"MEMBERS_CHANGED count={mc}")
                    last_member_count = mc
                is_solo = (mc == 1)
                if is_solo != last_is_solo:
                    log_once("LOBBY", "SOLO" if is_solo else "NOT_SOLO")
                    last_is_solo = is_solo

                # Matchmaking & phase
                ss = self._search_state()
                s = (ss.get("search") or {}).get("state") or ""
                phase = ss.get("phase") or ""

                searching = (s.lower() in ("in_progress", "searching")) or (phase == "Matchmaking")
                if searching != last_searching:
                    log_once("QUEUE", "MATCHMAKING_STARTED" if searching else "MATCHMAKING_STOPPED")
                    last_searching = searching

                if s and s != last_search_state:
                    log_once("QUEUE", f"SEARCH_STATE={s}")
                    last_search_state = s

                if phase != last_phase:
                    log_once("PHASE", f"{phase}")
                    last_phase = phase
                    if phase == "ReadyCheck":
                        log_once("QUEUE", "ACCEPT_WINDOW (maç bulundu)")

            except Exception as e:
                log_once("LOBBY", f"watch err: {e}")
            finally:
                time.sleep(interval)

    # ---- GeoInfo ----
    def geoinfo(self) -> dict:
        """LCU: /lol-geoinfo/v1/getlocation → bölge/ülke/locale vb. bilgileri döner."""
        r = self._get("/lol-geoinfo/v1/getlocation")
        try:
            return r.json() if r and r.status_code == 200 else {}
        except Exception:
            return {}

    def geoinfo_quick(self) -> str:
        """getlocation cevabından kısa, insan-okur bir özet üretir."""
        j = self.geoinfo() or {}
        region  = j.get("region") or j.get("webRegion") or j.get("regionId") or j.get("platformId") or "?"
        country = j.get("country") or j.get("countryCode") or j.get("ipCountry") or "?"
        locale  = j.get("locale") or j.get("webLanguage") or j.get("displayLocale") or "?"
        shard   = j.get("shard") or j.get("platform") or j.get("routing") or ""
        extra   = f" shard={shard}" if shard else ""
        return f"region={region} country={country} locale={locale}{extra}"

    # --- Lobby üyeleri: PUUID seti ---
    def _lobby_member_puuids(self) -> set[str]:
        j = self._lget("/lol-lobby/v2/lobby") or {}
        puuids = set()
        for m in (j.get("members") or []):
            p = (m.get("puuid") or "").lower()
            if p:
                puuids.add(p)
        return puuids

    # --- Grup (groupchat) katılımcılarından PUUID çıkar ---
    def _group_participant_puuids(self, conv_id: str) -> set[str]:
        puuids = set()
        for p in self.participants(conv_id):
            # pid tipik olarak "<puuid>@pvp.net" biçiminde gelir
            pid = (p.get("pid") or p.get("id") or "")
            base = pid.split("@", 1)[0].lower()
            if base:
                puuids.add(base)
        # yedek: isimden değil; isim takma/maskeleme sorun çıkarır, o yüzden es geçiyoruz
        return puuids

    # --- Lobby groupchat ID'sini PUUID kesişimi ile seç ---
    def get_lobby_group_id(self) -> Optional[str]:
        try:
            lobby_puuids = self._lobby_member_puuids()
            if not lobby_puuids:
                return None

            best_gid, best_score = None, -1
            for g in self.list_groups():
                gid = g.get("id")
                if not gid:
                    continue
                gp = self._group_participant_puuids(gid)
                if not gp:
                    continue
                score = len(gp & lobby_puuids)
                # solo ise >=1; 2+ kişi varsa en az 2 eşleşme mantıklı eşik
                if score > best_score and score >= (1 if len(lobby_puuids) <= 2 else 2):
                    best_gid, best_score = gid, score
            return best_gid
        except Exception:
            return None

    # --- ARAM Bench: list + swap ---
    def cs_bench_list(self) -> list[int]:
        """
        Champ Select oturumundan bench'teki şampiyonları döndürür (championId listesi).
        ARAM'da reroll sonrası takım bench'ine düşenler burada.
        """
        sess = self.cs_session() or {}
        bench = sess.get("benchChampions") or sess.get("bench") or []
        out = []
        for b in bench:
            try:
                cid = int(b.get("championId") or b.get("id") or 0)
                if cid: out.append(cid)
            except Exception:
                pass
        return out

    def bench_swap(self, champion_id: int) -> bool:
        """
        Bench'ten kendi seçimime champion çeker.
        LCU: POST /lol-champ-select/v1/session/bench/swap/{championId}
        """
        r = self._post(f"/lol-champ-select/v1/session/bench/swap/{int(champion_id)}")
        return bool(r and r.status_code in (200, 204))

    def autopick_try_with_bench(self, pref_ids: list[int], do_lock: bool = True) -> tuple[bool, str]:
        """
        Önce bench'te varsa hedef şampiyonu çek, sonra hover/lock dene.
        Döner: (ok, 'bench_locked|bench_swapped|locked|hovered|reason')
        """
        # Sıra bende mi?
        act, _sess = self.my_pick_action()
        if not act:
            return False, "not_my_turn"
        if not act.get("isInProgress", False):
            return False, "not_in_progress"

        action_id = int(act.get("id"))
        bench = set(self.cs_bench_list())

        # 1) Bench önceliği
        for cid in pref_ids:
            if cid in bench:
                if self.bench_swap(cid):
                    # swap sonrası kilitlemeyi dene
                    if do_lock:
                        # action aynı kalır; yine de bir refresh zarar vermez
                        a2, _ = self.my_pick_action()
                        if a2:
                            aid = int(a2.get("id"))
                            if self.cs_lock(aid, cid):
                                return True, "bench_locked"
                    return True, "bench_swapped"

        # 2) Normal pickable → hover/lock
        ok, how, _ = self.autopick_try(pref_ids, do_lock=do_lock)
        return (ok, how)

