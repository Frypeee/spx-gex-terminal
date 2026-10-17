"""Екрани акаунтів у Streamlit: вхід і реєстрація, особистий кабінет, адмін-панель, сесії, персональні налаштування.

Логіка живе в auth.py; тут лише інтерфейс і зв'язок із st.session_state.
"""
from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import assistant as AI
import auth as A
import i18n as I
from store import StoreError

COOKIE = "ash_sess"
KYIV = ZoneInfo("Europe/Kyiv")
GUEST = {"uid": "guest", "login": "guest", "name": "Guest", "email": "", "provider": "local", "avatar": None, "picture": None,
         "status": "active", "role": "user", "ai": None, "created": 0, "last_seen": 0, "last_login": 0, "logins": 0}

# ключі st.session_state, які зберігаються в акаунті користувача
PREF_KEYS = ["lang", "scope", "sess", "chart_h", "basis_override", "tf", "inst", "vis_layers", "vis_hidden", "rpanel",
             "al_master", "al_sound", "al_levels", "al_dist", "al_vol", "strikes_mode", "ai_model"]


@dataclass
class Ctx:
    store: object
    vault: A.Vault | None = None
    admin_list: list[str] = field(default_factory=list)
    google: bool = False                 # у Secrets налаштовано [auth] (Google OIDC)
    site_ai_key: str | None = None       # спільний ключ Anthropic сайту
    disabled: bool = False               # ASH_AUTH_DISABLED=1: без входу (лише розробка й тести)


def tr(key: str, **kw) -> str:
    s = I.t(key, st.session_state.get("lang"))
    return s.format(**kw) if kw else s


def lang() -> str:
    return I.norm(st.session_state.get("lang"))


# ------------------------------------------------------------------ клієнт
def client_info() -> tuple[str, str]:
    """(IP, User-Agent) з заголовків запиту (за проксі Streamlit Cloud беремо X-Forwarded-For)."""
    try:
        h = st.context.headers
        ip = (h.get("X-Forwarded-For") or h.get("X-Real-Ip") or "").split(",")[0].strip()
        return ip[:45], (h.get("User-Agent") or "")[:160]
    except Exception:  # noqa: BLE001
        return "", ""


def _cookie_token() -> str | None:
    try:
        v = st.context.cookies.get(COOKIE)
        return v if isinstance(v, str) and v else None
    except Exception:  # noqa: BLE001
        return None


def emit_cookie(value: str | None, days: int = 30) -> None:
    """Ставить (або стирає, якщо value=None) кукі сесії з боку браузера: iframe має доступ до батьківської сторінки."""
    age = int(days * 86400) if value else 0
    v = value or ""
    js = ("<script>try{var p=window.parent;var sec=p.location.protocol==='https:'?';Secure':'';"
          f"p.document.cookie='{COOKIE}={v};path=/;max-age={age};SameSite=Lax'+sec;}}catch(e){{}}</script>")
    with st.container(key="ckie"):
        if hasattr(st, "iframe"):
            st.iframe(js, height=1)
        else:  # pragma: no cover
            import streamlit.components.v1 as components
            components.html(js, height=1)


# ------------------------------------------------------------------ сесія
def _set_user(ctx: Ctx, user: dict, token: str | None = None) -> None:
    ss = st.session_state
    ss["uid"], ss["user"], ss["_rv"] = user["uid"], user, time.time()
    if token:
        ss["sess_tok"] = token


def logout(ctx: Ctx, reason: str | None = None) -> None:
    ss = st.session_state
    tok = ss.get("sess_tok") or _cookie_token()
    try:
        if tok:
            A.destroy_session(ctx.store, tok)
        if ss.get("uid"):
            A.log_event(ctx.store, "logout", ss["uid"], (ss.get("user") or {}).get("login", ""))
    except StoreError:
        pass
    is_google = (ss.get("user") or {}).get("provider") == "google"
    for k in [k for k in list(ss.keys()) if k not in ("lang",)]:        # чистий стан для наступного користувача
        try:
            del ss[k]
        except Exception:  # noqa: BLE001
            pass
    ss["_clear_cookie"] = True
    if reason:
        ss["_auth_msg"] = reason
    if is_google and ctx.google:
        try:
            st.logout()
            return
        except Exception:  # noqa: BLE001
            pass
    st.rerun()


def gate(ctx: Ctx) -> dict:
    """Повертає поточного користувача або показує сторінку входу й зупиняє скрипт."""
    ss = st.session_state
    if ctx.disabled:
        ss.setdefault("uid", GUEST["uid"])
        ss["user"] = GUEST
        return GUEST
    ip, ua = client_info()
    user = None
    try:
        uid = ss.get("uid")
        if uid:
            if time.time() - ss.get("_rv", 0) > 60:
                user = A.touch(ctx.store, uid, ip, ua)
                ss["_rv"] = time.time()
                if user is None or user.get("status") == "blocked":
                    logout(ctx, "blocked" if user else None)
                    return GUEST
                ss["user"] = user
            else:
                user = ss.get("user")
        if user is None:
            tok = _cookie_token()
            user = A.resolve_session(ctx.store, tok)
            if user is not None:
                _set_user(ctx, user, tok)
                A.touch(ctx.store, user["uid"], ip, ua)
            elif tok:
                old = A.peek_session(ctx.store, tok)
                if old and old.get("status") == "blocked":
                    ss["_auth_msg"] = "blocked"
        if user is None and ctx.google:
            user = _google_login(ctx, ip, ua)
    except StoreError:
        st.error(tr("a.err.store"))
        st.stop()
    if user is None:
        auth_page(ctx)
        st.stop()
    if ss.pop("_set_cookie", None):
        emit_cookie(ss.get("sess_tok"))
    return user


def _google_login(ctx: Ctx, ip: str, ua: str) -> dict | None:
    try:
        u = st.user
        if not getattr(u, "is_logged_in", False):
            return None
        sub, email = str(u.get("sub") or ""), str(u.get("email") or "")
    except Exception:  # noqa: BLE001
        return None
    user, err = A.google_user(ctx.store, sub, email, str(u.get("name") or ""), str(u.get("picture") or ""), ip,
                              first_is_admin=not ctx.admin_list)
    if user is None:
        st.session_state["_auth_msg"] = err
        return None
    if not st.session_state.get("_g_done"):
        user = A.mark_login(ctx.store, user, ip, ua)
        st.session_state["_g_done"] = True
    _set_user(ctx, user)
    return user


# ------------------------------------------------------------------ сторінка входу
def auth_page(ctx: Ctx) -> None:
    ss = st.session_state
    st.markdown("<style>[data-testid='stSidebar'],[data-testid='stExpandSidebarButton'],[data-testid='stSidebarCollapsedControl']{display:none}</style>",
                unsafe_allow_html=True)
    if ss.pop("_clear_cookie", False):
        emit_cookie(None)
    _, mid, _ = st.columns([1, 1.15, 1])
    with mid:
        st.markdown(f'<div class="auth-h"><div class="auth-t">{html.escape(tr("app"))}</div><div class="auth-s">{html.escape(tr("a.tag"))}</div></div>',
                    unsafe_allow_html=True)
        st.radio("Language", I.LANGS, horizontal=True, key="lang", label_visibility="collapsed")
        msg = ss.pop("_auth_msg", None)
        if msg:
            st.error(tr("a.err." + msg) if msg in ("blocked", "reg_closed", "google_bad") else msg)
        try:
            if not getattr(ctx.store, "persistent", True) and A.users_count(ctx.store) == 0:      # підказка власнику на етапі налаштування
                st.warning(tr("a.mem_warn"))
        except StoreError:
            pass
        if ctx.google:
            if st.button(tr("a.google"), key="g_btn", use_container_width=True, icon=":material/login:"):
                st.login()
            st.markdown(f'<div class="auth-or"><span>{html.escape(tr("a.or"))}</span></div>', unsafe_allow_html=True)
        t_in, t_up = st.tabs([tr("a.signin"), tr("a.signup")])
        with t_in:
            with st.form("f_login"):
                lg = st.text_input(tr("a.login"), key="in_login", autocomplete="username")
                pw = st.text_input(tr("a.password"), type="password", key="in_pw", autocomplete="current-password")
                go = st.form_submit_button(tr("a.enter"), type="primary", use_container_width=True)
            st.caption(tr("a.no_recover"))
            if go:
                _do_login(ctx, lg, pw)
        with t_up:
            first = False
            try:
                first = A.users_count(ctx.store) == 0 and not ctx.admin_list
            except StoreError:
                pass
            if first:
                st.info(tr("a.first_admin"))
            with st.form("f_reg"):
                lg = st.text_input(tr("a.login"), key="up_login", help=tr("a.login_hint"), autocomplete="username")
                nm = st.text_input(tr("a.name"), key="up_name")
                em = st.text_input(tr("a.email"), key="up_email")
                p1 = st.text_input(tr("a.password"), type="password", key="up_pw", help=tr("a.pw_hint"), autocomplete="new-password")
                p2 = st.text_input(tr("a.password2"), type="password", key="up_pw2", autocomplete="new-password")
                go = st.form_submit_button(tr("a.create"), type="primary", use_container_width=True)
            if go:
                _do_register(ctx, lg, nm, em, p1, p2)


def _finish_login(ctx: Ctx, user: dict, ip: str, ua: str) -> None:
    user = A.mark_login(ctx.store, user, ip, ua)
    tok = A.create_session(ctx.store, user["uid"], ip)
    _set_user(ctx, user, tok)
    st.session_state["_set_cookie"] = True
    st.session_state.pop("_clear_cookie", None)
    st.rerun()


def _do_login(ctx: Ctx, login: str, pw: str) -> None:
    ip, ua = client_info()
    try:
        user, err = A.authenticate(ctx.store, login, pw, ip)
        if err:
            st.error(tr("a.err." + err))
            return
        _finish_login(ctx, user, ip, ua)
    except StoreError:
        st.error(tr("a.err.store"))


def _do_register(ctx: Ctx, login: str, name: str, email: str, p1: str, p2: str) -> None:
    if p1 != p2:
        st.error(tr("a.err.pw_mismatch"))
        return
    ip, ua = client_info()
    try:
        user, err = A.register_local(ctx.store, login, p1, name, email, ip, first_is_admin=not ctx.admin_list)
        if err:
            st.error(tr("a.err." + err))
            return
        tok = A.create_session(ctx.store, user["uid"], ip)
        _set_user(ctx, user, tok)
        st.session_state["_set_cookie"] = True
        st.rerun()
    except StoreError:
        st.error(tr("a.err.store"))


# ------------------------------------------------------------------ персональні налаштування
def _pack(v):
    if isinstance(v, (set, frozenset)):
        return {"_set": sorted(v)}
    return v


def _unpack(v):
    return set(v["_set"]) if isinstance(v, dict) and "_set" in v else v


_AL_CHECK = re.compile(r"^al_[a-z0-9_]+_(app|tg)$")        # галочки матриці сповіщень (кнопки al_test тощо не зберігаємо)


def _pref_ok(k: str) -> bool:
    return k in PREF_KEYS or bool(_AL_CHECK.match(k))


def _pref_keys() -> list[str]:
    ss = st.session_state
    return PREF_KEYS + [k for k in list(ss.keys()) if isinstance(k, str) and k not in PREF_KEYS and _AL_CHECK.match(k)]


def load_state(ctx: Ctx, user: dict) -> None:
    """Один раз за сесію після входу: підставляє збережені налаштування користувача до session_state."""
    ss = st.session_state
    if ss.get("_state_uid") == user["uid"]:
        return
    ss["_state_uid"] = user["uid"]
    if ctx.disabled:
        return
    try:
        prefs = A.load_prefs(ctx.store, user["uid"])
    except StoreError:
        return
    for k, v in prefs.items():
        if _pref_ok(k):
            try:
                ss[k] = _unpack(v)
            except Exception:  # noqa: BLE001
                pass
    ss["_prefs_hash"] = hash(repr(sorted((k, repr(_pack(ss[k]))) for k in prefs if k in ss)))


def save_state(ctx: Ctx, force: bool = False) -> None:
    """Зберігає налаштування користувача, якщо вони змінилися (не частіше ніж раз на 2 с)."""
    ss = st.session_state
    uid = ss.get("uid")
    if ctx.disabled or not uid or uid == "guest" or ss.get("_state_uid") != uid:
        return
    data = {k: _pack(ss[k]) for k in _pref_keys() if k in ss}
    h = hash(repr(sorted((k, repr(v)) for k, v in data.items())))
    if h == ss.get("_prefs_hash") or (not force and time.time() - ss.get("_prefs_t", 0) < 2):
        return
    try:
        A.save_prefs(ctx.store, uid, data)
        ss["_prefs_hash"], ss["_prefs_t"] = h, time.time()
    except StoreError:
        pass


def heartbeat(ctx: Ctx) -> None:
    """Не частіше ніж раз на хвилину: «востаннє онлайн» і перевірка блокування (виклик із фрагмента графіка)."""
    ss = st.session_state
    if ctx.disabled or not ss.get("uid") or ss["uid"] == "guest":
        return
    if time.time() - ss.get("_hb", 0) < 60:
        return
    ss["_hb"] = time.time()
    try:
        ip, ua = client_info()
        user = A.touch(ctx.store, ss["uid"], ip, ua)
    except StoreError:
        return
    if user is None or user.get("status") == "blocked":
        logout(ctx, "blocked" if user else None)
    else:
        ss["user"] = user


# ------------------------------------------------------------------ ІІ користувача
def ai_for(ctx: Ctx, user: dict) -> dict | None:
    """Який ІІ використати: власний ключ користувача, інакше спільний ключ сайту (якщо дозволено)."""
    own = A.get_ai(user, ctx.vault) if user.get("uid") != "guest" else None
    if own:
        return {**own, "source": "user"}
    if ctx.site_ai_key:
        try:
            allowed = A.site_cfg(ctx.store)["site_ai"]
        except StoreError:
            allowed = True
        if allowed:
            return {"provider": "anthropic", "model": None, "key": ctx.site_ai_key, "source": "site"}
    return None


# ------------------------------------------------------------------ вигляд
def fmt_ts(ts: int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(int(ts), KYIV).strftime("%d.%m.%Y %H:%M")


def _initial_svg(user: dict) -> str:
    """Кружок з літерою для таблиці (коли фото немає)."""
    import base64
    ch = html.escape((user.get("name") or user.get("login") or user.get("email") or "?")[:1].upper())
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="32" fill="#8a97b8"/>'
           f'<text x="32" y="43" font-size="30" font-family="Arial" text-anchor="middle" fill="#fff">{ch}</text></svg>')
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def avatar_html(user: dict, size: int = 40) -> str:
    src = A.avatar_of(user)
    if src:
        return f'<img class="av" style="width:{size}px;height:{size}px" src="{html.escape(src, quote=True)}" alt="">'
    ch = html.escape((user.get("name") or user.get("login") or "?")[:1].upper())
    return f'<div class="av av0" style="width:{size}px;height:{size}px;font-size:{int(size * .45)}px">{ch}</div>'


def user_card(ctx: Ctx, user: dict, go) -> None:
    """Блок користувача в лівому меню: фото, ім'я, кнопки кабінету, адмінки й виходу."""
    handle = user.get("login") or user.get("email") or ""
    st.markdown(f'<div class="ucard">{avatar_html(user, 40)}<div class="ui"><b>{html.escape(user.get("name") or "")}</b>'
                f'<span>@{html.escape(handle)}</span></div></div>', unsafe_allow_html=True)
    if user.get("uid") == "guest":
        return
    c1, c2 = st.columns(2)
    c1.button(tr("a.profile"), key="u_profile", icon=":material/person:", use_container_width=True, on_click=go, args=("profile",))
    c2.button(tr("a.logout"), key="u_logout", icon=":material/logout:", use_container_width=True, on_click=lambda: logout(ctx))
    if A.is_admin(user, ctx.admin_list):
        st.button(tr("a.admin"), key="u_admin", icon=":material/shield_person:", use_container_width=True, on_click=go, args=("admin",))


def page_head(title: str) -> None:
    st.markdown(f'<div class="mqh"><span class="a">{html.escape(title)}</span></div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ особистий кабінет
def profile_page(ctx: Ctx, user: dict) -> dict:
    ss = st.session_state
    page_head(tr("a.p.title"))
    if user.get("uid") == "guest":
        st.info("Guest mode")
        return user
    uid = user["uid"]
    c_av, c_info = st.columns([0.45, 3], vertical_alignment="center")
    c_av.markdown(avatar_html(user, 96), unsafe_allow_html=True)
    c_info.markdown(f"**{html.escape(user.get('name') or '')}**  \n@{html.escape(user.get('login') or user.get('email') or '')}  \n"
                    f"<span class='muted'>{tr('a.p.since')}: {fmt_ts(user.get('created'))} · {tr('a.p.last')}: {fmt_ts(user.get('last_login'))}</span>",
                    unsafe_allow_html=True)
    t_prof, t_sec, t_ai, t_data = st.tabs([tr("a.p.t_profile"), tr("a.p.t_security"), tr("a.p.t_ai"), tr("a.p.t_data")])
    msg = ss.pop("_p_msg", None)
    if msg:
        (st.success if msg[0] == "ok" else st.error)(msg[1])

    with t_prof:
        up = st.file_uploader(tr("a.p.upload"), type=["png", "jpg", "jpeg", "webp"], key="p_avatar")
        ca, cb = st.columns(2)
        if up is not None and ca.button(tr("a.p.save"), key="p_av_save", icon=":material/save:", use_container_width=True):
            u, err = A.set_avatar(ctx.store, uid, up.getvalue())
            _flash(err, u)
        if user.get("avatar") and cb.button(tr("a.p.remove_avatar"), key="p_av_del", icon=":material/delete:", use_container_width=True):
            u, err = A.set_avatar(ctx.store, uid, None)
            _flash(err, u)
        with st.form("p_form"):
            nm = st.text_input(tr("a.name"), value=user.get("name") or "")
            em = st.text_input("Email", value=user.get("email") or "")
            if st.form_submit_button(tr("a.p.save"), type="primary"):
                u = A.update_profile(ctx.store, uid, nm, em)
                _flash(None, u)

    with t_sec:
        if user.get("provider") == "google":
            st.info(tr("a.p.google_note"))
        else:
            with st.form("p_login"):
                nl = st.text_input(tr("a.p.new_login"), value=user.get("login") or "", help=tr("a.login_hint"))
                if st.form_submit_button(tr("a.p.change_login")):
                    u, err = A.change_login(ctx.store, uid, nl)
                    _flash(err, u, tr("a.p.login_ok"))
            with st.form("p_pw"):
                old = st.text_input(tr("a.p.cur_pw"), type="password")
                new = st.text_input(tr("a.p.new_pw"), type="password", help=tr("a.pw_hint"))
                if st.form_submit_button(tr("a.p.change_pw")):
                    ok, err = A.change_password(ctx.store, uid, old, new)
                    if ok:
                        tok = A.create_session(ctx.store, uid)            # цей пристрій лишається у системі
                        ss["sess_tok"] = tok
                        ss["_set_cookie"] = True
                    _flash(err, ok or None, tr("a.p.pw_ok"))
        if st.button(tr("a.p.logout_all"), key="p_kick", icon=":material/devices:"):
            A.destroy_all_sessions(ctx.store, uid)
            logout(ctx)

    with t_ai:
        _ai_tab(ctx, user)

    with t_data:
        st.caption(tr("a.p.data_note"))
        if st.button(tr("a.p.reset_prefs"), key="p_reset", icon=":material/restart_alt:"):
            A.save_prefs(ctx.store, uid, {})
            for k in _pref_keys():
                ss.pop(k, None)
            ss["_p_msg"] = ("ok", tr("a.p.reset_ok"))
            st.rerun()
        st.divider()
        st.markdown(f"**{tr('a.p.del_title')}**")
        pw = st.text_input(tr("a.p.del_pw"), type="password", key="p_del_pw") if user.get("provider") == "local" else ""
        sure = st.checkbox(tr("a.p.del_confirm"), key="p_del_ok")
        if st.button(tr("a.p.del_btn"), key="p_del", disabled=not sure, icon=":material/delete_forever:"):
            if user.get("provider") == "local":
                u2, err = A.authenticate(ctx.store, user["login"], pw)
                if err:
                    st.error(tr("a.err.bad"))
                    return user
            A.delete_account(ctx.store, uid)
            logout(ctx)
    return ss.get("user") or user


def _flash(err: str | None, ok_obj, ok_text: str | None = None) -> None:
    ss = st.session_state
    if err or not ok_obj:
        ss["_p_msg"] = ("err", tr("a.err." + err) if err else "?")
    else:
        ss["_p_msg"] = ("ok", ok_text or tr("a.p.saved"))
        if isinstance(ok_obj, dict) and ok_obj.get("uid"):
            ss["user"] = ok_obj
    st.rerun()


def _ai_tab(ctx: Ctx, user: dict) -> None:
    uid, ss = user["uid"], st.session_state
    st.caption(tr("a.p.ai_intro"))
    ai = user.get("ai")
    if ai and ai.get("enc"):
        pname = A.PROVIDERS.get(ai["provider"], {}).get("name", ai["provider"])
        st.success(tr("a.p.ai_connected", p=pname, m=ai["model"], t=ai.get("tail", "")))
        mods = list(dict.fromkeys(A.PROVIDERS.get(ai["provider"], {}).get("models", []) + [ai["model"]]))
        nm = st.selectbox(tr("a.p.ai_model"), mods, index=mods.index(ai["model"]), key="p_ai_m2")
        if nm != ai["model"]:
            A.set_ai_model(ctx.store, uid, nm)
            ss["user"] = A.get_user(ctx.store, uid)
            st.rerun()
        c1, c2 = st.columns(2)
        if c1.button(tr("a.p.ai_check"), key="p_ai_chk", icon=":material/check_circle:", use_container_width=True):
            g = A.get_ai(user, ctx.vault)
            err = AI.check_key(g["key"], g["provider"], g["model"]) if g else "—"
            (st.error if err else st.success)(err or tr("a.p.ai_ok"))
        if c2.button(tr("a.p.ai_remove"), key="p_ai_rm", icon=":material/link_off:", use_container_width=True):
            A.clear_ai(ctx.store, uid)
            ss["user"] = A.get_user(ctx.store, uid)
            st.rerun()
        return
    if ctx.site_ai_key:
        st.info(tr("a.p.ai_site"))
    with st.form("p_ai_form"):
        prov = st.selectbox(tr("a.p.ai_provider"), list(A.PROVIDERS), format_func=lambda p: A.PROVIDERS[p]["name"])
        model = st.selectbox(tr("a.p.ai_model"), sum((v["models"] for v in A.PROVIDERS.values()), []),
                             help="Anthropic: claude-*, OpenAI: gpt-*")
        key = st.text_input(tr("a.p.ai_key"), type="password", autocomplete="off")
        go = st.form_submit_button(tr("a.p.ai_save"), type="primary")
    if go:
        if ctx.vault is None:
            st.error("APP_SECRET?")
            return
        if model not in A.PROVIDERS[prov]["models"]:
            model = A.PROVIDERS[prov]["models"][0]
        err = AI.check_key(key.strip(), prov, model) if len(key.strip()) >= 20 else None
        if err and "401" in err:
            st.error(err)
            return
        u, e = A.set_ai(ctx.store, ctx.vault, uid, prov, model, key)
        _flash(e, u, tr("a.p.ai_on"))


# ------------------------------------------------------------------ адмін-панель
def admin_page(ctx: Ctx, me: dict) -> None:
    ss = st.session_state
    page_head(tr("a.ad.title"))
    if not A.is_admin(me, ctx.admin_list):
        st.error("403")
        return
    try:
        users = A.list_users(ctx.store)
    except StoreError:
        st.error(tr("a.err.store"))
        return
    s = A.stats(users)
    m = st.columns(5)
    for col, (k, v) in zip(m, [("total", s["total"]), ("online", s["online"]), ("new7", s["new7"]), ("active24", s["active24"]), ("blocked", s["blocked"])]):
        col.metric(tr("a.ad." + k), v)
    if not getattr(ctx.store, "persistent", True):
        st.warning(tr("a.mem_warn"))
    t_u, t_e, t_s = st.tabs([tr("a.ad.t_users"), tr("a.ad.t_events"), tr("a.ad.t_site")])

    with t_u:
        c1, c2 = st.columns([2, 1])
        q = c1.text_input(tr("a.ad.search"), key="ad_q", label_visibility="collapsed", placeholder=tr("a.ad.search")).strip().lower()
        flt = c2.segmented_control(tr("a.ad.filter"), ["all", "online", "blocked"], default="all", key="ad_f", label_visibility="collapsed",
                                   format_func=lambda x: tr("a.ad.f_" + x)) or "all"
        rows = []
        for u in users:
            if flt == "online" and not A.is_online(u):
                continue
            if flt == "blocked" and u.get("status") != "blocked":
                continue
            hay = " ".join([u.get("login") or "", u.get("name") or "", u.get("email") or ""]).lower()
            if q and q not in hay:
                continue
            st_txt = ("🔴 " + tr("a.ad.blk")) if u.get("status") == "blocked" else (("🟢 " + tr("a.ad.on")) if A.is_online(u) else ("⚪ " + tr("a.ad.off")))
            rows.append({"": A.avatar_of(u) or _initial_svg(u), tr("a.ad.c_status"): st_txt, tr("a.ad.c_user"): u.get("login") or u.get("email"),
                         tr("a.ad.c_name"): u.get("name"), tr("a.ad.c_type"): u.get("provider"), tr("a.ad.c_created"): fmt_ts(u.get("created")),
                         tr("a.ad.c_seen"): fmt_ts(u.get("last_seen")), tr("a.ad.c_logins"): u.get("logins", 0),
                         tr("a.ad.c_ai"): "✓" if (u.get("ai") or {}).get("enc") else "", tr("a.ad.live"): "⚡" if u.get("live") else "", tr("a.ad.c_ip"): u.get("last_ip") or ""})
        df = pd.DataFrame(rows)
        st.dataframe(df, hide_index=True, use_container_width=True, height=min(520, 60 + 36 * max(len(rows), 1)),
                     column_config={"": st.column_config.ImageColumn("", width="small")})
        _admin_actions(ctx, me, users)

    with t_e:
        ev = A.recent_events(ctx.store, 150)
        if not ev:
            st.caption(tr("a.ad.no_events"))
        else:
            st.dataframe(pd.DataFrame([{"": fmt_ts(e["t"]), "event": tr("a.ev." + e["k"]) if ("a.ev." + e["k"]) in I._D else e["k"],
                                        "user": e.get("login") or e.get("uid"), "IP": e.get("ip"), "info": e.get("n")} for e in ev]),
                         hide_index=True, use_container_width=True, height=520)

    with t_s:
        cfg = A.site_cfg(ctx.store)
        reg = st.toggle(tr("a.ad.reg_open"), value=cfg["reg_open"], key="ad_reg")
        sai = st.toggle(tr("a.ad.site_ai"), value=cfg["site_ai"], key="ad_sai", disabled=not ctx.site_ai_key)
        lva = st.toggle(tr("a.ad.live_all"), value=cfg["live_all"], key="ad_live_all")
        if reg != cfg["reg_open"] or sai != cfg["site_ai"] or lva != cfg["live_all"]:
            A.set_site_cfg(ctx.store, reg_open=reg, site_ai=sai, live_all=lva)
            st.toast(tr("a.ad.done"))
        st.caption(f"Store: {'Upstash' if getattr(ctx.store, 'persistent', False) else 'memory'} · ADMIN_USERS: {', '.join(ctx.admin_list) or '—'} · "
                   f"Google: {'on' if ctx.google else 'off'}")


def _admin_actions(ctx: Ctx, me: dict, users: list[dict]) -> None:
    ss = st.session_state
    if not users:
        return
    st.divider()
    labels = {u["uid"]: f"{u.get('login') or u.get('email')} · {u.get('name') or ''}" for u in users}
    uid = st.selectbox(tr("a.ad.pick"), list(labels), format_func=lambda x: labels[x], key="ad_pick")
    u = next(x for x in users if x["uid"] == uid)
    temp = ss.pop("_temp_pw", None)
    if temp and temp[0] == uid:
        st.warning(tr("a.ad.temp"))
        st.code(temp[1], language=None)
    is_me = uid == me["uid"]
    if is_me:
        st.caption(tr("a.ad.self"))
    c1, c2, c3 = st.columns(3)
    blocked = u.get("status") == "blocked"
    if blocked:
        if c1.button(tr("a.ad.unblock"), key="ad_unblock", icon=":material/lock_open:", use_container_width=True):
            A.set_blocked(ctx.store, uid, False, by=me.get("login", ""))
            st.rerun()
        if u.get("reason"):
            st.caption(u["reason"])
    else:
        reason = st.text_input(tr("a.ad.reason"), key="ad_reason", disabled=is_me)
        if c1.button(tr("a.ad.block"), key="ad_block", icon=":material/block:", disabled=is_me, use_container_width=True):
            A.set_blocked(ctx.store, uid, True, reason, by=me.get("login", ""))
            st.rerun()
    if c2.button(tr("a.ad.kick"), key="ad_kick", icon=":material/devices:", use_container_width=True):
        A.destroy_all_sessions(ctx.store, uid)
        st.toast(tr("a.ad.done"))
    live = bool(u.get("live"))
    if st.button(tr("a.ad.live_off" if live else "a.ad.live_on"), key="ad_live", icon=":material/bolt:"):
        A.set_live(ctx.store, uid, not live)
        st.rerun()
    if u.get("provider") == "local" and c3.button(tr("a.ad.reset"), key="ad_reset", icon=":material/key:", use_container_width=True):
        pw = A.admin_reset_password(ctx.store, uid, by=me.get("login", ""))
        ss["_temp_pw"] = (uid, pw)
        st.rerun()
    with st.expander(tr("a.ad.delete")):
        sure = st.checkbox(tr("a.ad.del_confirm"), key="ad_del_ok")
        if st.button(tr("a.ad.delete"), key="ad_del", disabled=(is_me or not sure), icon=":material/delete_forever:"):
            A.delete_account(ctx.store, uid)
            st.rerun()
