import re
from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db_connection
from models import User

auth_bp = Blueprint('auth', __name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
PHONE_RE = re.compile(r'^[0-9+\-\s]{7,15}$')
MIN_PASSWORD_LENGTH = 8


def dashboard_for(user):
    return url_for('provider.dashboard' if user.user_type == 'provider' else 'user.dashboard')


def is_safe_next(target):
    """Only follow ?next= links that stay on this site."""
    if not target:
        return False
    parts = urlsplit(target)
    return not parts.scheme and not parts.netloc and target.startswith('/') and not target.startswith('//')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(dashboard_for(current_user))

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''
        first_name = (request.form.get('first_name') or '').strip()
        last_name = (request.form.get('last_name') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        user_type = request.form.get('user_type')

        errors = []
        if not first_name or not last_name:
            errors.append('Please enter your first and last name.')
        if not EMAIL_RE.match(email):
            errors.append('Please enter a valid email address.')
        if phone and not PHONE_RE.match(phone):
            errors.append('Please enter a valid phone number.')
        if user_type not in ('user', 'provider'):
            errors.append('Please choose whether you are a customer or a service provider.')
        if len(password) < MIN_PASSWORD_LENGTH:
            errors.append(f'Password must be at least {MIN_PASSWORD_LENGTH} characters long.')
        if password != confirm_password:
            errors.append('Passwords do not match.')

        conn = get_db_connection()
        if not errors and conn.execute('SELECT 1 FROM users WHERE email = ?', (email,)).fetchone():
            errors.append('Email already registered. Please use a different email.')

        if errors:
            conn.close()
            for error in errors:
                flash(error, 'error')
            return render_template('auth/register.html', email=email, first_name=first_name,
                                   last_name=last_name, phone=phone, user_type=user_type), 400

        try:
            user_id = conn.execute(
                'INSERT INTO users (email, password_hash, first_name, last_name, phone, user_type) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (email, generate_password_hash(password), first_name, last_name, phone or None, user_type)
            ).lastrowid
            if user_type == 'provider':
                conn.execute(
                    'INSERT INTO providers (user_id, business_name, service_type, availability_status) '
                    "VALUES (?, ?, 'general', 'available')",
                    (user_id, f'{first_name} {last_name}'))
            conn.commit()
        finally:
            conn.close()

        flash('Registration successful! Please log in to continue.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', user_type=request.args.get('type'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(dashboard_for(current_user))

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        remember = bool(request.form.get('remember'))

        conn = get_db_connection()
        row = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()

        # Same message whether the email or the password is wrong.
        if not row or not check_password_hash(row['password_hash'], password):
            flash('Invalid email or password. Please try again.', 'error')
            return render_template('auth/login.html', email=email), 401

        user = User.from_row(row)
        login_user(user, remember=remember)
        flash(f'Welcome back, {user.first_name}!', 'success')

        target = request.args.get('next')
        return redirect(target if is_safe_next(target) else dashboard_for(user))

    return render_template('auth/login.html')


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('index'))
