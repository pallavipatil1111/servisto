"""CSRF, configuration and output escaping."""
import os

from conftest import CUSTOMER, PLUMBER, first_service, future, provider_id
from main import create_app, format_inr, format_time12


def test_forms_without_the_csrf_token_are_refused(customer, db):
    pending = db.execute("SELECT id FROM bookings WHERE status = 'pending'").fetchone()[0]
    response = customer.post(f'/user/booking/{pending}/cancel', csrf=False)
    assert response.status_code == 400
    assert db.execute('SELECT status FROM bookings WHERE id = ?', (pending,)).fetchone()[0] == 'pending'


def test_a_wrong_csrf_token_is_refused(customer):
    response = customer.client.post('/logout', data={'csrf_token': 'guess'})
    assert response.status_code == 400


def test_login_form_also_needs_the_token(browser):
    assert browser.post('/login', {'email': CUSTOMER, 'password': 'demo1234'}, csrf=False).status_code == 400


def test_fetch_calls_without_the_header_are_refused(plumber, db):
    assert plumber.fetch_post('/provider/availability', {'availability_status': 'busy'}, csrf=False).status_code == 400
    assert db.execute('SELECT availability_status FROM providers WHERE id = ?',
                      (provider_id(db, PLUMBER),)).fetchone()[0] == 'available'


def test_every_post_form_in_the_templates_carries_a_token():
    import glob
    import re
    root = os.path.join(os.path.dirname(__file__), '..', 'templates')
    for path in glob.glob(os.path.join(root, '**', '*.html'), recursive=True):
        html = open(path, encoding='utf-8').read()
        for form in re.findall(r'<form\b[^>]*method="POST"[^>]*>(.*?)</form>', html, re.S | re.I):
            assert 'csrf_token()' in form, path


def test_user_input_is_escaped(customer, db):
    pid = provider_id(db, PLUMBER)
    customer.post(f'/user/book/{pid}', {'service_id': first_service(db, pid)['id'], 'service_date': future(),
                                        'service_time': '16:00', 'address': 'Pune',
                                        'problem_description': '<script>alert(1)</script>'})
    page = customer.get('/user/bookings').get_data(as_text=True)
    assert '<script>alert(1)</script>' not in page
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page


def test_session_cookie_flags(customer):
    cookie = customer.client.get_cookie('session')
    assert cookie is not None and cookie.http_only


def test_settings_come_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'from-env')
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'env.db'))
    monkeypatch.setenv('SEED_DEMO_DATA', 'false')
    app = create_app()
    assert app.config['SECRET_KEY'] == 'from-env'
    assert app.config['DATABASE'] == str(tmp_path / 'env.db')
    assert not app.debug
    from database import connect
    conn = connect(app.config['DATABASE'])
    assert conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0  # no demo data
    conn.close()


def test_no_debug_routes():
    app = create_app({'DATABASE': ':memory:', 'SEED_DEMO_DATA': False, 'SECRET_KEY': 'x'})
    assert not [rule.rule for rule in app.url_map.iter_rules() if rule.rule.startswith('/debug')]


def test_rupee_and_time_formatting():
    assert format_inr(299) == '₹299'
    assert format_inr(125000) == '₹1,25,000'
    assert format_inr(12345678.5) == '₹1,23,45,678.50'
    assert format_inr(None) == '₹0'
    assert format_time12('17:00') == '5:00 PM'
    assert format_time12('09:00') == '9:00 AM'
    assert format_time12('09:00 AM') == '09:00 AM'
