from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", DATA_DIR / "database.db"))
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
BANGKOK_TZ = timezone(timedelta(hours=7), name="Asia/Bangkok")

def load_secret_key():
    env_secret = os.environ.get("SECRET_KEY")
    if env_secret:
        return env_secret

    secret_file = DATA_DIR / ".secret_key"
    if secret_file.exists():
        return secret_file.read_text(encoding="utf-8").strip()

    generated = secrets.token_hex(32)
    secret_file.write_text(generated, encoding="utf-8")
    return generated


app = Flask(__name__)
app.secret_key = load_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
@app.before_request
def prepare_request():
    if request.headers.get("X-Forwarded-Proto", request.scheme) == "https":
        app.config["SESSION_COOKIE_SECURE"] = True

    if "owner_id" not in session:
        session["owner_id"] = secrets.token_urlsafe(24)

    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)


@app.context_processor
def inject_globals():
    return {
        "csrf_token": session.get("csrf_token", ""),
        "today_thai": thai_date(),
    }

def now_bangkok():
    return datetime.now(BANGKOK_TZ)


def today_iso():
    return now_bangkok().date().isoformat()


def thai_date(value=None):
    months = [
        "", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
        "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
    ]
    value = value or now_bangkok()
    if isinstance(value, str):
        try:
            value = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return value
    return f"{value.day} {months[value.month]} {value.year + 543}"


def parse_legacy_thai_date(value):
    if not value:
        return None
    months = {
        "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4,
        "พฤษภาคม": 5, "มิถุนายน": 6, "กรกฎาคม": 7, "สิงหาคม": 8,
        "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
    }
    try:
        day_text, month_text, year_text = value.strip().split()
        return date(int(year_text) - 543, months[month_text], int(day_text)).isoformat()
    except (ValueError, KeyError, AttributeError):
        return None

buildings = {
    "อาคาร 1": ["111", "112", "113", "114", "115", "116", "117", "121", "122", "123", "124", "125", "126", "127"],
    "อาคาร 3": ["ห้องแลป", "311", "312", "313", "314", "315", "321", "322", "323", "324", "325", "331", "332", "333", "334", "335"],
    "อาคาร 4": ["411", "421", "422", "423", "424", "425", "426", "427", "428", "431", "432", "433", "434", "435", "436", "437", "438"],
    "อาคาร 5": ["ห้องกระจกขุนศรี1", "511", "512", "513", "514", "515", "516", "517", "518", "521", "522", "523", "524", "525", "526", "527", "528", "531", "532", "533", "534", "535", "536", "537", "538"],
    "อาคาร 6": ["ห้องto be number one", "621", "622", "623", "624", "625", "626", "627", "628", "631", "632", "633", "634", "635", "636", "637", "638", "641", "642", "643", "644", "645", "646", "647", "648"],
    "ฝึกงาน1": ["ฝ111", "ฝ112", "ฝ121", "ฝ122"],
    "ฝึกงาน2": ["ฝ211", "ฝ212", "ฝ221", "ฝ222"],
    "โดม": ["โดม1"],
    "หอประชุมขุนศรี": ["หอประชุมขุนศรี"],
    "เรือนแก้ว": ["เรือนแก้ว"],
}


def room_exists(building, room):
    return building in buildings and room in buildings[building]

def connect_db():
    conn = sqlite3.connect(str(DATABASE_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def table_columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def create_table():
    conn = connect_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS booking(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            building TEXT NOT NULL,
            room TEXT NOT NULL,
            name TEXT NOT NULL,
            date TEXT,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            booking_date TEXT,
            owner_id TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT,
            cancelled_at TEXT
        )
    """)

    columns = table_columns(conn, "booking")
    migrations = {
        "booking_date": "ALTER TABLE booking ADD COLUMN booking_date TEXT",
        "owner_id": "ALTER TABLE booking ADD COLUMN owner_id TEXT",
        "status": "ALTER TABLE booking ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
        "created_at": "ALTER TABLE booking ADD COLUMN created_at TEXT",
        "cancelled_at": "ALTER TABLE booking ADD COLUMN cancelled_at TEXT",
    }
    for column, sql in migrations.items():
        if column not in columns:
            conn.execute(sql)

    legacy_rows = conn.execute(
        "SELECT id, date FROM booking WHERE booking_date IS NULL OR booking_date=''"
    ).fetchall()
    for row in legacy_rows:
        parsed = parse_legacy_thai_date(row["date"])
        conn.execute(
            "UPDATE booking SET booking_date=?, owner_id=COALESCE(owner_id, ?), created_at=COALESCE(created_at, ?) WHERE id=?",
            (parsed, f"legacy-{row['id']}", now_bangkok().isoformat(timespec="seconds"), row["id"]),
        )

    conn.execute("UPDATE booking SET status='active' WHERE status IS NULL OR status='' ")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_booking_day ON booking(booking_date, building, room, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_booking_owner ON booking(owner_id, booking_date)")

    try:
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_room_day_active
            ON booking(building, room, booking_date)
            WHERE status='active' AND booking_date IS NOT NULL
        """)
    except sqlite3.IntegrityError:
        duplicates = conn.execute("""
            SELECT building, room, booking_date
            FROM booking
            WHERE status='active' AND booking_date IS NOT NULL
            GROUP BY building, room, booking_date
            HAVING COUNT(*) > 1
        """).fetchall()
        for dup in duplicates:
            rows = conn.execute("""
                SELECT id FROM booking
                WHERE building=? AND room=? AND booking_date=? AND status='active'
                ORDER BY id ASC
            """, (dup["building"], dup["room"], dup["booking_date"])).fetchall()
            for extra in rows[1:]:
                conn.execute(
                    "UPDATE booking SET status='cancelled', cancelled_at=? WHERE id=?",
                    (now_bangkok().isoformat(timespec="seconds"), extra["id"]),
                )
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_room_day_active
            ON booking(building, room, booking_date)
            WHERE status='active' AND booking_date IS NOT NULL
        """)

    conn.commit()
    conn.close()


create_table()


def verify_csrf():
    token = request.form.get("csrf_token", "")
    if not token or not secrets.compare_digest(token, session.get("csrf_token", "")):
        abort(400, description="คำขอไม่ถูกต้อง กรุณาลองใหม่")


def booking_to_dict(row):
    item = dict(row)
    item["thai_booking_date"] = thai_date(item.get("booking_date")) if item.get("booking_date") else item.get("date", "-")
    item["is_today"] = item.get("booking_date") == today_iso()
    item["can_cancel"] = (
        item.get("owner_id") == session.get("owner_id")
        and item.get("status") == "active"
        and item.get("booking_date") == today_iso()
    )
    return item

@app.route("/")
def home():
    total_rooms = sum(len(items) for items in buildings.values())
    conn = connect_db()
    booked_today = conn.execute(
        "SELECT COUNT(*) AS total FROM booking WHERE booking_date=? AND status='active'",
        (today_iso(),),
    ).fetchone()["total"]
    conn.close()

    return render_template(
        "index.html",
        buildings=buildings,
        total_rooms=total_rooms,
        booked_today=booked_today,
        available_today=max(total_rooms - booked_today, 0),
    )
@app.route("/building/<building>")
def rooms(building):
    if building not in buildings:
        abort(404)

    conn = connect_db()
    bookings_today = conn.execute(
        """
        SELECT * FROM booking
        WHERE building=? AND booking_date=? AND status='active'
        """,
        (building, today_iso()),
    ).fetchall()
    conn.close()

    booking_map = {row["room"]: row for row in bookings_today}
    room_list = []
    for room in buildings[building]:
        book = booking_map.get(room)
        room_list.append({
            "room": room,
            "status": "ไม่ว่าง" if book else "ว่าง",
            "name": book["name"] if book else "-",
            "start_time": book["start_time"] if book else "",
            "end_time": book["end_time"] if book else "",
        })

    return render_template(
        "rooms.html",
        building=building,
        rooms=room_list,
        today=thai_date(),
        available_count=sum(1 for room in room_list if room["status"] == "ว่าง"),
    )

@app.route("/booking/<building>/<room>", methods=["GET", "POST"])
def booking(building, room):
    if not room_exists(building, room):
        abort(404)

    if request.method == "POST":
        verify_csrf()
        name = request.form.get("name", "").strip()
        start = request.form.get("start", "").strip()
        end = request.form.get("end", "").strip()

        if len(name) < 2 or len(name) > 100:
            flash("กรุณากรอกชื่อผู้จอง 2-100 ตัวอักษร", "error")
            return render_template("booking.html", building=building, room=room, today=thai_date())

        try:
            start_obj = datetime.strptime(start, "%H:%M").time()
            end_obj = datetime.strptime(end, "%H:%M").time()
        except ValueError:
            flash("รูปแบบเวลาไม่ถูกต้อง", "error")
            return render_template("booking.html", building=building, room=room, today=thai_date())

        if start_obj >= end_obj:
            flash("เวลาสิ้นสุดต้องมากกว่าเวลาเริ่ม", "error")
            return render_template("booking.html", building=building, room=room, today=thai_date())

        booking_day = today_iso()
        created_at = now_bangkok().isoformat(timespec="seconds")
        conn = connect_db()
        try:
            conn.execute(
                """
                INSERT INTO booking
                (building, room, name, date, start_time, end_time, booking_date, owner_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    building,
                    room,
                    name,
                    thai_date(),
                    start,
                    end,
                    booking_day,
                    session["owner_id"],
                    created_at,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            flash("ห้องนี้มีผู้จองสำหรับวันนี้แล้ว กรุณาเลือกห้องอื่น", "error")
            return redirect(url_for("rooms", building=building))
        finally:
            conn.close()

        flash(f"จองห้อง {room} สำเร็จ", "success")
        return redirect(url_for("bookings"))
    conn = connect_db()
    exists = conn.execute(
        """
        SELECT 1 FROM booking
        WHERE building=? AND room=? AND booking_date=? AND status='active'
        LIMIT 1
        """,
        (building, room, today_iso()),
    ).fetchone()
    conn.close()
    if exists:
        flash("ห้องนี้มีผู้จองแล้วในวันนี้", "error")
        return redirect(url_for("rooms", building=building))

    return render_template("booking.html", building=building, room=room, today=thai_date())

@app.route("/bookings")
def bookings():
    conn = connect_db()
    rows = conn.execute("""
        SELECT * FROM booking
        ORDER BY
            CASE WHEN booking_date=? AND status='active' THEN 0 ELSE 1 END,
            booking_date DESC,
            start_time ASC,
            id DESC
    """, (today_iso(),)).fetchall()
    conn.close()

    data = [booking_to_dict(row) for row in rows]
    active_today = [item for item in data if item["is_today"] and item["status"] == "active"]
    history = [item for item in data if not (item["is_today"] and item["status"] == "active")]

    return render_template(
        "bookings.html",
        active_today=active_today,
        history=history,
        my_active_count=sum(1 for item in active_today if item["can_cancel"]),
    )

@app.route("/booking/<int:booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    verify_csrf()
    conn = connect_db()
    row = conn.execute("SELECT * FROM booking WHERE id=?", (booking_id,)).fetchone()

    if row is None:
        conn.close()
        abort(404)

    if row["owner_id"] != session.get("owner_id"):
        conn.close()
        abort(403, description="คุณไม่มีสิทธิ์ยกเลิกการจองรายการนี้")

    if row["status"] != "active":
        conn.close()
        flash("รายการนี้ถูกยกเลิกไปแล้ว", "error")
        return redirect(url_for("bookings"))

    if row["booking_date"] != today_iso():
        conn.close()
        flash("ไม่สามารถยกเลิกรายการย้อนหลังได้", "error")
        return redirect(url_for("bookings"))

    conn.execute(
        "UPDATE booking SET status='cancelled', cancelled_at=? WHERE id=? AND owner_id=?",
        (now_bangkok().isoformat(timespec="seconds"), booking_id, session["owner_id"]),
    )
    conn.commit()
    conn.close()

    flash("ยกเลิกการจองเรียบร้อยแล้ว และยังเก็บรายการไว้ในประวัติ", "success")
    return redirect(url_for("bookings"))


@app.errorhandler(403)
def forbidden(error):
    return render_template("error.html", code=403, title="ไม่มีสิทธิ์ดำเนินการ", message=str(error.description)), 403


@app.errorhandler(404)
def not_found(error):
    return render_template("error.html", code=404, title="ไม่พบหน้าที่ต้องการ", message="ตรวจสอบลิงก์แล้วลองใหม่อีกครั้ง"), 404


@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", code=400, title="คำขอไม่ถูกต้อง", message=str(error.description)), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
