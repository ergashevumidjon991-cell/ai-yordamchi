import json
import sqlite3
from datetime import datetime, timedelta

from . import config

KINDS = ("syomka", "montaj", "post", "boshqa")

_conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.executescript(
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        start_at TEXT NOT NULL,          -- mahalliy vaqt, 'YYYY-MM-DD HH:MM'
        location TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        status TEXT DEFAULT 'active',    -- active | departed | done | cancelled
        sent TEXT DEFAULT '[]',          -- yuborilgan eslatmalar (daqiqalar ro'yxati)
        last_nag TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS alarms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT NOT NULL,              -- 'HH:MM'
        days TEXT DEFAULT '0123456',     -- hafta kunlari, 0 = dushanba
        date TEXT DEFAULT '',            -- bir martalik bo'lsa 'YYYY-MM-DD'
        label TEXT DEFAULT '',
        enabled INTEGER DEFAULT 1,
        last_fired TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS contacts (
        tg_id INTEGER PRIMARY KEY,       -- yordamchi akkaunt yozishgan odamning Telegram id si
        name TEXT DEFAULT '',
        contact TEXT DEFAULT '',         -- @username yoki +998... raqam
        event_id INTEGER                 -- mijoz bo'lsa, qaysi s'yomka uchun eslatma olgan
    );
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL,
        text TEXT NOT NULL
    );
    """
)
# Eski bazaga yangi ustunlar qo'shamiz (mijozga eslatma uchun)
_cols = {r["name"] for r in _conn.execute("PRAGMA table_info(events)")}
for _col, _type in (("client_name", "TEXT DEFAULT ''"), ("client_contact", "TEXT DEFAULT ''"),
                    ("client_sent", "TEXT DEFAULT '[]'"), ("client_pending", "TEXT DEFAULT ''")):
    if _col not in _cols:
        _conn.execute(f"ALTER TABLE events ADD COLUMN {_col} {_type}")
_conn.commit()


def now() -> datetime:
    return datetime.now(config.TZ).replace(tzinfo=None, second=0, microsecond=0)


def parse_dt(value: str) -> datetime:
    return datetime.strptime(value.strip()[:16], "%Y-%m-%d %H:%M")


def _row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r else None


# --- Rejalar ---

def add_event(kind: str, title: str, start_at: str, location: str = "", notes: str = "",
              client_name: str = "", client_contact: str = "") -> dict:
    if kind not in KINDS:
        kind = "boshqa"
    start = parse_dt(start_at).strftime("%Y-%m-%d %H:%M")
    cur = _conn.execute(
        "INSERT INTO events (kind, title, start_at, location, notes, client_name, client_contact) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (kind, title, start, location, notes, client_name, client_contact.strip()),
    )
    _conn.commit()
    return get_event(cur.lastrowid)


def get_event(event_id: int) -> dict | None:
    return _row(_conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())


def list_events(date_from: str, date_to: str, include_finished: bool = False) -> list[dict]:
    sql = "SELECT * FROM events WHERE start_at >= ? AND start_at <= ?"
    if not include_finished:
        sql += " AND status IN ('active', 'departed')"
    rows = _conn.execute(sql + " ORDER BY start_at", (date_from[:10] + " 00:00", date_to[:10] + " 23:59"))
    return [dict(r) for r in rows]


def active_events() -> list[dict]:
    rows = _conn.execute("SELECT * FROM events WHERE status = 'active' ORDER BY start_at")
    return [dict(r) for r in rows]


def update_event(event_id: int, **fields) -> dict | None:
    allowed = {"kind", "title", "start_at", "location", "notes", "status", "client_name", "client_contact",
               "client_sent", "client_pending"}
    fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "start_at" in fields:
        fields["start_at"] = parse_dt(fields["start_at"]).strftime("%Y-%m-%d %H:%M")
        fields["sent"] = "[]"  # vaqt o'zgarsa eslatmalar qaytadan yuboriladi
        fields["client_sent"] = "[]"
        fields["client_pending"] = ""
        fields["status"] = fields.get("status", "active")
    if fields:
        cols = ", ".join(f"{k} = ?" for k in fields)
        _conn.execute(f"UPDATE events SET {cols} WHERE id = ?", (*fields.values(), event_id))
        _conn.commit()
    return get_event(event_id)


def client_pending_events() -> list[dict]:
    rows = _conn.execute("SELECT * FROM events WHERE client_pending != '' AND status = 'active' ORDER BY start_at")
    return [dict(r) for r in rows]


def delete_event(event_id: int) -> bool:
    cur = _conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
    _conn.commit()
    return cur.rowcount > 0


def mark_sent(event_id: int, sent: list[int]) -> None:
    _conn.execute("UPDATE events SET sent = ? WHERE id = ?", (json.dumps(sent), event_id))
    _conn.commit()


def set_last_nag(event_id: int, when: datetime) -> None:
    _conn.execute("UPDATE events SET last_nag = ? WHERE id = ?", (when.strftime("%Y-%m-%d %H:%M"), event_id))
    _conn.commit()


# --- Budilniklar ---

def add_alarm(time: str, days: str = "", date: str = "", label: str = "") -> dict:
    """days berilsa — takrorlanadi, aks holda bir martalik (date yoki eng yaqin shu vaqt)."""
    hh, mm = time.strip().split(":")[:2]
    time = f"{int(hh):02d}:{int(mm):02d}"
    days = "".join(d for d in (days or "") if d in "0123456")
    date = (date or "")[:10]
    if not days and not date:
        n = now()
        day = n.date() if time > n.strftime("%H:%M") else n.date() + timedelta(days=1)
        date = day.isoformat()
    cur = _conn.execute(
        "INSERT INTO alarms (time, days, date, label) VALUES (?, ?, ?, ?)",
        (time, days if not date else "", date, label),
    )
    _conn.commit()
    return _row(_conn.execute("SELECT * FROM alarms WHERE id = ?", (cur.lastrowid,)).fetchone())


def list_alarms() -> list[dict]:
    return [dict(r) for r in _conn.execute("SELECT * FROM alarms WHERE enabled = 1 ORDER BY time")]


def delete_alarm(alarm_id: int) -> bool:
    cur = _conn.execute("DELETE FROM alarms WHERE id = ?", (alarm_id,))
    _conn.commit()
    return cur.rowcount > 0


def alarm_fired(alarm: dict, when: datetime) -> None:
    stamp = when.strftime("%Y-%m-%d %H:%M")
    if alarm["date"]:
        _conn.execute("UPDATE alarms SET last_fired = ?, enabled = 0 WHERE id = ?", (stamp, alarm["id"]))
    else:
        _conn.execute("UPDATE alarms SET last_fired = ? WHERE id = ?", (stamp, alarm["id"]))
    _conn.commit()


# --- Suhbat tarixi ---

def add_history(role: str, text: str) -> None:
    _conn.execute("INSERT INTO history (role, text) VALUES (?, ?)", (role, text))
    _conn.execute(
        "DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT ?)",
        (config.HISTORY_TURNS * 2,),
    )
    _conn.commit()


def get_history() -> list[dict]:
    rows = _conn.execute("SELECT role, text FROM history ORDER BY id").fetchall()
    msgs = [{"role": r["role"], "content": r["text"]} for r in rows]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


def clear_history() -> None:
    _conn.execute("DELETE FROM history")
    _conn.commit()


def save_contact(tg_id: int, name: str = "", contact: str = "", event_id: int | None = None) -> None:
    """Yordamchi yozishgan odamni eslab qoladi; event_id faqat yangi qiymat bo'lsa almashtiriladi."""
    _conn.execute(
        "INSERT INTO contacts (tg_id, name, contact, event_id) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(tg_id) DO UPDATE SET name = COALESCE(NULLIF(excluded.name, ''), name), "
        "contact = COALESCE(NULLIF(excluded.contact, ''), contact), "
        "event_id = COALESCE(excluded.event_id, event_id)",
        (tg_id, name, contact, event_id),
    )
    _conn.commit()


def get_contact(tg_id: int) -> dict | None:
    return _row(_conn.execute("SELECT * FROM contacts WHERE tg_id = ?", (tg_id,)).fetchone())


def find_contact(name: str) -> dict | None:
    """Ism yoki @username bo'yicha (egasi «Aliga yoz» desa)."""
    q = f"%{name.strip().lstrip('@')}%"
    return _row(_conn.execute(
        "SELECT * FROM contacts WHERE name LIKE ? OR contact LIKE ? ORDER BY event_id IS NULL, rowid DESC LIMIT 1",
        (q, q)).fetchone())


def client_events(contact: dict) -> list[dict]:
    """Shu mijozning hali o'tmagan s'yomkalari."""
    rows = _conn.execute(
        "SELECT * FROM events WHERE status = 'active' AND kind = 'syomka' AND (id = ? OR "
        "(client_contact != '' AND client_contact = ?)) ORDER BY start_at",
        (contact.get("event_id") or -1, contact.get("contact") or "\0"))
    return [dict(r) for r in rows]
