from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from werkzeug.security import check_password_hash, generate_password_hash

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", DATA_DIR / "database.db"))
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
# ประเทศไทยใช้ UTC+7 ตลอดปีและไม่มี Daylight Saving Time
# ใช้ fixed offset เพื่อให้รันบน Windows/Python ที่ไม่มี tzdata ได้ทันที
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

# เปิด Secure cookie อัตโนมัติเมื่อ deploy ผ่าน HTTPS
@app.before_request
def prepare_request():
    if request.headers.get("X-Forwarded-Proto", request.scheme) == "https":
        app.config["SESSION_COOKIE_SECURE"] = True

    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)


@app.context_processor
def inject_globals():
    return {
        "csrf_token": session.get("csrf_token", ""),
        "today_thai": thai_date(),
        "current_username": session.get("username"),
        "current_display_name": session.get("display_name"),
    }


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            flash("กรุณาเข้าสู่ระบบก่อนใช้งานระบบจองห้อง", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped_view


# --------------------------
# วันที่ / เวลา
# --------------------------
def now_bangkok():
    return datetime.now(BANGKOK_TZ)


def today_iso():
    return now_bangkok().date().isoformat()


def parse_time_text(value):
    """รองรับทั้ง 08:30, 8:30 และ 08:30:00 จากฐานข้อมูลเก่า"""
    value = (value or "").strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            pass
    return None


def booking_end_datetime(booking_date, end_time):
    try:
        day = datetime.strptime((booking_date or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None
    end_obj = parse_time_text(end_time)
    if end_obj is None:
        return None
    return datetime.combine(day, end_obj, tzinfo=BANGKOK_TZ)


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


# --------------------------
# รายชื่ออาคารและห้องเรียน
# --------------------------
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


# --------------------------
# ตารางสอน (จาก ตารางสอน ม.4/10 ภาคเรียนที่ 1 ปีการศึกษา 2569)
# ใช้กันไม่ให้จองห้องทับคาบเรียนจริง โดยจับคู่วันในสัปดาห์ + ช่วงเวลา + ห้อง
# วันจันทร์=0 ... ศุกร์=4 ตาม datetime.weekday()
# --------------------------
CLASS_SCHEDULE = {
    0: [  # จันทร์
        {"start": "08:30", "end": "09:20", "building": "อาคาร 5", "room": "523", "subject": "ว31181", "teacher": "ครูดารัส"},
        {"start": "09:20", "end": "10:10", "building": "อาคาร 5", "room": "523", "subject": "ว31281", "teacher": "ครูดารัส"},
        {"start": "12:40", "end": "13:30", "building": "ฝึกงาน2", "room": "ฝ221", "subject": "ง30101", "teacher": "ครูวุฒิมณเฑน์"},
        {"start": "13:30", "end": "14:20", "building": "อาคาร 3", "room": "332", "subject": "ว31221", "teacher": "ครูลลิตา"},
        {"start": "14:20", "end": "15:10", "building": "อาคาร 3", "room": "313", "subject": "ว30111", "teacher": "ครูสมนึก"},
    ],
    1: [  # อังคาร
        {"start": "08:30", "end": "09:20", "building": "อาคาร 1", "room": "122", "subject": "ก31901 แนะแนว", "teacher": "ครูวาทินี"},
        {"start": "09:20", "end": "10:10", "building": "อาคาร 6", "room": "623", "subject": "จ30201", "teacher": "ครูดุสิตา"},
        {"start": "10:10", "end": "11:00", "building": "อาคาร 6", "room": "632", "subject": "ส31101", "teacher": "ครูยุพเยาว์"},
        {"start": "11:00", "end": "11:50", "building": "อาคาร 5", "room": "538", "subject": "ค31103", "teacher": "ครูพิจิตรา"},
        {"start": "12:40", "end": "13:30", "building": "อาคาร 3", "room": "313", "subject": "ว30111", "teacher": "ครูสมนึก"},
        {"start": "13:30", "end": "14:20", "building": "ฝึกงาน1", "room": "ฝ122", "subject": "ศ31102", "teacher": "ครูสิชิน"},
        {"start": "14:20", "end": "15:10", "building": "อาคาร 6", "room": "641", "subject": "ส31102", "teacher": "ครูวณัฐพล"},
    ],
    2: [  # พุธ
        {"start": "08:30", "end": "09:20", "building": "อาคาร 6", "room": "622", "subject": "อ31101", "teacher": "ครูพิรดา"},
        {"start": "09:20", "end": "10:10", "building": "อาคาร 3", "room": "322", "subject": "ว31241", "teacher": "ครูดารัสศิริ"},
        {"start": "11:00", "end": "11:50", "building": "อาคาร 4", "room": "411", "subject": "Sci30221", "teacher": "ครูDivine, ครูลลิตา"},
        {"start": "12:40", "end": "13:30", "building": "อาคาร 6", "room": "635", "subject": "ท31101", "teacher": "ครูลักขณา"},
        {"start": "13:30", "end": "14:20", "building": "อาคาร 3", "room": "332", "subject": "ว30121", "teacher": "ครูลลิตา"},
        {"start": "14:20", "end": "15:10", "building": "อาคาร 3", "room": "313", "subject": "ว31201", "teacher": "ครูสมนึก"},
    ],
    3: [  # พฤหัสบดี
        {"start": "08:30", "end": "09:20", "building": "อาคาร 3", "room": "313", "subject": "ว31201", "teacher": "ครูสมนึก"},
        {"start": "09:20", "end": "10:10", "building": "อาคาร 6", "room": "627", "subject": "พ31101", "teacher": "ครูจิราภรณ์"},
        {"start": "10:10", "end": "11:00", "building": "อาคาร 5", "room": "536", "subject": "ค31103", "teacher": "ครูพิจิตรา"},
        {"start": "11:00", "end": "11:50", "building": "อาคาร 3", "room": "332", "subject": "ว31221", "teacher": "ครูลลิตา"},
        {"start": "12:40", "end": "13:30", "building": "อาคาร 3", "room": "322", "subject": "ว31241", "teacher": "ครูดารัสศิริ"},
        {"start": "13:30", "end": "15:10", "building": "อาคาร 3", "room": "315", "subject": "ว31291", "teacher": "ครูภัทร, ครูพนิดา"},
    ],
    4: [  # ศุกร์
        {"start": "08:30", "end": "09:20", "building": "อาคาร 6", "room": "632", "subject": "ส31101", "teacher": "ครูยุพเยาว์"},
        {"start": "09:20", "end": "10:10", "building": "อาคาร 1", "room": "126", "subject": "อ30201", "teacher": "ครูDee, ครูจตุรงค์"},
        {"start": "10:10", "end": "11:00", "building": "อาคาร 6", "room": "622", "subject": "อ31101", "teacher": "ครูพิรดา"},
        {"start": "11:00", "end": "11:50", "building": "อาคาร 3", "room": "332", "subject": "ว30121", "teacher": "ครูลลิตา"},
        {"start": "12:40", "end": "13:30", "building": "อาคาร 4", "room": "411", "subject": "Sci30221", "teacher": "ครูDivine, ครูลลิตา"},
        {"start": "13:30", "end": "14:20", "building": "อาคาร 6", "room": "635", "subject": "ท31101", "teacher": "ครูลักขณา"},
    ],
}


def class_schedule_conflict(building, room, weekday, start_obj, end_obj):
    """คืนคาบเรียนที่เวลาที่ขอจองไปทับ ถ้ามี ไม่งั้นคืน None"""
    for entry in CLASS_SCHEDULE.get(weekday, []):
        if entry["building"] != building or entry["room"] != room:
            continue
        entry_start = parse_time_text(entry["start"])
        entry_end = parse_time_text(entry["end"])
        if entry_start < end_obj and start_obj < entry_end:
            return entry
    return None


def current_class_entry(building, room, weekday, time_obj):
    """คืนคาบเรียนที่กำลังสอนอยู่ ณ เวลานี้ในห้องนี้ ถ้ามี ไม่งั้นคืน None"""
    for entry in CLASS_SCHEDULE.get(weekday, []):
        if entry["building"] != building or entry["room"] != room:
            continue
        entry_start = parse_time_text(entry["start"])
        entry_end = parse_time_text(entry["end"])
        if entry_start <= time_obj < entry_end:
            return entry
    return None


# --------------------------
# Database
# --------------------------
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
        CREATE TABLE IF NOT EXISTS user(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            created_at TEXT
        )
    """)
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
            cancelled_at TEXT,
            completed_at TEXT
        )
    """)

    # Migration สำหรับ database เดิมที่เป็น Demo
    columns = table_columns(conn, "booking")
    migrations = {
        "booking_date": "ALTER TABLE booking ADD COLUMN booking_date TEXT",
        "owner_id": "ALTER TABLE booking ADD COLUMN owner_id TEXT",
        "status": "ALTER TABLE booking ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
        "created_at": "ALTER TABLE booking ADD COLUMN created_at TEXT",
        "cancelled_at": "ALTER TABLE booking ADD COLUMN cancelled_at TEXT",
        "completed_at": "ALTER TABLE booking ADD COLUMN completed_at TEXT",
    }
    for column, sql in migrations.items():
        if column not in columns:
            conn.execute(sql)

    # ย้ายวันที่แบบภาษาไทยเดิม -> YYYY-MM-DD เพื่อให้กรองตามวันได้จริง
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

    # ห้องหนึ่งมีรายการ active ได้เพียง 1 รายการต่อวัน ป้องกันกดจองชนกันพร้อมกัน
    try:
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_room_day_active
            ON booking(building, room, booking_date)
            WHERE status='active' AND booking_date IS NOT NULL
        """)
    except sqlite3.IntegrityError:
        # รองรับ DB เก่าที่มีข้อมูลซ้ำ: เก็บรายการแรกเป็น active ที่เหลือย้ายเป็น cancelled
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


def sync_expired_bookings():
    """
    ปิดรายการหมดเวลาด้วย datetime จริงแทนการเทียบข้อความใน SQL
    จึงทำงานเหมือนกันทั้ง Windows, Linux/Render และรองรับ DB รุ่นเก่าที่เวลาเป็น 8:30
    """
    now = now_bangkok()
    conn = connect_db()
    rows = conn.execute(
        """
        SELECT id, booking_date, end_time
        FROM booking
        WHERE status='active' AND booking_date IS NOT NULL
        """
    ).fetchall()

    expired = []
    for row in rows:
        end_dt = booking_end_datetime(row["booking_date"], row["end_time"])
        if end_dt is not None and end_dt <= now:
            expired.append((end_dt.isoformat(timespec="seconds"), row["id"]))

    if expired:
        conn.executemany(
            """
            UPDATE booking
            SET status='completed', completed_at=COALESCE(completed_at, ?)
            WHERE id=? AND status='active'
            """,
            expired,
        )
        conn.commit()

    conn.close()
    return len(expired)


@app.before_request
def auto_complete_expired_bookings():
    # ไม่แตะฐานข้อมูลตอน browser โหลด CSS/JS เพื่อลดงานที่ไม่จำเป็น
    if request.endpoint != "static":
        sync_expired_bookings()


def release_after_ms(booking_date, end_time):
    """เวลาที่เหลือก่อนห้องว่าง ใช้ให้หน้าเว็บตรวจสถานะตรงเวลาสิ้นสุด"""
    if not booking_date or booking_date != today_iso() or not end_time:
        return 0
    end_dt = booking_end_datetime(booking_date, end_time)
    if end_dt is None:
        return 0
    return max(0, int((end_dt - now_bangkok()).total_seconds() * 1000))


def verify_csrf():
    token = request.form.get("csrf_token", "")
    if not token or not secrets.compare_digest(token, session.get("csrf_token", "")):
        abort(400, description="คำขอไม่ถูกต้อง กรุณาลองใหม่")


def booking_to_dict(row):
    item = dict(row)
    item["thai_booking_date"] = thai_date(item.get("booking_date")) if item.get("booking_date") else item.get("date", "-")
    item["is_today"] = item.get("booking_date") == today_iso()
    item["can_cancel"] = (
        item.get("owner_id") == str(session.get("user_id"))
        and item.get("status") == "active"
        and item.get("booking_date") == today_iso()
    )
    item["release_after_ms"] = release_after_ms(item.get("booking_date"), item.get("end_time"))
    return item


# --------------------------
# สมัครสมาชิก / เข้าสู่ระบบ / ออกจากระบบ
# --------------------------
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.]{3,50}$")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("home"))

    username = ""
    display_name = ""
    if request.method == "POST":
        verify_csrf()
        username = request.form.get("username", "").strip().lower()
        display_name = request.form.get("display_name", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        error = None
        if not USERNAME_RE.match(username):
            error = "ชื่อผู้ใช้ต้องมี 3-50 ตัวอักษร ใช้ได้เฉพาะ a-z, 0-9, . หรือ _"
        elif len(display_name) < 2 or len(display_name) > 100:
            error = "กรุณากรอกชื่อ-นามสกุล 2-100 ตัวอักษร"
        elif len(password) < 6:
            error = "รหัสผ่านต้องมีอย่างน้อย 6 ตัวอักษร"
        elif password != confirm:
            error = "รหัสผ่านยืนยันไม่ตรงกัน"

        if error:
            flash(error, "error")
            return render_template("register.html", username=username, display_name=display_name)

        conn = connect_db()
        try:
            conn.execute(
                "INSERT INTO user (username, password_hash, display_name, created_at) VALUES (?, ?, ?, ?)",
                (username, generate_password_hash(password), display_name, now_bangkok().isoformat(timespec="seconds")),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            conn.close()
            flash("มีชื่อผู้ใช้นี้ในระบบแล้ว กรุณาใช้ชื่ออื่น", "error")
            return render_template("register.html", username=username, display_name=display_name)
        conn.close()

        flash("สมัครสมาชิกสำเร็จ กรุณาเข้าสู่ระบบ", "success")
        return redirect(url_for("login"))

    return render_template("register.html", username=username, display_name=display_name)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("home"))

    username = ""
    next_url = request.values.get("next", "")
    if not next_url.startswith("/"):
        next_url = ""

    if request.method == "POST":
        verify_csrf()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        conn = connect_db()
        user = conn.execute("SELECT * FROM user WHERE username=?", (username,)).fetchone()
        conn.close()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", "error")
            return render_template("login.html", username=username, next_url=next_url)

        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["display_name"] = user["display_name"]

        flash(f"ยินดีต้อนรับ {user['display_name']}", "success")
        return redirect(next_url or url_for("home"))

    return render_template("login.html", username=username, next_url=next_url)


@app.route("/logout", methods=["POST"])
def logout():
    verify_csrf()
    session.pop("user_id", None)
    session.pop("username", None)
    session.pop("display_name", None)
    flash("ออกจากระบบเรียบร้อยแล้ว", "success")
    return redirect(url_for("login"))


# --------------------------
# หน้าแรก
# --------------------------
@app.route("/")
@login_required
def home():
    total_rooms = sum(len(items) for items in buildings.values())
    conn = connect_db()
    active_rows = conn.execute(
        "SELECT id, building, room, end_time FROM booking WHERE booking_date=? AND status='active'",
        (today_iso(),),
    ).fetchall()
    conn.close()
    booked_today = len(active_rows)
    release_times = [release_after_ms(today_iso(), row["end_time"]) for row in active_rows]
    release_times = [ms for ms in release_times if ms > 0]

    return render_template(
        "index.html",
        buildings=buildings,
        total_rooms=total_rooms,
        booked_today=booked_today,
        available_today=max(total_rooms - booked_today, 0),
        nearest_release_ms=min(release_times) if release_times else 0,
    )


# --------------------------
# แสดงห้องของอาคาร (เฉพาะการจองวันนี้)
# --------------------------
@app.route("/building/<building>")
@login_required
def rooms(building):
    if building not in buildings:
        abort(404)

    now = now_bangkok()
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
        class_entry = None if book else current_class_entry(building, room, now.weekday(), now.time())
        if book:
            room_list.append({
                "room": room,
                "status": "ไม่ว่าง",
                "reason": "booking",
                "name": book["name"],
                "start_time": book["start_time"],
                "end_time": book["end_time"],
                "release_after_ms": release_after_ms(book["booking_date"], book["end_time"]),
            })
        elif class_entry:
            room_list.append({
                "room": room,
                "status": "ไม่ว่าง",
                "reason": "class",
                "name": f"{class_entry['subject']} • {class_entry['teacher']}",
                "start_time": class_entry["start"],
                "end_time": class_entry["end"],
                "release_after_ms": release_after_ms(today_iso(), class_entry["end"]),
            })
        else:
            room_list.append({
                "room": room,
                "status": "ว่าง",
                "reason": None,
                "name": "-",
                "start_time": "",
                "end_time": "",
                "release_after_ms": 0,
            })

    return render_template(
        "rooms.html",
        building=building,
        rooms=room_list,
        today=thai_date(),
        available_count=sum(1 for room in room_list if room["status"] == "ว่าง"),
    )


# --------------------------
# จองห้อง - จองได้เฉพาะวันปัจจุบัน
# --------------------------
@app.route("/booking/<building>/<room>", methods=["GET", "POST"])
@login_required
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

        start_obj = parse_time_text(start)
        end_obj = parse_time_text(end)
        if start_obj is None or end_obj is None:
            flash("รูปแบบเวลาไม่ถูกต้อง", "error")
            return render_template("booking.html", building=building, room=room, today=thai_date())

        # บันทึกให้เป็น HH:MM เสมอ ป้องกันข้อมูลต่างรูปแบบระหว่างเครื่องกับ Render
        start = start_obj.strftime("%H:%M")
        end = end_obj.strftime("%H:%M")

        if start_obj >= end_obj:
            flash("เวลาสิ้นสุดต้องมากกว่าเวลาเริ่ม", "error")
            return render_template("booking.html", building=building, room=room, today=thai_date())

        now = now_bangkok()
        booking_day = now.date().isoformat()
        start_dt = datetime.combine(now.date(), start_obj, tzinfo=BANGKOK_TZ)
        end_dt = datetime.combine(now.date(), end_obj, tzinfo=BANGKOK_TZ)
        # อนุญาตนาทีปัจจุบัน แต่ห้ามเลือกนาทีที่ผ่านไปแล้ว
        now_minute = now.replace(second=0, microsecond=0)
        if start_dt < now_minute:
            flash("เวลาเริ่มต้องเป็นเวลาปัจจุบันหรือหลังจากนี้", "error")
            return render_template("booking.html", building=building, room=room, today=thai_date())
        if end_dt <= now:
            flash("เวลาสิ้นสุดต้องเป็นเวลาหลังจากเวลาปัจจุบัน", "error")
            return render_template("booking.html", building=building, room=room, today=thai_date())

        conflict = class_schedule_conflict(building, room, now.weekday(), start_obj, end_obj)
        if conflict:
            flash(
                f"ห้องนี้มีคาบเรียนวิชา {conflict['subject']} ({conflict['teacher']}) "
                f"เวลา {conflict['start']}-{conflict['end']} ตามตารางเรียน กรุณาเลือกเวลาอื่นหรือห้องอื่น",
                "error",
            )
            return render_template("booking.html", building=building, room=room, today=thai_date())

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
                    str(session["user_id"]),
                    created_at,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            flash("ห้องนี้ยังมีรายการจองที่ไม่หมดเวลา กรุณารอเวลาสิ้นสุดหรือเลือกห้องอื่น", "error")
            return redirect(url_for("rooms", building=building))
        finally:
            conn.close()

        flash(f"จองห้อง {room} สำเร็จ", "success")
        return redirect(url_for("bookings"))

    # ป้องกันเปิดหน้าจองห้องที่ถูกจองแล้วจาก URL โดยตรง
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
        flash("ห้องนี้ยังไม่หมดเวลาการจอง เมื่อถึงเวลาสิ้นสุดจะว่างอัตโนมัติ", "error")
        return redirect(url_for("rooms", building=building))

    now = now_bangkok()
    ongoing_class = current_class_entry(building, room, now.weekday(), now.time())
    if ongoing_class:
        flash(
            f"ห้องนี้มีคาบเรียนวิชา {ongoing_class['subject']} ({ongoing_class['teacher']}) "
            f"ถึงเวลา {ongoing_class['end']} กรุณาเลือกห้องอื่นหรือรอคาบเรียนจบ",
            "error",
        )
        return redirect(url_for("rooms", building=building))

    return render_template("booking.html", building=building, room=room, today=thai_date())


# --------------------------
# รายการจองทั้งหมด + ประวัติย้อนหลัง
# --------------------------
@app.route("/bookings")
@login_required
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
    active_today = [
        item for item in data
        if item["is_today"] and item["status"] == "active"
    ]
    active_ids = {item["id"] for item in active_today}
    history = [item for item in data if item["id"] not in active_ids]

    return render_template(
        "bookings.html",
        active_today=active_today,
        history=history,
        my_active_count=sum(1 for item in active_today if item["can_cancel"]),
    )


# --------------------------
# API สถานะสด - ใช้ให้หน้าเว็บปล่อยห้องทันทีเมื่อหมดเวลา
# --------------------------
@app.route("/api/live-bookings")
@login_required
def live_bookings():
    # before_request จะ sync รายการหมดเวลาให้แล้ว
    now = now_bangkok()
    conn = connect_db()
    rows = conn.execute(
        """
        SELECT id, building, room, end_time
        FROM booking
        WHERE booking_date=? AND status='active'
        ORDER BY end_time ASC, id ASC
        """,
        (now.date().isoformat(),),
    ).fetchall()
    conn.close()

    response = jsonify({
        "ok": True,
        "server_now": now.isoformat(timespec="seconds"),
        "timezone": "Asia/Bangkok (UTC+7)",
        "active_count": len(rows),
        "active_ids": [row["id"] for row in rows],
        "active_rooms": [f"{row['building']}::{row['room']}" for row in rows],
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# --------------------------
# ตรวจเวลา server สำหรับเช็กตอน deploy บน Render
# --------------------------
@app.route("/api/server-time")
def server_time():
    now = now_bangkok()
    response = jsonify({
        "ok": True,
        "server_now": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "time": now.strftime("%H:%M:%S"),
        "timezone": "Asia/Bangkok (UTC+7)",
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


# --------------------------
# ยกเลิกการจอง - เฉพาะเจ้าของ และใช้ POST เท่านั้น
# --------------------------
@app.route("/booking/<int:booking_id>/cancel", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    verify_csrf()
    conn = connect_db()
    row = conn.execute("SELECT * FROM booking WHERE id=?", (booking_id,)).fetchone()

    if row is None:
        conn.close()
        abort(404)

    if row["owner_id"] != str(session.get("user_id")):
        conn.close()
        abort(403, description="คุณไม่มีสิทธิ์ยกเลิกการจองรายการนี้")

    if row["status"] != "active":
        conn.close()
        if row["status"] == "completed":
            flash("รายการนี้สิ้นสุดตามเวลาแล้ว ห้องถูกคืนเป็นว่างอัตโนมัติ", "success")
        else:
            flash("รายการนี้ถูกยกเลิกไปแล้ว", "error")
        return redirect(url_for("bookings"))

    if row["booking_date"] != today_iso():
        conn.close()
        flash("ไม่สามารถยกเลิกรายการย้อนหลังได้", "error")
        return redirect(url_for("bookings"))

    conn.execute(
        "UPDATE booking SET status='cancelled', cancelled_at=? WHERE id=? AND owner_id=?",
        (now_bangkok().isoformat(timespec="seconds"), booking_id, str(session["user_id"])),
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
