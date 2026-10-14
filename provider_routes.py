"""Pages for service providers: profile, services, bookings and reviews."""
from datetime import date
from functools import wraps

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from database import get_db_connection

provider_bp = Blueprint('provider', __name__)

AVAILABILITY = ('available', 'busy', 'unavailable')
BOOKING_STATUSES = ('pending', 'confirmed', 'completed', 'cancelled')

# Which status a booking may move to from its current one.
ALLOWED_TRANSITIONS = {
    'pending': {'confirmed', 'cancelled'},
    'confirmed': {'completed', 'cancelled'},
    'completed': set(),
    'cancelled': set(),
}

# The ORDER BY clause comes from this fixed map, never from the request itself.
SORT_ORDERS = {
    'date': 'b.service_date ASC, b.service_time ASC',
    'customer': 'u.first_name COLLATE NOCASE, u.last_name COLLATE NOCASE, b.service_date',
    'service': 's.service_name COLLATE NOCASE, b.service_date',
}

STATUS_MESSAGES = {
    'confirmed': 'Booking confirmed!',
    'completed': 'Service marked as completed!',
    'cancelled': 'Booking cancelled.',
}



def provider_required(view):
    """Only providers get in; the view receives (conn, provider) as its first two arguments."""
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if current_user.user_type != 'provider':
            if request.method == 'POST':
                return jsonify({'success': False, 'message': 'Access denied'}), 403
            flash('Access denied. This page is for service providers only.', 'error')
            return redirect(url_for('user.dashboard'))
        conn = get_db_connection()
        provider = conn.execute('SELECT * FROM providers WHERE user_id = ?', (current_user.id,)).fetchone()
        if not provider:
            # Should not happen (registration creates it), but recover instead of crashing.
            conn.execute(
                "INSERT INTO providers (user_id, business_name, service_type, availability_status) "
                "VALUES (?, ?, 'general', 'available')",
                (current_user.id, f'{current_user.first_name} {current_user.last_name}'))
            conn.commit()
            provider = conn.execute('SELECT * FROM providers WHERE user_id = ?', (current_user.id,)).fetchone()
        try:
            return view(conn, provider, *args, **kwargs)
        finally:
            conn.close()
    return wrapper


@provider_bp.route('/dashboard')
@provider_required
def dashboard(conn, provider):
    recent_bookings = conn.execute('''
        SELECT b.*, u.first_name, u.last_name, u.email, u.phone, s.service_name
        FROM bookings b
        JOIN users u ON b.user_id = u.id
        JOIN services s ON b.service_id = s.id
        WHERE b.provider_id = ?
        ORDER BY b.created_at DESC, b.id DESC
        LIMIT 5
    ''', (provider['id'],)).fetchall()
    counts = dict(conn.execute(
        'SELECT status, COUNT(*) FROM bookings WHERE provider_id = ? GROUP BY status', (provider['id'],)
    ).fetchall())
    month_start = date.today().replace(day=1)
    monthly_earnings = conn.execute(
        "SELECT SUM(total_amount) FROM bookings WHERE provider_id = ? AND status = 'completed' "
        'AND service_date >= ?', (provider['id'], month_start)).fetchone()[0] or 0
    profile_incomplete = provider['service_type'] == 'general' or not provider['service_area']
    has_services = conn.execute(
        'SELECT 1 FROM services WHERE provider_id = ? AND is_active = 1', (provider['id'],)).fetchone() is not None

    return render_template('provider/dashboard.html',
                           provider=provider,
                           recent_bookings=recent_bookings,
                           total_bookings=sum(counts.values()),
                           pending_bookings=counts.get('pending', 0),
                           confirmed_bookings=counts.get('confirmed', 0),
                           completed_bookings=counts.get('completed', 0),
                           monthly_earnings=monthly_earnings,
                           profile_incomplete=profile_incomplete,
                           has_services=has_services)


def _parse_profile(form):
    values = {key: (form.get(key) or '').strip() for key in (
        'business_name', 'service_type', 'description', 'experience_years', 'license_number',
        'service_area', 'hourly_rate', 'availability_status', 'phone', 'address')}
    errors = []
    if not values['business_name']:
        errors.append('Please enter a business name.')
    if not values['service_type']:
        errors.append('Please choose a service type.')
    values['service_type'] = values['service_type'].lower()
    if values['availability_status'] not in AVAILABILITY:
        errors.append('Please choose a valid availability status.')
    try:
        years = int(values['experience_years'] or 0)
        if not 0 <= years <= 60:
            raise ValueError
        values['experience_years'] = years
    except ValueError:
        errors.append('Years of experience must be a whole number between 0 and 60.')
    try:
        rate = float(values['hourly_rate']) if values['hourly_rate'] else None
        if rate is not None and not 0 <= rate <= 100000:
            raise ValueError
        values['hourly_rate'] = rate
    except ValueError:
        errors.append('Hourly rate must be a number between 0 and 1,00,000.')
    return values, errors


@provider_bp.route('/profile', methods=['GET', 'POST'])
@provider_required
def profile(conn, provider):
    user = conn.execute('SELECT * FROM users WHERE id = ?', (current_user.id,)).fetchone()

    if request.method == 'POST':
        values, errors = _parse_profile(request.form)
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('provider/profile.html', provider=provider, user=user), 400

        conn.execute('''
            UPDATE providers SET business_name = ?, service_type = ?, description = ?,
                   experience_years = ?, license_number = ?, service_area = ?, hourly_rate = ?,
                   availability_status = ?
            WHERE id = ?
        ''', (values['business_name'], values['service_type'], values['description'] or None,
              values['experience_years'], values['license_number'] or None, values['service_area'] or None,
              values['hourly_rate'], values['availability_status'], provider['id']))
        conn.execute('UPDATE users SET phone = ?, address = ? WHERE id = ?',
                     (values['phone'] or None, values['address'] or None, current_user.id))
        conn.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('provider.profile'))

    return render_template('provider/profile.html', provider=provider, user=user)


@provider_bp.route('/services', methods=['GET', 'POST'])
@provider_required
def services(conn, provider):
    def show(status=200):
        rows = conn.execute('SELECT * FROM services WHERE provider_id = ? ORDER BY is_active DESC, id',
                            (provider['id'],)).fetchall()
        return render_template('provider/services.html', services=rows, provider=provider), status

    if request.method == 'POST':
        service_name = (request.form.get('service_name') or '').strip()
        description = (request.form.get('description') or '').strip()
        try:
            base_price = float(request.form.get('base_price') or '')
            duration_hours = float(request.form.get('duration_hours') or 1.0)
        except ValueError:
            base_price = duration_hours = -1
        if not service_name or base_price <= 0 or not 0 < duration_hours <= 24:
            flash('Please enter a service name, a price above zero and a duration of up to 24 hours.', 'error')
            return show(400)

        conn.execute(
            'INSERT INTO services (provider_id, service_name, description, base_price, duration_hours) '
            'VALUES (?, ?, ?, ?, ?)',
            (provider['id'], service_name, description or None, base_price, duration_hours))
        conn.commit()
        flash('Service added successfully!', 'success')
        return redirect(url_for('provider.services'))

    return show()


@provider_bp.route('/service/<int:service_id>/toggle', methods=['POST'])
@provider_required
def toggle_service(conn, provider, service_id):
    service = conn.execute('SELECT * FROM services WHERE id = ? AND provider_id = ?',
                           (service_id, provider['id'])).fetchone()
    if not service:
        return jsonify({'success': False, 'message': 'Service not found'}), 404

    new_status = 0 if service['is_active'] else 1
    conn.execute('UPDATE services SET is_active = ? WHERE id = ?', (new_status, service_id))
    conn.commit()
    return jsonify({'success': True, 'is_active': bool(new_status),
                    'message': f'Service {"activated" if new_status else "deactivated"} successfully!'})


@provider_bp.route('/bookings')
@provider_required
def bookings(conn, provider):
    status_filter = request.args.get('status', 'all')
    if status_filter not in BOOKING_STATUSES:
        status_filter = 'all'
    sort = request.args.get('sort', 'date')
    order_by = SORT_ORDERS.get(sort)
    if not order_by:
        sort, order_by = 'date', SORT_ORDERS['date']
    rows = conn.execute(f'''
        SELECT b.*, u.first_name, u.last_name, u.email, u.phone, s.service_name, s.duration_hours,
               r.id AS review_id
        FROM bookings b
        JOIN users u ON b.user_id = u.id
        JOIN services s ON b.service_id = s.id
        LEFT JOIN reviews r ON r.booking_id = b.id
        WHERE b.provider_id = ?
        ORDER BY {order_by}
    ''', (provider['id'],)).fetchall()

    all_bookings = []
    for row in rows:
        booking = dict(row)
        booking['review'] = booking['review_id'] is not None
        created = booking['created_at']
        booking['created_at_formatted'] = created.strftime('%d %b %Y') if hasattr(created, 'strftime') else created
        all_bookings.append(booking)
    shown = all_bookings if status_filter == 'all' else [b for b in all_bookings if b['status'] == status_filter]
    return render_template('provider/bookings.html', bookings=shown, all_bookings=all_bookings,
                           status_filter=status_filter, sort=sort, provider=provider)


@provider_bp.route('/booking/<int:booking_id>/update_status', methods=['POST'])
@provider_required
def update_booking_status(conn, provider, booking_id):
    booking = conn.execute('SELECT * FROM bookings WHERE id = ? AND provider_id = ?',
                           (booking_id, provider['id'])).fetchone()
    if not booking:
        return jsonify({'success': False, 'message': 'Booking not found'}), 404

    new_status = request.form.get('status')
    if new_status not in BOOKING_STATUSES:
        return jsonify({'success': False, 'message': 'Invalid status'}), 400
    if new_status not in ALLOWED_TRANSITIONS[booking['status']]:
        return jsonify({'success': False,
                        'message': f'A {booking["status"]} booking cannot be marked {new_status}.'}), 409

    conn.execute('UPDATE bookings SET status = ? WHERE id = ?', (new_status, booking_id))
    conn.commit()
    return jsonify({'success': True, 'message': STATUS_MESSAGES[new_status], 'new_status': new_status})


@provider_bp.route('/reviews')
@provider_required
def reviews(conn, provider):
    rows = conn.execute('''
        SELECT r.*, u.first_name, u.last_name, b.service_date, s.service_name
        FROM reviews r
        JOIN users u ON r.user_id = u.id
        JOIN bookings b ON r.booking_id = b.id
        JOIN services s ON b.service_id = s.id
        WHERE r.provider_id = ?
        ORDER BY r.created_at DESC, r.id DESC
    ''', (provider['id'],)).fetchall()

    return render_template('provider/reviews.html', reviews=rows, provider=provider)


@provider_bp.route('/review/<int:review_id>/respond', methods=['POST'])
@provider_required
def respond_to_review(conn, provider, review_id):
    review = conn.execute('SELECT * FROM reviews WHERE id = ? AND provider_id = ?',
                          (review_id, provider['id'])).fetchone()
    if not review:
        flash('Review not found.', 'error')
        return redirect(url_for('provider.reviews'))

    response = (request.form.get('response') or '').strip()
    if not response or len(response) > 1000:
        flash('Please write a reply of up to 1000 characters.', 'error')
        return redirect(url_for('provider.reviews'))

    conn.execute('UPDATE reviews SET provider_response = ?, responded_at = CURRENT_TIMESTAMP WHERE id = ?',
                 (response, review_id))
    conn.commit()
    flash('Your reply has been posted.', 'success')
    return redirect(url_for('provider.reviews'))


@provider_bp.route('/availability', methods=['POST'])
@provider_required
def update_availability(conn, provider):
    new_status = request.form.get('availability_status')
    if new_status not in AVAILABILITY:
        return jsonify({'success': False, 'message': 'Invalid status'}), 400

    conn.execute('UPDATE providers SET availability_status = ? WHERE id = ?', (new_status, provider['id']))
    conn.commit()
    return jsonify({'success': True, 'message': f'Availability updated to {new_status}!',
                    'new_status': new_status})
