from conftest import CUSTOMER, PLUMBER


def register(browser, **overrides):
    form = {'first_name': 'Priya', 'last_name': 'Shah', 'email': 'priya@example.com', 'phone': '9876543210',
            'password': 'secret123', 'confirm_password': 'secret123', 'user_type': 'user'}
    form.update(overrides)
    return browser.post('/register', form)


def test_home_page_shows_real_numbers(browser):
    page = browser.get('/').get_data(as_text=True)
    assert 'data-stat="providers">3<' in page
    assert '500+' not in page and 'John Smith' not in page
    assert 'Came on time and fixed the leak' in page  # latest real review


def test_register_customer_then_log_in(browser, db):
    response = register(browser)
    assert response.status_code == 302 and response.location.endswith('/login')
    row = db.execute("SELECT * FROM users WHERE email = 'priya@example.com'").fetchone()
    assert row['user_type'] == 'user'
    assert row['password_hash'] != 'secret123'  # stored hashed

    response = browser.login('priya@example.com', 'secret123')
    assert response.location.endswith('/user/dashboard')


def test_register_provider_creates_provider_profile(browser, db):
    register(browser, email='Kiran@Example.com ', user_type='provider')
    user = db.execute("SELECT * FROM users WHERE email = 'kiran@example.com'").fetchone()
    assert user is not None  # email is trimmed and lower-cased
    provider = db.execute('SELECT * FROM providers WHERE user_id = ?', (user['id'],)).fetchone()
    assert provider['business_name'] == 'Priya Shah'
    assert browser.login('kiran@example.com', 'secret123').location.endswith('/provider/dashboard')


def test_new_provider_dashboard_asks_to_finish_setup(browser):
    register(browser, email='new@example.com', user_type='provider')
    browser.login('new@example.com', 'secret123')
    assert 'id="setup-banner"' in browser.get('/provider/dashboard').get_data(as_text=True)


def test_register_rejects_bad_input(browser, db):
    cases = [
        ({'email': CUSTOMER}, 'Email already registered'),
        ({'confirm_password': 'different1'}, 'Passwords do not match'),
        ({'password': 'short', 'confirm_password': 'short'}, 'at least 8 characters'),
        ({'email': 'not-an-email'}, 'valid email'),
        ({'user_type': 'admin'}, 'customer or a service provider'),
        ({'first_name': ''}, 'first and last name'),
    ]
    for overrides, message in cases:
        response = register(browser, **overrides)
        assert response.status_code == 400, overrides
        assert message in response.get_data(as_text=True), overrides
    assert db.execute("SELECT COUNT(*) FROM users WHERE email = 'priya@example.com'").fetchone()[0] == 0


def test_register_keeps_typed_values_after_an_error(browser):
    page = register(browser, confirm_password='nope12345').get_data(as_text=True)
    assert 'value="Priya"' in page and 'value="priya@example.com"' in page


def test_login_failure_gives_one_generic_message(browser):
    wrong_password = browser.login(CUSTOMER, 'wrong-password')
    unknown_email = browser.login('nobody@example.com')
    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
        assert 'Invalid email or password' in response.get_data(as_text=True)


def test_login_follows_only_local_next_links(browser):
    response = browser.post('/login?next=/user/bookings', {'email': CUSTOMER, 'password': 'demo1234'})
    assert response.location == '/user/bookings'
    browser.logout()
    response = browser.post('/login?next=https://evil.example/', {'email': CUSTOMER, 'password': 'demo1234'})
    assert response.location.endswith('/user/dashboard')


def test_logout_needs_post_and_ends_the_session(customer):
    assert customer.get('/logout').status_code == 405
    assert customer.logout().status_code == 302
    assert customer.get('/user/dashboard').location.startswith('/login')


def test_pages_need_login(browser):
    for url in ('/user/dashboard', '/user/search', '/user/bookings', '/provider/dashboard', '/provider/reviews'):
        response = browser.get(url)
        assert response.status_code == 302 and response.location.startswith('/login'), url


def test_customers_and_providers_stay_in_their_own_area(customer, plumber):
    assert customer.get('/provider/dashboard').location.endswith('/user/dashboard')
    assert plumber.get('/user/search').location.endswith('/provider/dashboard')
    assert customer.fetch_post('/provider/availability', {'availability_status': 'busy'}).status_code == 403


def test_logged_in_users_are_sent_to_their_dashboard(customer, plumber):
    assert customer.get('/').location.endswith('/user/dashboard')
    assert plumber.get('/login').location.endswith('/provider/dashboard')


def test_health_check_and_error_pages(browser):
    assert browser.get('/healthz').get_json() == {'status': 'ok'}
    response = browser.get('/no-such-page')
    assert response.status_code == 404 and 'Servisto' in response.get_data(as_text=True)


def test_seed_runs_only_on_an_empty_database(app, db):
    from seed import seed_demo_data
    assert seed_demo_data(app.config['DATABASE']) is False
    assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 4
    assert db.execute("SELECT COUNT(*) FROM users WHERE email = ?", (PLUMBER,)).fetchone()[0] == 1
