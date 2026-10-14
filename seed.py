"""Demo data, so a fresh install has something to look at.

Runs only when the users table is empty, so it never touches real data.
Turn it off with SEED_DEMO_DATA=false.
"""
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

from database import connect, refresh_provider_rating

DEMO_PASSWORD = 'demo1234'

CUSTOMERS = [
    ('customer@servisto.demo', 'Ananya', 'Kulkarni', '9822001100', 'Flat 12, Shivaji Nagar, Pune'),
]

# (email, first, last, phone, business, type, description, years, area, rate, services)
PROVIDERS = [
    ('plumber@servisto.demo', 'Rahul', 'Jadhav', '9822003344', 'Jadhav Plumbing Works', 'plumbing',
     'Leak repairs, bathroom fittings and water-tank cleaning. Same-day visits in most areas.',
     8, 'Pune, Kothrud, Karve Nagar', 350,
     [('Tap and leak repair', 'Fix dripping taps, pipe joints and small leaks.', 299, 1),
      ('Bathroom fitting', 'Install a shower, basin, geyser connection or flush tank.', 899, 2.5),
      ('Water tank cleaning', 'Clean and disinfect an overhead tank up to 1000 L.', 649, 2)]),
    ('electrician@servisto.demo', 'Sneha', 'Patil', '9822005566', 'BrightSpark Electricals', 'electrical',
     'Licensed electrician for wiring, fans, lights and inverter installation.',
     6, 'Pune, Baner, Aundh', 400,
     [('Fan or light installation', 'Install or replace a ceiling fan or light fitting.', 249, 1),
      ('House wiring check', 'Safety check of the switchboard, earthing and MCBs.', 799, 2)]),
    ('cleaner@servisto.demo', 'Imran', 'Shaikh', '9822007788', 'Sparkle Home Cleaning', 'cleaning',
     'Deep cleaning for flats and offices with our own equipment and eco-friendly products.',
     4, 'Pune, Hadapsar, Viman Nagar', 300,
     [('1 BHK deep cleaning', 'Kitchen, bathroom, floors, windows and fans.', 2499, 4),
      ('Sofa shampooing', 'Shampoo and vacuum a 5-seater sofa.', 999, 2)]),
]


def seed_demo_data(path):
    conn = connect(path)
    if conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] > 0:
        conn.close()
        return False

    password_hash = generate_password_hash(DEMO_PASSWORD)
    customer_ids = []
    for email, first, last, phone, address in CUSTOMERS:
        cur = conn.execute(
            'INSERT INTO users (email, password_hash, first_name, last_name, phone, address, user_type) '
            "VALUES (?, ?, ?, ?, ?, ?, 'user')",
            (email, password_hash, first, last, phone, address))
        customer_ids.append(cur.lastrowid)

    provider_services = []
    for (email, first, last, phone, business, kind, desc, years, area, rate, services) in PROVIDERS:
        user_id = conn.execute(
            'INSERT INTO users (email, password_hash, first_name, last_name, phone, address, user_type) '
            "VALUES (?, ?, ?, ?, ?, ?, 'provider')",
            (email, password_hash, first, last, phone, area.split(',')[0])).lastrowid
        provider_id = conn.execute(
            'INSERT INTO providers (user_id, service_type, business_name, description, experience_years, '
            'license_number, service_area, hourly_rate, availability_status) '
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'available')",
            (user_id, kind, business, desc, years, f'MH-{kind[:3].upper()}-{1000 + user_id}', area, rate)
        ).lastrowid
        service_ids = []
        for name, sdesc, price, hours in services:
            service_ids.append(conn.execute(
                'INSERT INTO services (provider_id, service_name, description, base_price, duration_hours) '
                'VALUES (?, ?, ?, ?, ?)', (provider_id, name, sdesc, price, hours)).lastrowid)
        provider_services.append((provider_id, service_ids))

    # A few bookings in different states, so every page has content.
    customer = customer_ids[0]
    address = CUSTOMERS[0][4]
    today = date.today()
    plumber, electrician, cleaner = provider_services
    bookings = [
        (plumber, 0, today - timedelta(days=12), '10:00', 'completed', 'Kitchen tap has been dripping for a week.'),
        (cleaner, 0, today - timedelta(days=5), '09:00', 'completed', 'Deep clean before guests arrive.'),
        (electrician, 0, today + timedelta(days=2), '17:00', 'confirmed', 'Bedroom fan makes a noise.'),
        (plumber, 1, today + timedelta(days=4), '11:00', 'pending', 'New geyser needs connecting.'),
    ]
    booking_ids = []
    for (provider_id, service_ids), idx, when, time, status, problem in bookings:
        price = conn.execute('SELECT base_price FROM services WHERE id = ?', (service_ids[idx],)).fetchone()[0]
        booking_ids.append(conn.execute(
            'INSERT INTO bookings (user_id, provider_id, service_id, service_date, service_time, address, '
            'problem_description, status, total_amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (customer, provider_id, service_ids[idx], when, time, address, problem, status, price)
        ).lastrowid)

    # The plumber's job has a review with a reply; the cleaning job is still waiting for one.
    conn.execute(
        'INSERT INTO reviews (booking_id, user_id, provider_id, rating, comment, provider_response, responded_at) '
        "VALUES (?, ?, ?, 5, ?, ?, CURRENT_TIMESTAMP)",
        (booking_ids[0], customer, plumber[0], 'Came on time and fixed the leak in 20 minutes. Very polite.',
         'Thank you, Ananya! Happy to help any time.'))
    refresh_provider_rating(conn, plumber[0])

    conn.commit()
    conn.close()
    return True
