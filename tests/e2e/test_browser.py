"""End-to-end tests in a real Chromium browser (Playwright).

They start the app on a free port with its own database and click through
the pages the way a customer and a provider would. Run with:

    python -m playwright install chromium
    pytest tests/e2e
"""
import re
import socket
import threading
from datetime import date, timedelta

import pytest

playwright_api = pytest.importorskip('playwright.sync_api')
from playwright.sync_api import expect, sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from main import create_app  # noqa: E402

PASSWORD = 'demo1234'
pytestmark = pytest.mark.e2e


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture(scope='module')
def base_url(tmp_path_factory):
    app = create_app({'SECRET_KEY': 'e2e', 'DATABASE': str(tmp_path_factory.mktemp('e2e') / 'e2e.db')})
    server = make_server('127.0.0.1', free_port(), app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def new_page(browser, base_url):
    contexts = []

    def make(width=1280, height=900):
        context = browser.new_context(base_url=base_url, viewport={'width': width, 'height': height})
        contexts.append(context)
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda error: page.errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())  # "Are you sure?" confirms
        return page

    yield make
    for context in contexts:
        context.close()


def log_in(page, email, password=PASSWORD):
    page.goto('/login')
    page.fill('#email', email)
    page.fill('#password', password)
    page.click('form button[type=submit]')
    expect(page.locator('#logout')).to_be_attached()


def test_customer_finds_and_books_a_provider(new_page):
    page = new_page()
    log_in(page, 'customer@servisto.demo')

    page.goto('/user/search')
    page.select_option('select[name=service_type]', 'electrical')
    page.locator('form[method=GET] button[type=submit]').click()
    expect(page.get_by_text('BrightSpark Electricals')).to_be_visible()
    expect(page.get_by_text('Jadhav Plumbing Works')).to_have_count(0)

    page.get_by_role('link', name=re.compile('View Profile|View Details', re.I)).first.click()
    expect(page.get_by_role('heading', name='BrightSpark Electricals')).to_be_visible()
    page.locator('a', has_text='Book this').nth(1).click()  # "House wiring check"

    # The chosen service is preselected and the summary follows it.
    expect(page.locator('#selected-service')).to_contain_text('House wiring check')
    page.locator('.service-option', has_text='Fan or light installation').click()
    expect(page.locator('#total-price')).to_have_text('₹249')

    day = (date.today() + timedelta(days=6)).isoformat()
    page.fill('#service_date', day)
    page.select_option('#service_time', '14:00')
    page.fill('#problem_description', 'Install a new ceiling fan in the hall.')
    page.check('#terms_agreement')
    page.click('#booking-form button[type=submit]')

    expect(page).to_have_url(re.compile('/user/bookings'))
    expect(page.get_by_text('Booking request sent successfully')).to_be_visible()
    expect(page.get_by_text('Install a new ceiling fan in the hall.')).to_be_visible()

    # Booking the same provider again: that slot is now greyed out.
    page.goto('/user/book/2')
    page.fill('#service_date', day)
    page.dispatch_event('#service_date', 'change')
    expect(page.locator('#service_time option[value="14:00"]')).to_be_disabled()
    expect(page.locator('#service_time option[value="15:00"]')).to_be_enabled()
    assert page.errors == []


def test_provider_confirms_completes_and_replies_to_a_review(new_page):
    provider = new_page()
    log_in(provider, 'plumber@servisto.demo')
    provider.goto('/provider/bookings?status=pending')
    card = provider.locator('div.rounded-2xl', has_text='Bathroom fitting').first
    card.get_by_role('button', name='Confirm').click()
    provider.click('#confirm-status-update')  # the fetch() call carries the CSRF header
    expect(provider.get_by_text('Booking confirmed!')).to_be_visible()

    provider.goto('/provider/bookings?status=confirmed')
    provider.locator('div.rounded-2xl', has_text='Bathroom fitting').first \
        .get_by_role('button', name='Mark Complete').click()
    provider.click('#confirm-status-update')
    expect(provider.get_by_text('Service marked as completed!')).to_be_visible()

    # The customer can now review it.
    customer = new_page()
    log_in(customer, 'customer@servisto.demo')
    customer.goto('/user/bookings?status=completed')
    customer.locator('div.rounded-2xl', has_text='Bathroom fitting').get_by_role('link', name='Leave Review').click()
    customer.locator('.star[data-rating="4"]').click()
    customer.fill('#comment', 'Neat work on the geyser connection.')
    customer.locator('form button[type=submit]').last.click()
    expect(customer.get_by_text('Thank you for your review!')).to_be_visible()

    # The provider replies, and the reply shows on the public profile.
    provider.goto('/provider/reviews')
    review = provider.locator('div.rounded-2xl', has_text='Neat work on the geyser connection.')
    review.locator('summary').click()
    review.locator('textarea[name=response]').fill('Thanks! Call us any time.')
    review.get_by_role('button', name='Post reply').click()
    expect(provider.get_by_text('Your reply has been posted.')).to_be_visible()

    customer.goto('/user/provider/1')
    expect(customer.get_by_text('Thanks! Call us any time.')).to_be_visible()
    assert provider.errors == [] and customer.errors == []


def test_customer_cancels_a_booking(new_page):
    page = new_page()
    log_in(page, 'customer@servisto.demo')
    page.goto('/user/bookings?status=confirmed')
    page.locator('[data-cancel]').first.click()
    expect(page.get_by_text('Booking cancelled successfully.')).to_be_visible()


def test_new_provider_sets_up_and_appears_in_search(new_page):
    page = new_page()
    page.goto('/register?type=provider')
    page.fill('#first_name', 'Meera')
    page.fill('#last_name', 'Joshi')
    page.fill('#email', 'meera@example.com')
    page.fill('#password', 'garden123')
    page.fill('#confirm_password', 'garden123')
    page.locator('form button[type=submit]').click()
    expect(page.get_by_text('Registration successful')).to_be_visible()

    log_in(page, 'meera@example.com', 'garden123')
    expect(page.locator('#setup-banner')).to_be_visible()

    page.goto('/provider/profile')
    page.fill('#business_name', 'Green Thumb Gardens')
    page.select_option('#service_type', 'gardening')
    page.fill('#service_area', 'Pune, Aundh')
    page.fill('#hourly_rate', '300')
    page.locator('form button[type=submit]').last.click()
    expect(page.get_by_text('Profile updated successfully!')).to_be_visible()

    page.goto('/provider/services')
    page.locator('button', has_text=re.compile('Add (New )?Service', re.I)).first.click()
    page.fill('#service_name', 'Lawn mowing')
    page.fill('#base_price', '499')
    page.locator('#add-service-modal button[type=submit]').click()
    expect(page.get_by_text('Service added successfully!')).to_be_visible()

    customer = new_page()
    log_in(customer, 'customer@servisto.demo')
    customer.goto('/user/search?location=Aundh')
    expect(customer.get_by_text('Green Thumb Gardens')).to_be_visible()

    # Turning the only service off hides the provider again (toggle uses fetch()).
    switch = page.get_by_role('switch', name='Offer Lawn mowing')
    switch.click()
    expect(page.get_by_text('Service deactivated successfully!')).to_be_visible()
    expect(switch).to_have_attribute('aria-checked', 'false')
    customer.reload()
    expect(customer.get_by_text('Green Thumb Gardens')).to_have_count(0)
    assert page.errors == [] and customer.errors == []


def test_availability_toggle(new_page):
    page = new_page()
    log_in(page, 'cleaner@servisto.demo')
    page.goto('/provider/dashboard')
    page.click('.availability-btn[data-status="busy"]')
    expect(page.get_by_text('Availability updated to busy!')).to_be_visible()
    page.reload()
    expect(page.get_by_text('Busy', exact=True).first).to_be_visible()


def test_phone_layout_and_menu(new_page):
    page = new_page(width=390, height=844)
    log_in(page, 'customer@servisto.demo')
    for url in ('/user/dashboard', '/user/search', '/user/provider/1', '/user/book/1', '/user/bookings'):
        page.goto(url)
        width = page.evaluate('document.documentElement.scrollWidth')
        assert width <= 390, f'{url} scrolls sideways ({width}px)'

    # The desktop links are hidden on a phone; the account menu has them instead.
    page.click('[data-user-menu] button')
    page.get_by_role('link', name='My Bookings').last.click()
    expect(page).to_have_url(re.compile('/user/bookings'))
    assert page.errors == []
