"""Акаунти: реєстрація, вхід, сесії, профіль, особисті налаштування, ключ ІІ, керування користувачами (адмін).

Модуль не залежить від Streamlit: усе працює над сховищем із store.py (Upstash у продакшні, пам'ять у тестах).
Паролі зберігаються лише як scrypt-хеш із сіллю. Ключі ІІ шифруються (Fernet) ключем із секрету APP_SECRET.
Токени сесій у сховищі лежать лише як SHA-256, тож витік бази не дає готових сесій.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import re
import secrets
import time

SESSION_TTL = 30 * 86400
ONLINE_SEC = 300
MAX_FAILS = 8            # невдалих входів на логін за 15 хв
MAX_FAILS_IP = 40        # невдалих входів з однієї адреси за 15 хв
FAIL_WINDOW = 900
REG_PER_IP = 8           # реєстрацій з однієї адреси за годину
LOGIN_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,23}$")
EVENT_KEEP = 500
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
PROVIDERS = {
    "anthropic": {"name": "Anthropic (Claude)", "models": ["claude-haiku-5-5", "claude-sonnet-5-5"]},
    "openai": {"name": "OpenAI (GPT)", "models": ["gpt-4o-mini", "gpt-4o"]},
}
MQ_INSTRUMENTS = ("ES", "NQ")

K_USER, K_LOGIN, K_GSUB, K_USERS = "a:u:", "a:login:", "a:gsub:", "a:users"
K_SESS, K_USESS, K_PREFS, K_NOTE, K_MQ, K_EVENTS, K_SITE = "a:s:", "a:us:", "a:prefs:", "a:note:", "a:mq:", "a:events", "a:site"


def now() -> int:
    return int(time.time())


# ------------------------------------------------------------------ перевірка введення
def norm_login(s: str | None) -> str:
    return (s or "").strip().lower()


def check_login(login: str) -> str | None:
    return None if LOGIN_RE.match(login) else "login_fmt"


def check_password(pw: str, login: str = "") -> str | None:
    if len(pw or "") < 8:
        return "pw_short"
    if len(pw) > 128:
        return "pw_long"
    if login and pw.strip().lower() == login:
        return "pw_same"
    return None


def clean_name(s: str | None, fallback: str = "") -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())[:40]
    return s or fallback


def clean_email(s: str | None) -> str:
    s = (s or "").strip().lower()[:120]
    return s if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s) else ""


# ------------------------------------------------------------------ паролі
def _hash(pw: str, salt: bytes | None = None) -> dict:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode("utf-8"), salt=salt, **SCRYPT, dklen=32)
    return {"s": salt.hex(), "h": h.hex(), **SCRYPT}


def _verify(pw: str, rec: dict | None) -> bool:
    if not rec:
        _hash(pw, b"\x00" * 16)          # однаковий час відповіді для неіснуючого логіну
        return False
    try:
        h = hashlib.scrypt(pw.encode("utf-8"), salt=bytes.fromhex(rec["s"]), n=rec["n"], r=rec["r"], p=rec["p"], dklen=32)
        return hmac.compare_digest(h.hex(), rec["h"])
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ записи користувачів
def _j(x) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def get_user(store, uid: str | None) -> dict | None:
    if not uid:
        return None
    raw = store.get(K_USER + uid)
    return json.loads(raw) if raw else None


def _put(store, user: dict) -> None:
    store.set(K_USER + user["uid"], _j(user))


def get_user_by_login(store, login: str) -> dict | None:
    return get_user(store, store.get(K_LOGIN + norm_login(login)))


def users_count(store) -> int:
    return len(store.smembers(K_USERS))


def public(user: dict | None) -> dict:
    """Запис без секретів (хеш пароля, зашифрований ключ ІІ)."""
    if not user:
        return {}
    u = {k: v for k, v in user.items() if k not in ("pw", "ai")}
    ai = user.get("ai") or {}
    u["ai"] = {"provider": ai.get("provider"), "model": ai.get("model"), "tail": ai.get("tail")} if ai.get("enc") else None
    return u


def is_admin(user: dict | None, admin_list: list[str] | tuple[str, ...] = ()) -> bool:
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    keys = {norm_login(user.get("login")), (user.get("email") or "").lower()} - {""}
    return bool(keys & {norm_login(a) for a in admin_list})


def parse_admin_list(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [norm_login(x) for x in raw if x]
    return [norm_login(x) for x in re.split(r"[,\s;]+", str(raw)) if x]


# ------------------------------------------------------------------ налаштування сайту
SITE_DEFAULT = {"reg_open": True, "site_ai": True, "live_all": False}


def site_cfg(store) -> dict:
    try:
        raw = store.get(K_SITE)
        return {**SITE_DEFAULT, **(json.loads(raw) if raw else {})}
    except Exception:  # noqa: BLE001
        return dict(SITE_DEFAULT)


def set_site_cfg(store, **kw) -> dict:
    cfg = {**site_cfg(store), **kw}
    store.set(K_SITE, _j(cfg))
    return cfg


# ------------------------------------------------------------------ журнал подій
def log_event(store, kind: str, uid: str = "", login: str = "", ip: str = "", note: str = "") -> None:
    try:
        store.lpush(K_EVENTS, _j({"t": now(), "k": kind, "uid": uid, "login": login, "ip": ip, "n": note[:120]}), keep=EVENT_KEEP)
    except Exception:  # noqa: BLE001
        pass


def recent_events(store, n: int = 100) -> list[dict]:
    out = []
    for raw in store.lrange(K_EVENTS, n):
        try:
            out.append(json.loads(raw))
        except Exception:  # noqa: BLE001
            continue
    return out


# ------------------------------------------------------------------ реєстрація
def _new_uid() -> str:
    return "u_" + secrets.token_hex(8)


def _rate_ok(store, key: str, limit: int, window: int) -> bool:
    return int(store.get(key) or 0) < limit


def register_local(store, login: str, password: str, name: str = "", email: str = "", ip: str = "",
                   admin_logins: list[str] | None = None, first_is_admin: bool = False) -> tuple[dict | None, str | None]:
    """-> (користувач, код_помилки). Коди: reg_closed, login_fmt, pw_short, pw_long, pw_same, taken, rate."""
    if not site_cfg(store)["reg_open"] and users_count(store) > 0:
        return None, "reg_closed"
    login = norm_login(login)
    err = check_login(login) or check_password(password, login)
    if err:
        return None, err
    if ip and int(store.get(f"a:regip:{ip}") or 0) >= REG_PER_IP:
        return None, "rate"
    uid = _new_uid()
    if not store.setnx(K_LOGIN + login, uid):
        return None, "taken"
    first = users_count(store) == 0
    role = "admin" if (first and first_is_admin) else "user"
    user = {"uid": uid, "login": login, "name": clean_name(name, login), "email": clean_email(email), "provider": "local",
            "pw": _hash(password), "avatar": None, "picture": None, "created": now(), "last_login": now(), "last_seen": now(),
            "last_ip": ip, "ua": "", "logins": 1, "status": "active", "reason": "", "role": role, "ai": None}
    _put(store, user)
    store.sadd(K_USERS, uid)
    if ip:
        store.incr(f"a:regip:{ip}", ex=3600)
    log_event(store, "register", uid, login, ip)
    return user, None


def google_user(store, sub: str, email: str, name: str, picture: str, ip: str = "",
                admin_logins: list[str] | None = None, first_is_admin: bool = False) -> tuple[dict | None, str | None]:
    """Вхід через Google: акаунт прив'язується до sub (або email). Із локальними акаунтами не зливається навмисно:
    email у локальних не підтверджується, інакше можна було б захопити чужий кабінет."""
    ident = (sub or email or "").strip().lower()
    if not ident:
        return None, "google_bad"
    uid = store.get(K_GSUB + ident)
    user = get_user(store, uid)
    if user is None:
        if not site_cfg(store)["reg_open"] and users_count(store) > 0:
            return None, "reg_closed"
        uid = "g_" + hashlib.sha256(ident.encode()).hexdigest()[:16]
        first = users_count(store) == 0
        user = {"uid": uid, "login": "", "name": clean_name(name, (email or "google").split("@")[0]), "email": clean_email(email),
                "provider": "google", "pw": None, "avatar": None, "picture": picture or None, "created": now(), "last_login": now(),
                "last_seen": now(), "last_ip": ip, "ua": "", "logins": 0, "status": "active", "reason": "",
                "role": "admin" if (first and first_is_admin) else "user", "ai": None}
        store.set(K_GSUB + ident, uid)
        _put(store, user)
        store.sadd(K_USERS, uid)
        log_event(store, "register", uid, email, ip, "google")
    else:
        user["picture"] = picture or user.get("picture")
        if not user.get("email"):
            user["email"] = clean_email(email)
        _put(store, user)
    if user["status"] == "blocked":
        return None, "blocked"
    return user, None


# ------------------------------------------------------------------ вхід
def authenticate(store, login: str, password: str, ip: str = "") -> tuple[dict | None, str | None]:
    """-> (користувач, код_помилки). Коди: locked, bad, blocked."""
    login = norm_login(login)
    fk, ik = f"a:fail:{login}", f"a:failip:{ip}"
    if int(store.get(fk) or 0) >= MAX_FAILS or (ip and int(store.get(ik) or 0) >= MAX_FAILS_IP):
        log_event(store, "locked", "", login, ip)
        return None, "locked"
    user = get_user_by_login(store, login) if login else None
    ok = _verify(password or "", (user or {}).get("pw")) and user is not None
    if not ok:
        store.incr(fk, ex=FAIL_WINDOW)
        if ip:
            store.incr(ik, ex=FAIL_WINDOW)
        log_event(store, "login_fail", (user or {}).get("uid", ""), login, ip)
        return None, "bad"
    store.delete(fk)
    if user["status"] == "blocked":
        log_event(store, "login_blocked", user["uid"], login, ip)
        return None, "blocked"
    return user, None


def mark_login(store, user: dict, ip: str = "", ua: str = "") -> dict:
    user["last_login"] = user["last_seen"] = now()
    user["last_ip"], user["ua"] = ip, (ua or "")[:160]
    user["logins"] = int(user.get("logins") or 0) + 1
    _put(store, user)
    log_event(store, "login", user["uid"], user.get("login") or user.get("email", ""), ip, user.get("provider", ""))
    return user


def touch(store, uid: str, ip: str = "", ua: str = "") -> dict | None:
    """Оновлює «востаннє онлайн». Повертає свіжий запис (або None, якщо акаунт видалено)."""
    user = get_user(store, uid)
    if user is None:
        return None
    user["last_seen"] = now()
    if ip:
        user["last_ip"] = ip
    if ua:
        user["ua"] = ua[:160]
    _put(store, user)
    return user


def is_online(user: dict) -> bool:
    return now() - int(user.get("last_seen") or 0) < ONLINE_SEC


# ------------------------------------------------------------------ сесії (кукі «запам'ятати мене»)
def _sh(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(store, uid: str, ip: str = "") -> str:
    token = secrets.token_urlsafe(32)
    h = _sh(token)
    store.set(K_SESS + h, _j({"uid": uid, "t": now(), "ip": ip}), ex=SESSION_TTL)
    store.sadd(K_USESS + uid, h)
    return token


def resolve_session(store, token: str | None) -> dict | None:
    """Користувач за токеном; заблокований або видалений акаунт сесії не дає."""
    if not token or len(token) > 100:
        return None
    raw = store.get(K_SESS + _sh(token))
    if not raw:
        return None
    user = get_user(store, json.loads(raw).get("uid"))
    if user is None or user.get("status") == "blocked":
        return None
    return user


def peek_session(store, token: str | None) -> dict | None:
    """Користувач за токеном без перевірки блокування (щоб показати заблокованому причину)."""
    if not token or len(token) > 100:
        return None
    raw = store.get(K_SESS + _sh(token))
    return get_user(store, json.loads(raw).get("uid")) if raw else None


def destroy_session(store, token: str | None) -> None:
    if token:
        store.delete(K_SESS + _sh(token))


def destroy_all_sessions(store, uid: str) -> int:
    hs = store.smembers(K_USESS + uid)
    if hs:
        store.delete(*[K_SESS + h for h in hs])
    store.delete(K_USESS + uid)
    return len(hs)


# ------------------------------------------------------------------ профіль
def update_profile(store, uid: str, name: str | None = None, email: str | None = None) -> dict | None:
    user = get_user(store, uid)
    if not user:
        return None
    if name is not None:
        user["name"] = clean_name(name, user.get("login") or user["name"])
    if email is not None:
        user["email"] = clean_email(email)
    _put(store, user)
    return user


def change_login(store, uid: str, new_login: str) -> tuple[dict | None, str | None]:
    user = get_user(store, uid)
    if not user or user.get("provider") != "local":
        return None, "not_local"
    new = norm_login(new_login)
    err = check_login(new)
    if err:
        return None, err
    if new == user["login"]:
        return user, None
    if not store.setnx(K_LOGIN + new, uid):
        return None, "taken"
    store.delete(K_LOGIN + user["login"])
    user["login"] = new
    _put(store, user)
    log_event(store, "login_changed", uid, new)
    return user, None


def change_password(store, uid: str, old: str, new: str, keep_token: str | None = None) -> tuple[bool, str | None]:
    user = get_user(store, uid)
    if not user or user.get("provider") != "local":
        return False, "not_local"
    if not _verify(old or "", user.get("pw")):
        return False, "bad_old"
    err = check_password(new, user["login"])
    if err:
        return False, err
    user["pw"] = _hash(new)
    _put(store, user)
    destroy_all_sessions(store, uid)         # інші пристрої розлогінюються
    log_event(store, "pw_changed", uid, user["login"])
    return True, None


def process_avatar(data: bytes, size: int = 160) -> str | None:
    """Квадратна мініатюра JPEG як data-URL (≈6–10 КБ). None, якщо це не зображення."""
    if not data or len(data) > 6 * 1024 * 1024:
        return None
    try:
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        w, h = im.size
        s = min(w, h)
        im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((size, size))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=84, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001
        return None


def set_avatar(store, uid: str, data: bytes | None) -> tuple[dict | None, str | None]:
    user = get_user(store, uid)
    if not user:
        return None, "nouser"
    if data is None:
        user["avatar"] = None
    else:
        url = process_avatar(data)
        if not url:
            return None, "avatar_bad"
        user["avatar"] = url
    _put(store, user)
    return user, None


def avatar_of(user: dict | None) -> str | None:
    return (user or {}).get("avatar") or (user or {}).get("picture")


def delete_account(store, uid: str) -> None:
    user = get_user(store, uid)
    if not user:
        return
    destroy_all_sessions(store, uid)
    if user.get("login"):
        store.delete(K_LOGIN + user["login"])
    store.delete(K_USER + uid, K_PREFS + uid, K_NOTE + uid, *[f"{K_MQ}{uid}:{i}" for i in MQ_INSTRUMENTS])
    store.srem(K_USERS, uid)
    log_event(store, "deleted", uid, user.get("login") or user.get("email", ""))


# ------------------------------------------------------------------ власний ІІ (ключ шифрується)
class Vault:
    """Шифрування секретів користувачів. Ключ виводиться з APP_SECRET (або з іншого серверного секрету)."""

    def __init__(self, secret: str):
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(hashlib.sha256((secret + "|ash-vault").encode()).digest())
        self._f = Fernet(key)

    def enc(self, text: str) -> str:
        return self._f.encrypt(text.encode()).decode()

    def dec(self, token: str) -> str | None:
        try:
            return self._f.decrypt(token.encode()).decode()
        except Exception:  # noqa: BLE001
            return None


def set_ai(store, vault: Vault, uid: str, provider: str, model: str, key: str) -> tuple[dict | None, str | None]:
    user = get_user(store, uid)
    if not user:
        return None, "nouser"
    key = (key or "").strip()
    if provider not in PROVIDERS or len(key) < 20 or len(key) > 300 or re.search(r"\s", key):
        return None, "ai_key_bad"
    user["ai"] = {"provider": provider, "model": (model or PROVIDERS[provider]["models"][0])[:60], "enc": vault.enc(key), "tail": key[-4:]}
    _put(store, user)
    return user, None


def set_ai_model(store, uid: str, model: str) -> None:
    user = get_user(store, uid)
    if user and user.get("ai"):
        user["ai"]["model"] = model[:60]
        _put(store, user)


def clear_ai(store, uid: str) -> None:
    user = get_user(store, uid)
    if user:
        user["ai"] = None
        _put(store, user)


def get_ai(user: dict | None, vault: Vault | None) -> dict | None:
    """-> {'provider','model','key'} або None."""
    ai = (user or {}).get("ai")
    if not ai or not ai.get("enc") or vault is None:
        return None
    key = vault.dec(ai["enc"])
    return {"provider": ai["provider"], "model": ai["model"], "key": key} if key else None


# ------------------------------------------------------------------ особисті дані користувача
def load_prefs(store, uid: str) -> dict:
    try:
        raw = store.get(K_PREFS + uid)
        return json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        return {}


def save_prefs(store, uid: str, prefs: dict) -> None:
    store.set(K_PREFS + uid, _j(prefs))


def load_note(store, uid: str) -> str | None:
    raw = store.get(K_NOTE + uid)
    return json.loads(raw)["text"] if raw else None


def save_note(store, uid: str, text: str) -> None:
    store.set(K_NOTE + uid, _j({"text": text[:20000], "saved": now()}))


def save_levels(store, uid: str, inst: str, levels: dict) -> None:
    store.set(f"{K_MQ}{uid}:{inst}", _j({"levels": levels, "saved": now()}), ex=259200)


def load_levels(store, uid: str, inst: str) -> dict | None:
    raw = store.get(f"{K_MQ}{uid}:{inst}")
    if not raw:
        return None
    d = json.loads(raw)
    return {"levels": {k: float(v) for k, v in d["levels"].items()}, "saved": int(d["saved"])}


def clear_levels(store, uid: str, inst: str) -> None:
    store.delete(f"{K_MQ}{uid}:{inst}")


# ------------------------------------------------------------------ адмін
def list_users(store) -> list[dict]:
    uids = store.smembers(K_USERS)
    out = []
    for raw in store.mget([K_USER + u for u in uids]):
        if raw:
            out.append(json.loads(raw))
    out.sort(key=lambda u: -int(u.get("last_seen") or 0))
    return out


def stats(users: list[dict]) -> dict:
    t = now()
    return {"total": len(users), "online": sum(is_online(u) for u in users),
            "blocked": sum(u.get("status") == "blocked" for u in users),
            "new7": sum(t - int(u.get("created") or 0) < 7 * 86400 for u in users),
            "active24": sum(t - int(u.get("last_seen") or 0) < 86400 for u in users)}


def set_blocked(store, uid: str, blocked: bool, reason: str = "", by: str = "") -> dict | None:
    user = get_user(store, uid)
    if not user:
        return None
    user["status"] = "blocked" if blocked else "active"
    user["reason"] = reason[:120] if blocked else ""
    _put(store, user)
    if blocked:
        destroy_all_sessions(store, uid)
    log_event(store, "blocked" if blocked else "unblocked", uid, user.get("login") or user.get("email", ""), "", f"by {by} {reason}".strip())
    return user


def admin_reset_password(store, uid: str, by: str = "") -> str | None:
    """Тимчасовий пароль для локального акаунта (показується адміну один раз)."""
    user = get_user(store, uid)
    if not user or user.get("provider") != "local":
        return None
    temp = secrets.token_urlsafe(9)
    user["pw"] = _hash(temp)
    _put(store, user)
    destroy_all_sessions(store, uid)
    log_event(store, "pw_reset", uid, user["login"], "", f"by {by}")
    return temp


def set_live(store, uid: str, on: bool) -> dict | None:
    """Дозвіл на живі тики LSE (ключ браузера потрапляє на сторінку лише тим, кому видано дозвіл)."""
    user = get_user(store, uid)
    if not user:
        return None
    user["live"] = bool(on)
    _put(store, user)
    log_event(store, "live_on" if on else "live_off", uid, user.get("login") or user.get("email", ""))
    return user


def can_live(user: dict | None, admin_list: list[str] | tuple[str, ...], cfg: dict) -> bool:
    if not user or user.get("uid") == "guest":
        return False
    return bool(cfg.get("live_all") or user.get("live") or is_admin(user, admin_list))
