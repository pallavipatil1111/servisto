from datetime import date, timedelta

from conftest import CLEANER, ELECTRICIAN, PLUMBER, first_service, future, provider_id


def book(browser, pid, **overrides):
    form = {'service_date': future(), 'service_time': '10:00', 'address': '5 MG Road, Pune',
            'problem_description': 'Leaking pipe'}
    form.update(overrides)
    return browser.post(f'/user/book/{pid}', form)


def test_dashboard_lists_recent_bookings(customer):
    page = customer.get('/user/dashboard').get_data(as_text=True)
    assert 'Jadhav Plumbing Works' in page and 'Bathroom fitting' in page


def test_search_filters(customer, db):
    page = customer.get('/user/search').get_data(as_text=True)
    for name in ('Jadhav Plumbing Works', 'BrightSpark Electricals', 'Sparkle Home Cleaning'):
        assert name in page

    page = customer.get('/user/search?service_type=electrical').get_data(as_text=True)
    assert 'BrightSpark Electricals' in page and 'Jadhav Plumbing Works' not in page

    page = customer.get('/user/search?location=Baner').get_data(as_text=True)
    assert 'BrightSpark Electricals' in page and 'Sparkle Home Cleaning' not in page

    page = customer.get('/user/search?min_rating=4').get_data(as_text=True)
    assert 'Jadhav Plumbing Works' in page and 'BrightSpark Electricals' not in page


def test_search_hides_unavailable_providers_and_those_without_services(customer, db):
    db.execute("UPDATE providers SET availability_status = 'busy' WHERE id = ?", (provider_id(db, CLEANER),))
    db.execute('UPDATE services SET is_active = 0 WHERE provider_id = ?', (provider_id(db, ELECTRICIAN),))
    db.commit()
    page = customer.get('/user/search').get_data(as_text=True)
    assert 'Sparkle Home Cleaning' not in page
    assert 'BrightSpark Electricals' not in page
    assert 'Jadhav Plumbing Works' in page


def test_search_treats_input_as_text_not_sql(customer):
    response = customer.get("/user/search?location=' OR 1=1 --&service_type=%25")
    assert response.status_code == 200
    assert 'Jadhav Plumbing Works' not in response.get_data(as_text=True)


def test_provider_page_shows_services_reviews_and_replies(customer, db):
    pid = provider_id(db, PLUMBER)
    page = customer.get(f'/user/provider/{pid}').get_data(as_text=True)
    assert 'Tap and leak repair' in page and '₹299' in page
    assert 'Came on time and fixed the leak' in page
    assert 'Thank you, Ananya!' in page  # the provider's reply
    assert customer.get('/user/provider/999').location.endswith('/user/search')


def test_booking_a_service(customer, db):
    pid = provider_id(db, PLUMBER)
    service = first_service(db, pid)
    response = book(customer, pid, service_id=service['id'])
    assert response.status_code == 302 and response.location.endswith('/user/bookings')

    row = db.execute('SELECT * FROM bookings ORDER BY id DESC LIMIT 1').fetchone()
    assert row['status'] == 'pending'
    assert row['total_amount'] == service['base_price']  # price comes from the database, not the form
    assert str(row['service_date']) == future()

    page = customer.get('/user/bookings').get_data(as_text=True)
    assert 'Leaking pipe' in page and '10:00 AM' in page


def test_booking_page_preselects_a_service_and_lists_taken_slots(customer, db):
    pid = provider_id(db, PLUMBER)
    bathroom = db.execute("SELECT id FROM services WHERE service_name = 'Bathroom fitting'").fetchone()[0]
    page = customer.get(f'/user/book/{pid}?service_id={bathroom}').get_data(as_text=True)
    radio = page.split(f'name="service_id" value="{bathroom}"')[1].split('>')[0]
    assert 'checked' in radio
    # The seeded pending booking is 4 days ahead at 11:00.
    taken_day = (date.today() + timedelta(days=4)).isoformat()
    assert f'"{taken_day}": ["11:00"]' in page


def test_booking_validation(customer, db):
    pid = provider_id(db, PLUMBER)
    service_id = first_service(db, pid)['id']
    other_providers_service = first_service(db, provider_id(db, CLEANER))['id']
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    cases = [
        ({'service_id': service_id, 'address': ''}, 'fill in all required fields'),
        ({'service_id': service_id, 'service_date': yesterday}, 'today or a future date'),
        ({'service_id': service_id, 'service_date': '2026-02-31'}, 'valid date'),
        ({'service_id': service_id, 'service_time': '03:00'}, 'listed times'),
        ({'service_id': other_providers_service}, 'Invalid service'),
        ({'service_id': 99999}, 'Invalid service'),
    ]
    before = db.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]
    for overrides, message in cases:
        response = book(customer, pid, **overrides)
        assert response.status_code == 400, overrides
        assert message in response.get_data(as_text=True), overrides
    assert db.execute('SELECT COUNT(*) FROM bookings').fetchone()[0] == before


def test_booking_an_inactive_service_is_refused(customer, db):
    pid = provider_id(db, PLUMBER)
    service = first_service(db, pid)
    db.execute('UPDATE services SET is_active = 0 WHERE id = ?', (service['id'],))
    db.commit()
    assert book(customer, pid, service_id=service['id']).status_code == 400


def test_cannot_book_a_provider_who_is_not_available(customer, db):
    pid = provider_id(db, PLUMBER)
    db.execute("UPDATE providers SET availability_status = 'unavailable' WHERE id = ?", (pid,))
    db.commit()
    response = book(customer, pid, service_id=first_service(db, pid)['id'])
    assert response.status_code == 409
    assert 'not taking new bookings' in response.get_data(as_text=True)


def test_the_same_slot_cannot_be_booked_twice(customer, db):
    pid = provider_id(db, PLUMBER)
    service_id = first_service(db, pid)['id']
    assert book(customer, pid, service_id=service_id, service_time='15:00').status_code == 302
    second = book(customer, pid, service_id=service_id, service_time='15:00')
    assert second.status_code == 409
    assert 'just booked' in second.get_data(as_text=True)

    # Once the first booking is cancelled the slot is free again.
    booking_id = db.execute("SELECT id FROM bookings WHERE service_time = '15:00'").fetchone()[0]
    customer.post(f'/user/booking/{booking_id}/cancel')
    assert book(customer, pid, service_id=service_id, service_time='15:00').status_code == 302


def test_bookings_filter_by_status(customer):
    completed = customer.get('/user/bookings?status=completed').get_data(as_text=True)
    assert 'Sparkle Home Cleaning' in completed and 'BrightSpark Electricals' not in completed
    everything = customer.get('/user/bookings?status=nonsense').get_data(as_text=True)
    assert 'BrightSpark Electricals' in everything


def test_cancel_booking(customer, db):
    booking_id = db.execute("SELECT id FROM bookings WHERE status = 'pending'").fetchone()[0]
    assert customer.get(f'/user/booking/{booking_id}/cancel').status_code == 405  # no GET side effects
    response = customer.post(f'/user/booking/{booking_id}/cancel', follow_redirects=True)
    assert 'Booking cancelled successfully' in response.get_data(as_text=True)
    assert db.execute('SELECT status FROM bookings WHERE id = ?', (booking_id,)).fetchone()[0] == 'cancelled'


def test_completed_booking_cannot_be_cancelled(customer, db):
    booking_id = db.execute("SELECT id FROM bookings WHERE status = 'completed'").fetchone()[0]
    response = customer.post(f'/user/booking/{booking_id}/cancel', follow_redirects=True)
    assert 'cannot be cancelled' in response.get_data(as_text=True)
    assert db.execute('SELECT status FROM bookings WHERE id = ?', (booking_id,)).fetchone()[0] == 'completed'


def test_review_a_completed_booking(customer, db):
    cleaner = provider_id(db, CLEANER)
    booking_id = db.execute('SELECT id FROM bookings WHERE provider_id = ?', (cleaner,)).fetchone()[0]

    page = customer.get(f'/user/review/{booking_id}')
    assert page.status_code == 200
    assert 'Sparkle Home Cleaning' in page.get_data(as_text=True)

    response = customer.post(f'/user/review/{booking_id}', {'rating': '4', 'comment': 'Spotless kitchen.'})
    assert response.status_code == 302
    assert db.execute('SELECT average_rating FROM providers WHERE id = ?', (cleaner,)).fetchone()[0] == 4.0

    again = customer.post(f'/user/review/{booking_id}', {'rating': '1'}, follow_redirects=True)
    assert 'already reviewed' in again.get_data(as_text=True)
    assert db.execute('SELECT COUNT(*) FROM reviews WHERE booking_id = ?', (booking_id,)).fetchone()[0] == 1


def test_review_rules(customer, db):
    cleaner = provider_id(db, CLEANER)
    completed = db.execute('SELECT id FROM bookings WHERE provider_id = ?', (cleaner,)).fetchone()[0]
    for rating in ('0', '6', 'abc', ''):
        assert customer.post(f'/user/review/{completed}', {'rating': rating}).status_code == 400

    not_done = db.execute("SELECT id FROM bookings WHERE status = 'confirmed'").fetchone()[0]
    response = customer.post(f'/user/review/{not_done}', {'rating': '5'}, follow_redirects=True)
    assert 'only review completed bookings' in response.get_data(as_text=True)


def test_customers_cannot_touch_other_customers_bookings(app, browser, db):
    from conftest import Browser
    other = Browser(app.test_client())
    other.post('/register', {'first_name': 'Om', 'last_name': 'Rao', 'email': 'om@example.com',
                             'password': 'secret123', 'confirm_password': 'secret123', 'user_type': 'user'})
    other.login('om@example.com', 'secret123')

    pending = db.execute("SELECT id FROM bookings WHERE status = 'pending'").fetchone()[0]
    completed = db.execute("SELECT id FROM bookings WHERE status = 'completed' ORDER BY id DESC").fetchone()[0]
    assert 'Booking not found' in other.post(f'/user/booking/{pending}/cancel',
                                             follow_redirects=True).get_data(as_text=True)
    assert 'Booking not found' in other.post(f'/user/review/{completed}', {'rating': '1'},
                                             follow_redirects=True).get_data(as_text=True)
    assert db.execute('SELECT status FROM bookings WHERE id = ?', (pending,)).fetchone()[0] == 'pending'
    assert 'Ananya' not in other.get('/user/bookings').get_data(as_text=True)


def test_search_sorting(customer):
    page = customer.get('/user/search?sort=price').get_data(as_text=True)
    order = [page.index(name) for name in ('Sparkle Home Cleaning', 'Jadhav Plumbing Works', 'BrightSpark Electricals')]
    assert order == sorted(order)  # ₹300, ₹350, ₹400 an hour

    page = customer.get('/user/search?sort=reviews').get_data(as_text=True)
    assert page.index('Jadhav Plumbing Works') < page.index('Sparkle Home Cleaning')
    assert '(1 review)' in page and 'Tap and leak repair · ₹299' in page

    assert customer.get('/user/search?sort=;DROP TABLE users').status_code == 200
