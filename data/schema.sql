CREATE TABLE IF NOT EXISTS booking (
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
);

CREATE INDEX IF NOT EXISTS idx_booking_day
ON booking(booking_date, building, room, status);

CREATE INDEX IF NOT EXISTS idx_booking_owner
ON booking(owner_id, booking_date);

CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_room_day_active
ON booking(building, room, booking_date)
WHERE status='active' AND booking_date IS NOT NULL;
