import os
import re
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import connect  # noqa: E402
from main import create_app  # noqa: E402

PASSWORD = 'demo1234'
CUSTOMER = 'customer@servisto.demo'
PLUMBER = 'plumber@servisto.demo'
ELECTRICIAN = 'electrician@servisto.demo'
CLEANER = 'cleaner@servisto.demo'


@pytest.fixture
def app(tmp_path):
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'test-secret',
        'DATABASE': str(tmp_path / 'test.db'),
        'SEED_DEMO_DATA': True,
    })
    yield app


@pytest.fixture
def db(app):
    """A direct connection, for checking what the app stored."""
    conn = connect(app.config['DATABASE'])
    yield conn
    conn.close()


class Browser:
    """A test client that handles the CSRF token like a real browser form would."""

    def __init__(self, client):
        self.client = client

    def token(self):
        """Read the token from a rendered page, as the browser would."""
        page = self.client.get('/login', follow_redirects=True).get_data(as_text=True)
        match = re.search(r'name="csrf-token" content="([^"]+)"', page)
        assert match, 'csrf meta tag missing'
        return match.group(1)

    def get(self, url, **kwargs):
        return self.client.get(url, **kwargs)

    def post(self, url, data=None, csrf=True, **kwargs):
        data = dict(data or {})
        if csrf:
            data['csrf_token'] = self.token()
        return self.client.post(url, data=data, **kwargs)

    def fetch_post(self, url, data=None, csrf=True):
        """Like the pages' fetch() calls: token in a header, not in the form."""
        headers = {'X-CSRFToken': self.token()} if csrf else {}
        return self.client.post(url, data=data or {}, headers=headers)

    def login(self, email, password=PASSWORD):
        return self.post('/login', {'email': email, 'password': password})

    def logout(self):
        return self.post('/logout')


@pytest.fixture
def browser(app):
    return Browser(app.test_client())


@pytest.fixture
def customer(app):
    b = Browser(app.test_client())
    assert b.login(CUSTOMER).status_code == 302
    return b


@pytest.fixture
def plumber(app):
    b = Browser(app.test_client())
    assert b.login(PLUMBER).status_code == 302
    return b


def provider_id(db, email):
    return db.execute('SELECT p.id FROM providers p JOIN users u ON u.id = p.user_id WHERE u.email = ?',
                      (email,)).fetchone()[0]


def first_service(db, pid):
    return db.execute('SELECT * FROM services WHERE provider_id = ? ORDER BY id', (pid,)).fetchone()


def future(days=3):
    return (date.today() + timedelta(days=days)).isoformat()
