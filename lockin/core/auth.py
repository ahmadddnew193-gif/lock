import hashlib
import hmac
import os
import re
import secrets as pysecrets
import datetime as dt
import streamlit as st
from core import config, db

ITER = 200_000
RESERVED = {"admin", "root", "administrator", "system", "lockin", "support"}


def hash_pw(pw):
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITER)
    return f"pbkdf2${ITER}${salt.hex()}${h.hex()}"


def verify_pw(pw, stored):
    try:
        _, it, salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


DUMMY = hash_pw("dummy-password")


def master_key():
    return config.secret("MASTER_KEY")


def current():
    return st.session_state.get("user")


def logged_in():
    return current() is not None


def is_admin():
    u = current()
    return bool(u) and u.get("role") == "admin" and st.session_state.get("admin_verified") is True


def logout():
    st.session_state.clear()


def valid_username(u):
    return bool(re.fullmatch(r"[a-z0-9._-]{3,30}", u)) and u not in RESERVED


def validate_pw(a, b):
    if len(a) < 8:
        return False, "Use at least 8 characters."
    if a != b:
        return False, "The two passwords don't match."
    return True, ""


def recent_failures(username):
    since = (dt.datetime.now() - dt.timedelta(minutes=10)).isoformat(timespec="seconds")
    r = db.rows("SELECT COUNT(*) n FROM login_log WHERE username=? AND ok=0 AND created>=?", (username, since))
    return int(r[0]["n"])


def _log_attempt(username, role, ok):
    db.run("INSERT INTO login_log(created,username,role,ok) VALUES(?,?,?,?)", (db.now(), username, role, 1 if ok else 0))


def _set_user(row):
    st.session_state["user"] = {
        "id": row["id"], "username": row["username"],
        "display_name": row.get("display_name") or row["username"],
        "role": row["role"], "must_change": int(row.get("must_change") or 0),
    }


def login_student(username, password):
    u = (username or "").strip().lower()
    if not u or not password:
        return False, "Enter your username and password."
    if recent_failures(u) >= 5:
        return False, "Too many failed attempts. Try again in 10 minutes."
    r = db.rows("SELECT * FROM users WHERE username=? AND role='user'", (u,))
    row = r[0] if r else None
    stored = row["pw_hash"] if row and row["pw_hash"] else DUMMY
    pw_ok = verify_pw(password, stored)
    ok = bool(row) and pw_ok and int(row["active"]) == 1 and bool(row["pw_hash"])
    _log_attempt(u, "user", ok)
    if not ok:
        return False, "Wrong username or password, or the account is disabled."
    db.run("UPDATE users SET last_login=? WHERE id=?", (db.now(), row["id"]))
    _set_user(row)
    db.log_event("login", "", row["id"])
    return True, ""


def ensure_admin_row():
    r = db.rows("SELECT * FROM users WHERE role='admin' ORDER BY id LIMIT 1")
    if r:
        return r[0]
    db.run("INSERT INTO users(username,display_name,pw_hash,role,active,must_change,created,note) VALUES(?,?,?,?,?,?,?,?)",
           ("admin", "Admin", "", "admin", 1, 0, db.now(), "owner account"))
    return db.rows("SELECT * FROM users WHERE role='admin' ORDER BY id LIMIT 1")[0]


def login_admin(key):
    mk = master_key()
    if not mk:
        return False, "MASTER_KEY is not set in the Streamlit secrets."
    if recent_failures("admin") >= 5:
        return False, "Too many failed attempts. Try again in 10 minutes."
    ok = hmac.compare_digest((key or "").encode(), mk.encode())
    _log_attempt("admin", "admin", ok)
    if not ok:
        return False, "Wrong master key."
    row = ensure_admin_row()
    db.run("UPDATE users SET last_login=? WHERE id=?", (db.now(), row["id"]))
    _set_user(row)
    st.session_state["admin_verified"] = True
    db.log_event("login", "admin", row["id"])
    return True, ""


def change_password(user_id, new_pw):
    db.run("UPDATE users SET pw_hash=?, must_change=0 WHERE id=?", (hash_pw(new_pw), user_id))


def temp_password():
    return pysecrets.token_urlsafe(9)[:10]


def create_user(username, display_name, note="", password=None):
    u = (username or "").strip().lower()
    if not valid_username(u):
        return False, "Username must be 3-30 characters: letters, numbers, dot, dash, underscore (and not a reserved word)."
    if db.rows("SELECT 1 FROM users WHERE username=?", (u,)):
        return False, "That username is already taken."
    pw = password or temp_password()
    if len(pw) < 6:
        return False, "Password must be at least 6 characters."
    db.run("INSERT INTO users(username,display_name,pw_hash,role,active,must_change,created,note) VALUES(?,?,?,?,?,?,?,?)",
           (u, display_name.strip() or u, hash_pw(pw), "user", 1, 1, db.now(), note))
    return True, pw


def reset_password(user_id):
    pw = temp_password()
    db.run("UPDATE users SET pw_hash=?, must_change=1 WHERE id=? AND role='user'", (hash_pw(pw), user_id))
    return pw


def set_active(user_id, active):
    db.run("UPDATE users SET active=? WHERE id=? AND role='user'", (1 if active else 0, user_id))


def delete_user(user_id):
    r = db.rows("SELECT role FROM users WHERE id=?", (user_id,))
    if not r or r[0]["role"] != "user":
        return False
    for t in db.DATA_TABLES:
        db.run(f"DELETE FROM {t} WHERE user_id=?", (user_id,))
    db.run("DELETE FROM users WHERE id=?", (user_id,))
    return True


def add_request(name, contact, message):
    db.run("INSERT INTO requests(created,name,contact,message) VALUES(?,?,?,?)",
           (db.now(), name.strip()[:80], contact.strip()[:120], message.strip()[:500]))


def force_change_screen():
    st.title("🔑 Choose your own password")
    st.info("Your account was created with a temporary password. Pick a new one to continue.")
    with st.form("force_pw"):
        a = st.text_input("New password", type="password")
        b = st.text_input("Repeat new password", type="password")
        if st.form_submit_button("Save and continue", type="primary"):
            ok, msg = validate_pw(a, b)
            if ok:
                change_password(current()["id"], a)
                st.session_state["user"]["must_change"] = 0
                st.rerun()
            else:
                st.error(msg)
    if st.button("Log out"):
        logout()
        st.rerun()


def login_screen():
    _, mid, _ = st.columns([1, 1.5, 1])
    with mid:
        st.markdown("# 🔒 LockIn")
        st.caption("Your AI study system: notes, mistakes, flashcards, past papers, and a coach that keeps you honest.")
        t1, t2, t3 = st.tabs(["Student login", "Admin login", "Request access"])
        with t1:
            with st.form("student_login"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                if st.form_submit_button("Log in", type="primary"):
                    ok, msg = login_student(u, p)
                    if ok:
                        st.rerun()
                    st.error(msg)
        with t2:
            if not master_key():
                st.warning("Admin login is disabled until MASTER_KEY is set in the Streamlit secrets.")
            with st.form("admin_login"):
                k = st.text_input("Master key", type="password")
                if st.form_submit_button("Log in as admin", type="primary"):
                    ok, msg = login_admin(k)
                    if ok:
                        st.rerun()
                    st.error(msg)
        with t3:
            st.caption("Accounts are created by the admin. Tell them who you are and how to reach you.")
            with st.form("request_access", clear_on_submit=True):
                n = st.text_input("Your name")
                c = st.text_input("Email or other contact")
                m = st.text_area("Anything the admin should know? (optional)", height=80)
                if st.form_submit_button("Send request"):
                    if n.strip() and c.strip():
                        add_request(n, c, m)
                        st.success("Request sent. The admin will contact you with your login.")
                    else:
                        st.error("Name and contact are required.")
