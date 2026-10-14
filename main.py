"""Servisto: a marketplace for booking local home-service professionals."""
import os
import secrets
from datetime import date, datetime

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, url_for
from flask_login import LoginManager, current_user

from csrf import init_csrf
from database import get_db_connection, init_db
from models import User

load_dotenv()

SERVICE_ICONS = {
    'plumbing': 'fa-wrench',
    'electrical': 'fa-bolt',
    'cleaning': 'fa-broom',
    'painting': 'fa-paint-roller',
    'carpentry': 'fa-hammer',
    'gardening': 'fa-leaf',
    'moving': 'fa-truck-moving',
    'repair': 'fa-tools',
    'installation': 'fa-cogs',
    'maintenance': 'fa-clipboard-check',
    'landscaping': 'fa-tree',
    'carpet cleaning': 'fa-soap',
    'appliance repair': 'fa-toolbox',
    'handyman': 'fa-screwdriver',
    'pool cleaning': 'fa-water',
    'pest control': 'fa-bug',
    'roofing': 'fa-home',
    'fencing': 'fa-border-all',
    'concrete': 'fa-square',
    'drywall': 'fa-th-large',
}


def get_service_icon(service_type):
    if service_type:
        return SERVICE_ICONS.get(service_type.lower(), 'fa-hard-hat')
    return 'fa-hard-hat'


def format_inr(amount):
    """Format a number as Indian rupees with lakh grouping: 125000 -> ₹1,25,000."""
    if amount is None:
        amount = 0
    amount = float(amount)
    sign = '-' if amount < 0 else ''
    rupees, paise = f'{abs(amount):.2f}'.split('.')
    if len(rupees) > 3:
        head, tail = rupees[:-3], rupees[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        rupees = ','.join(groups + [tail])
    text = f'{sign}₹{rupees}'
    return text if paise == '00' else f'{text}.{paise}'


def format_time12(value):
    """'17:00' -> '5:00 PM'. Anything else is shown as it is."""
    try:
        return datetime.strptime(str(value), '%H:%M').strftime('%I:%M %p').lstrip('0')
    except ValueError:
        return value


def env_flag(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)

    secret = os.environ.get('SECRET_KEY') or (config or {}).get('SECRET_KEY')
    if not secret:
        # Fine for trying it out locally; sessions just won't survive a restart.
        secret = secrets.token_hex(32)
        app.logger.warning('SECRET_KEY is not set; using a random key for this run.')

    app.config.update(
        SECRET_KEY=secret,
        DATABASE=os.environ.get('DATABASE_PATH') or os.path.join(app.instance_path, 'servisto.db'),
        SEED_DEMO_DATA=env_flag('SEED_DEMO_DATA', True),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=env_flag('SECURE_COOKIES', False),
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE='Lax',
        REMEMBER_COOKIE_SECURE=env_flag('SECURE_COOKIES', False),
    )
    if config:
        app.config.update(config)

    os.makedirs(os.path.dirname(os.path.abspath(app.config['DATABASE'])), exist_ok=True)
    init_db(app.config['DATABASE'])
    if app.config['SEED_DEMO_DATA']:
        from seed import seed_demo_data
        seed_demo_data(app.config['DATABASE'])

    init_csrf(app)

    login_manager = LoginManager(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to continue.'
    login_manager.login_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        conn = get_db_connection()
        row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        conn.close()
        return User.from_row(row) if row else None

    app.jinja_env.filters['inr'] = format_inr
    app.jinja_env.filters['time12'] = format_time12

    @app.context_processor
    def utility_processor():
        return dict(getServiceIcon=get_service_icon, now_year=date.today().year)

    from auth import auth_bp
    from provider_routes import provider_bp
    from user_routes import user_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp, url_prefix='/user')
    app.register_blueprint(provider_bp, url_prefix='/provider')

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            if current_user.user_type == 'provider':
                return redirect(url_for('provider.dashboard'))
            return redirect(url_for('user.dashboard'))
        conn = get_db_connection()
        stats = {
            'providers': conn.execute('SELECT COUNT(*) FROM providers').fetchone()[0],
            'completed': conn.execute("SELECT COUNT(*) FROM bookings WHERE status = 'completed'").fetchone()[0],
            'service_types': conn.execute(
                "SELECT COUNT(DISTINCT service_type) FROM providers WHERE service_type != 'general'").fetchone()[0],
        }
        type_counts = dict(conn.execute(
            'SELECT service_type, COUNT(*) FROM providers GROUP BY service_type').fetchall())
        latest_review = conn.execute('''
            SELECT r.rating, r.comment, u.first_name, u.last_name, p.business_name
            FROM reviews r JOIN users u ON r.user_id = u.id JOIN providers p ON r.provider_id = p.id
            WHERE r.rating >= 4 AND r.comment IS NOT NULL
            ORDER BY r.created_at DESC, r.id DESC LIMIT 1
        ''').fetchone()
        conn.close()
        return render_template('index.html', stats=stats, type_counts=type_counts,
                               latest_review=latest_review)

    @app.route('/healthz')
    def healthz():
        conn = get_db_connection()
        conn.execute('SELECT 1')
        conn.close()
        return {'status': 'ok'}

    @app.errorhandler(400)
    def bad_request(error):
        return render_template('400.html', message=getattr(error, 'description', None)), 400

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        return render_template('500.html'), 500

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=int(os.environ.get('PORT', 5000)),
                       debug=env_flag('FLASK_DEBUG', False))
