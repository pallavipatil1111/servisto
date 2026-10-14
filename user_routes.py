"""Pages for customers: search, provider profiles, booking, cancelling and reviewing."""
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from database import get_db_connection, refresh_provider_rating

user_bp = Blueprint('user', __name__)

BOOKING_STATUSES = ('pending', 'confirmed', 'completed', 'cancelled')

# Bookable start times: (value stored in the database, label shown to the customer).
TIME_SLOTS = [(f'{hour:02d}:00', datetime(2000, 1, 1, hour).strftime('%I:%M %p').lstrip('0'))
              for hour in range(8, 18)]
SLOT_VALUES = {value for value, _ in TIME_SLOTS}

# ORDER BY clauses for the search page, picked by name so request text never reaches the SQL.
SEARCH_ORDERS = {
    'recommended': 'p.average_rating DESC, review_count DESC, p.business_name',
    'rating': 'COALESCE(avg_rating, 0) DESC, p.business_name',
    'reviews': 'review_count DESC, p.business_name',
    'price': 'p.hourly_rate IS NULL, p.hourly_rate ASC, p.business_name',
}


def customer_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if current_user.user_type != 'user':
            flash('Access denied. This page is for customers only.', 'error')
            return redirect(url_for('provider.dashboard'))
        return view(*args, **kwargs)
    return wrapper


@user_bp.route('/dashboard')
@customer_required
def dashboard():
    conn = get_db_connection()
    recent_bookings = conn.execute('''
        SELECT b.*, p.business_name, p.service_type, s.service_name
        FROM bookings b
        JOIN providers p ON b.provider_id = p.id
        JOIN services s ON b.service_id = s.id
        WHERE b.user_id = ?
        ORDER BY b.created_at DESC, b.id DESC
        LIMIT 5
    ''', (current_user.id,)).fetchall()
    counts = dict(conn.execute(
        'SELECT status, COUNT(*) FROM bookings WHERE user_id = ? GROUP BY status', (current_user.id,)
    ).fetchall())
    conn.close()

    return render_template('user/dashboard.html',
                           recent_bookings=recent_bookings,
                           total_bookings=sum(counts.values()),
                           completed_bookings=counts.get('completed', 0),
                           pending_bookings=counts.get('pending', 0))


@user_bp.route('/search')
@customer_required
def search():
    service_type = request.args.get('service_type', '').strip()
    location = request.args.get('location', '').strip()
    min_rating = request.args.get('min_rating', 0, type=float) or 0

    query = '''
        SELECT p.*, u.first_name, u.last_name, u.phone,
               (SELECT COUNT(*) FROM reviews r WHERE r.provider_id = p.id) AS review_count,
               (SELECT AVG(rating) FROM reviews r WHERE r.provider_id = p.id) AS avg_rating
        FROM providers p
        JOIN users u ON p.user_id = u.id
        WHERE p.availability_status = 'available'
          AND EXISTS (SELECT 1 FROM services s WHERE s.provider_id = p.id AND s.is_active = 1)
    '''
    params = []
    if service_type:
        query += ' AND p.service_type LIKE ?'
        params.append(f'%{service_type}%')
    if location:
        query += ' AND (p.service_area LIKE ? OR p.business_name LIKE ?)'
        params.extend([f'%{location}%', f'%{location}%'])
    if min_rating > 0:
        query += ' AND COALESCE((SELECT AVG(rating) FROM reviews r WHERE r.provider_id = p.id), 0) >= ?'
        params.append(min_rating)
    sort = request.args.get('sort', 'recommended')
    if sort not in SEARCH_ORDERS:
        sort = 'recommended'
    query += ' ORDER BY ' + SEARCH_ORDERS[sort]

    conn = get_db_connection()
    providers = []
    for row in conn.execute(query, params).fetchall():
        provider = dict(row)
        provider['services'] = conn.execute(
            'SELECT service_name, base_price FROM services WHERE provider_id = ? AND is_active = 1 '
            'ORDER BY base_price', (row['id'],)).fetchall()
        providers.append(provider)
    service_types = [row[0] for row in conn.execute(
        "SELECT DISTINCT service_type FROM providers WHERE service_type IS NOT NULL "
        "AND service_type != 'general' ORDER BY service_type")]
    conn.close()

    return render_template('user/search.html',
                           providers=providers,
                           service_types=service_types,
                           search_params={'service_type': service_type,
                                          'location': location,
                                          'min_rating': min_rating,
                                          'sort': sort})


@user_bp.route('/provider/<int:provider_id>')
@customer_required
def provider_detail(provider_id):
    conn = get_db_connection()
    provider = conn.execute('''
        SELECT p.*, u.first_name, u.last_name, u.email, u.phone
        FROM providers p
        JOIN users u ON p.user_id = u.id
        WHERE p.id = ?
    ''', (provider_id,)).fetchone()

    if not provider:
        conn.close()
        flash('Provider not found.', 'error')
        return redirect(url_for('user.search'))

    services = conn.execute(
        'SELECT * FROM services WHERE provider_id = ? AND is_active = 1 ORDER BY base_price',
        (provider_id,)).fetchall()
    reviews = conn.execute('''
        SELECT r.*, u.first_name, u.last_name
        FROM reviews r
        JOIN users u ON r.user_id = u.id
        WHERE r.provider_id = ?
        ORDER BY r.created_at DESC, r.id DESC
    ''', (provider_id,)).fetchall()
    completed_bookings = conn.execute(
        "SELECT COUNT(*) FROM bookings WHERE provider_id = ? AND status = 'completed'",
        (provider_id,)).fetchone()[0]
    conn.close()

    return render_template('user/provider_detail.html',
                           provider=dict(provider),
                           services=services,
                           reviews=reviews,
                           completed_bookings=completed_bookings)


def _parse_booking_form(form):
    """Return (values, errors) for the booking form."""
    values = {key: (form.get(key) or '').strip() for key in
              ('service_id', 'service_date', 'service_time', 'address', 'problem_description')}
    errors = []
    if not all(values[k] for k in ('service_id', 'service_date', 'service_time', 'address')):
        errors.append('Please fill in all required fields.')
        return values, errors
    try:
        when = date.fromisoformat(values['service_date'])
        if when < date.today():
            errors.append('Please choose today or a future date.')
        values['service_date'] = when
    except ValueError:
        errors.append('Please choose a valid date.')
    if values['service_time'] not in SLOT_VALUES:
        errors.append('Please choose one of the listed times.')
    elif (isinstance(values['service_date'], date) and values['service_date'] == date.today()
          and values['service_time'] <= datetime.now().strftime('%H:%M')):
        errors.append('That time has already passed today. Please choose a later slot.')
    if len(values['address']) > 300 or len(values['problem_description']) > 1000:
        errors.append('The address or description is too long.')
    return values, errors


@user_bp.route('/book/<int:provider_id>', methods=['GET', 'POST'])
@customer_required
def book_service(provider_id):
    conn = get_db_connection()
    provider = conn.execute('SELECT * FROM providers WHERE id = ?', (provider_id,)).fetchone()
    if not provider:
        conn.close()
        flash('Provider not found.', 'error')
        return redirect(url_for('user.search'))

    services = conn.execute(
        'SELECT * FROM services WHERE provider_id = ? AND is_active = 1 ORDER BY base_price',
        (provider_id,)).fetchall()

    def show_form(status=200):
        # Slots this provider already has booked, so the form can grey them out.
        taken = {}
        for row in conn.execute(
                "SELECT service_date, service_time FROM bookings WHERE provider_id = ? "
                "AND status IN ('pending', 'confirmed') AND service_date >= ?", (provider_id, date.today())):
            taken.setdefault(str(row['service_date']), []).append(row['service_time'])
        conn.close()
        selected_id = request.form.get('service_id') or request.args.get('service_id') or ''
        if not any(str(s['id']) == selected_id for s in services):
            selected_id = str(services[0]['id']) if services else ''
        selected_service = next((s for s in services if str(s['id']) == selected_id), None)
        return render_template('user/booking.html', provider=provider, services=services,
                               form=request.form, time_slots=TIME_SLOTS, taken_slots=taken,
                               selected_id=selected_id, selected_service=selected_service,
                               today=date.today().isoformat(),
                               default_date=(date.today() + timedelta(days=1)).isoformat()), status

    if request.method == 'POST':
        if provider['availability_status'] != 'available':
            flash('This provider is not taking new bookings right now.', 'error')
            return show_form(409)

        values, errors = _parse_booking_form(request.form)
        selected = None
        if not errors:
            # The service must belong to this provider and still be offered.
            selected = conn.execute(
                'SELECT * FROM services WHERE id = ? AND provider_id = ? AND is_active = 1',
                (values['service_id'], provider_id)).fetchone()
            if not selected:
                errors.append('Invalid service selected.')
        if errors:
            for error in errors:
                flash(error, 'error')
            return show_form(400)

        try:
            # A partial unique index stops two open bookings for the same provider and slot,
            # even if two customers submit at the same moment.
            conn.execute('''
                INSERT INTO bookings (user_id, provider_id, service_id, service_date, service_time,
                                      address, problem_description, total_amount, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            ''', (current_user.id, provider_id, selected['id'], values['service_date'],
                  values['service_time'], values['address'], values['problem_description'] or None,
                  selected['base_price']))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            flash('Sorry, that time slot was just booked. Please choose another time.', 'error')
            return show_form(409)
        conn.close()
        flash('Booking request sent successfully! The provider will confirm shortly.', 'success')
        return redirect(url_for('user.bookings'))

    return show_form()


@user_bp.route('/bookings')
@customer_required
def bookings():
    status_filter = request.args.get('status', 'all')
    if status_filter not in BOOKING_STATUSES:
        status_filter = 'all'

    conn = get_db_connection()
    rows = conn.execute('''
        SELECT b.*, p.business_name, p.service_type, s.service_name,
               pu.first_name, pu.last_name, pu.phone,
               r.id AS review_id
        FROM bookings b
        JOIN providers p ON b.provider_id = p.id
        JOIN users pu ON p.user_id = pu.id
        JOIN services s ON b.service_id = s.id
        LEFT JOIN reviews r ON r.booking_id = b.id
        WHERE b.user_id = ?
        ORDER BY b.created_at DESC, b.id DESC
    ''', (current_user.id,)).fetchall()
    conn.close()

    all_bookings = []
    for row in rows:
        booking = dict(row)
        booking['review'] = booking['review_id'] is not None
        created = booking['created_at']
        booking['created_at_formatted'] = (created.strftime('%d %b %Y, %I:%M %p')
                                           if isinstance(created, datetime) else created or 'Unknown date')
        all_bookings.append(booking)

    shown = all_bookings if status_filter == 'all' else [b for b in all_bookings if b['status'] == status_filter]
    return render_template('user/bookings.html', bookings=shown, all_bookings=all_bookings,
                           status_filter=status_filter)


def _own_booking(conn, booking_id):
    return conn.execute('''
        SELECT b.*, s.service_name
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        WHERE b.id = ? AND b.user_id = ?
    ''', (booking_id, current_user.id)).fetchone()


@user_bp.route('/review/<int:booking_id>', methods=['GET', 'POST'])
@customer_required
def review_booking(booking_id):
    conn = get_db_connection()
    row = _own_booking(conn, booking_id)

    problem = None
    if not row:
        problem = 'Booking not found.'
    elif row['status'] != 'completed':
        problem = 'You can only review completed bookings.'
    elif conn.execute('SELECT 1 FROM reviews WHERE booking_id = ?', (booking_id,)).fetchone():
        problem = 'You have already reviewed this booking.'
    if problem:
        conn.close()
        flash(problem, 'error')
        return redirect(url_for('user.bookings'))

    booking = row
    provider = conn.execute('SELECT * FROM providers WHERE id = ?', (row['provider_id'],)).fetchone()
    review_count = conn.execute(
        'SELECT COUNT(*) FROM reviews WHERE provider_id = ?', (row['provider_id'],)).fetchone()[0]

    def show_form(status=200):
        conn.close()
        return render_template('user/review.html', booking=booking, provider=provider,
                               review_count=review_count), status

    if request.method == 'POST':
        rating = request.form.get('rating', type=int)
        comment = (request.form.get('comment') or '').strip()
        if rating not in (1, 2, 3, 4, 5):
            flash('Please choose a rating from 1 to 5 stars.', 'error')
            return show_form(400)
        if len(comment) > 1000:
            flash('Please keep your review under 1000 characters.', 'error')
            return show_form(400)

        conn.execute(
            'INSERT INTO reviews (booking_id, user_id, provider_id, rating, comment) VALUES (?, ?, ?, ?, ?)',
            (booking_id, current_user.id, row['provider_id'], rating, comment or None))
        refresh_provider_rating(conn, row['provider_id'])
        conn.commit()
        conn.close()
        flash('Thank you for your review!', 'success')
        return redirect(url_for('user.bookings'))

    return show_form()


@user_bp.route('/booking/<int:booking_id>/cancel', methods=['POST'])
@customer_required
def cancel_booking(booking_id):
    conn = get_db_connection()
    booking = _own_booking(conn, booking_id)

    if not booking:
        flash('Booking not found.', 'error')
    elif booking['status'] not in ('pending', 'confirmed'):
        flash('This booking cannot be cancelled.', 'error')
    else:
        conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
        conn.commit()
        flash('Booking cancelled successfully.', 'success')
    conn.close()
    return redirect(url_for('user.bookings'))
