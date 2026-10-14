"""SQLite access for Servisto.

The database file comes from the app config (``DATABASE``), so tests and
deployments can each use their own file. Timestamps and dates are converted
to Python ``datetime``/``date`` objects when read, so templates can format them.
"""
import sqlite3
from datetime import date, datetime

from flask import current_app


def _parse_timestamp(raw: bytes):
    text = raw.decode()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return text


def _parse_date(raw: bytes):
    text = raw.decode()
    try:
        return date.fromisoformat(text)
    except ValueError:
        return text


sqlite3.register_converter('timestamp', _parse_timestamp)
sqlite3.register_converter('date', _parse_date)
sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_adapter(datetime, lambda d: d.strftime('%Y-%m-%d %H:%M:%S'))


def connect(path):
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row  # access columns by name
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def get_db_connection():
    """Open a connection to the configured database. Callers close it."""
    return connect(current_app.config['DATABASE'])


SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    phone TEXT,
    address TEXT,
    user_type TEXT NOT NULL CHECK (user_type IN ('user', 'provider')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    service_type TEXT NOT NULL,
    business_name TEXT,
    description TEXT,
    experience_years INTEGER,
    license_number TEXT,
    service_area TEXT,
    hourly_rate REAL,
    availability_status TEXT DEFAULT 'available',
    average_rating REAL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER NOT NULL,
    service_name TEXT NOT NULL,
    description TEXT,
    base_price REAL NOT NULL,
    duration_hours REAL DEFAULT 1.0,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (provider_id) REFERENCES providers (id)
);

CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    provider_id INTEGER NOT NULL,
    service_id INTEGER NOT NULL,
    booking_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    service_date DATE NOT NULL,
    service_time TEXT NOT NULL,
    address TEXT NOT NULL,
    problem_description TEXT,
    status TEXT DEFAULT 'pending',
    total_amount REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id),
    FOREIGN KEY (provider_id) REFERENCES providers (id),
    FOREIGN KEY (service_id) REFERENCES services (id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER NOT NULL UNIQUE,
    user_id INTEGER NOT NULL,
    provider_id INTEGER NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    provider_response TEXT,
    responded_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (booking_id) REFERENCES bookings (id),
    FOREIGN KEY (user_id) REFERENCES users (id),
    FOREIGN KEY (provider_id) REFERENCES providers (id)
);

CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings (user_id);
CREATE INDEX IF NOT EXISTS idx_bookings_provider ON bookings (provider_id);
CREATE INDEX IF NOT EXISTS idx_reviews_provider ON reviews (provider_id);
-- A provider can't have two open bookings in the same slot.
CREATE UNIQUE INDEX IF NOT EXISTS uq_open_booking_slot
    ON bookings (provider_id, service_date, service_time)
    WHERE status IN ('pending', 'confirmed');
'''


def init_db(path):
    """Create the tables if they don't exist (safe to run on every start)."""
    conn = connect(path)
    conn.executescript(SCHEMA)
    # Databases made by the first version have no review-response columns.
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(reviews)')}
    if 'provider_response' not in columns:
        conn.execute('ALTER TABLE reviews ADD COLUMN provider_response TEXT')
        conn.execute('ALTER TABLE reviews ADD COLUMN responded_at TIMESTAMP')
    conn.commit()
    conn.close()


def refresh_provider_rating(conn, provider_id):
    """Recalculate a provider's average rating from their reviews."""
    avg = conn.execute(
        'SELECT AVG(rating) FROM reviews WHERE provider_id = ?', (provider_id,)
    ).fetchone()[0]
    conn.execute('UPDATE providers SET average_rating = ? WHERE id = ?',
                 (round(avg or 0.0, 2), provider_id))
