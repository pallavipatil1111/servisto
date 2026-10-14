from conftest import CLEANER, ELECTRICIAN, PLUMBER, Browser, provider_id

PROFILE = {'business_name': 'Jadhav Plumbing', 'service_type': 'Plumbing', 'description': 'Fast repairs',
           'experience_years': '9', 'license_number': 'MH-1', 'service_area': 'Pune, Wakad',
           'hourly_rate': '400', 'availability_status': 'available', 'phone': '9000000000',
           'address': 'Wakad, Pune'}


def test_dashboard_shows_counts_and_earnings(plumber):
    page = plumber.get('/provider/dashboard').get_data(as_text=True)
    assert 'Welcome back, Rahul' in page
    assert 'id="setup-banner"' not in page  # the demo profile is complete


def test_update_profile(plumber, db):
    response = plumber.post('/provider/profile', PROFILE)
    assert response.status_code == 302
    row = db.execute('SELECT * FROM providers WHERE id = ?', (provider_id(db, PLUMBER),)).fetchone()
    assert row['business_name'] == 'Jadhav Plumbing'
    assert row['service_type'] == 'plumbing'  # stored lower-case so search and icons match
    assert row['experience_years'] == 9 and row['hourly_rate'] == 400
    assert db.execute("SELECT address FROM users WHERE email = ?", (PLUMBER,)).fetchone()[0] == 'Wakad, Pune'


def test_profile_validation(plumber, db):
    for field, value in [('experience_years', '-1'), ('experience_years', 'ten'), ('hourly_rate', 'abc'),
                         ('availability_status', 'on-holiday'), ('business_name', ''), ('service_type', '')]:
        response = plumber.post('/provider/profile', {**PROFILE, field: value})
        assert response.status_code == 400, (field, value)
    assert db.execute('SELECT business_name FROM providers WHERE id = ?',
                      (provider_id(db, PLUMBER),)).fetchone()[0] == 'Jadhav Plumbing Works'


def test_add_and_toggle_a_service(plumber, db):
    response = plumber.post('/provider/services', {'service_name': 'Drain unblocking', 'base_price': '450',
                                                   'duration_hours': '1.5', 'description': 'Kitchen or bathroom'})
    assert response.status_code == 302
    service = db.execute("SELECT * FROM services WHERE service_name = 'Drain unblocking'").fetchone()
    assert service['base_price'] == 450 and service['is_active'] == 1

    result = plumber.fetch_post(f'/provider/service/{service["id"]}/toggle').get_json()
    assert result == {'success': True, 'is_active': False, 'message': 'Service deactivated successfully!'}
    assert plumber.fetch_post(f'/provider/service/{service["id"]}/toggle').get_json()['is_active'] is True


def test_service_validation(plumber, db):
    before = db.execute('SELECT COUNT(*) FROM services').fetchone()[0]
    for form in ({'service_name': '', 'base_price': '100'}, {'service_name': 'X', 'base_price': '0'},
                 {'service_name': 'X', 'base_price': 'free'}, {'service_name': 'X', 'base_price': '100',
                                                                'duration_hours': '30'}):
        assert plumber.post('/provider/services', form).status_code == 400, form
    assert db.execute('SELECT COUNT(*) FROM services').fetchone()[0] == before


def test_cannot_toggle_another_providers_service(plumber, db):
    other = db.execute('SELECT id FROM services WHERE provider_id = ?', (provider_id(db, CLEANER),)).fetchone()[0]
    assert plumber.fetch_post(f'/provider/service/{other}/toggle').status_code == 404
    assert db.execute('SELECT is_active FROM services WHERE id = ?', (other,)).fetchone()[0] == 1


def test_booking_life_cycle(plumber, db):
    pending = db.execute("SELECT id FROM bookings WHERE status = 'pending' AND provider_id = ?",
                         (provider_id(db, PLUMBER),)).fetchone()[0]
    url = f'/provider/booking/{pending}/update_status'

    # Can't jump straight from pending to completed.
    assert plumber.fetch_post(url, {'status': 'completed'}).status_code == 409
    assert plumber.fetch_post(url, {'status': 'confirmed'}).get_json()['new_status'] == 'confirmed'
    assert plumber.fetch_post(url, {'status': 'completed'}).get_json()['message'] == 'Service marked as completed!'
    # A completed job is final.
    assert plumber.fetch_post(url, {'status': 'cancelled'}).status_code == 409
    assert plumber.fetch_post(url, {'status': 'archived'}).status_code == 400
    assert db.execute('SELECT status FROM bookings WHERE id = ?', (pending,)).fetchone()[0] == 'completed'


def test_cannot_update_another_providers_booking(plumber, db):
    theirs = db.execute('SELECT id FROM bookings WHERE provider_id = ?',
                        (provider_id(db, ELECTRICIAN),)).fetchone()[0]
    assert plumber.fetch_post(f'/provider/booking/{theirs}/update_status',
                              {'status': 'cancelled'}).status_code == 404
    assert db.execute('SELECT status FROM bookings WHERE id = ?', (theirs,)).fetchone()[0] == 'confirmed'


def test_bookings_page_filters_and_sorts(plumber):
    page = plumber.get('/provider/bookings?status=pending').get_data(as_text=True)
    assert 'Bathroom fitting' in page and 'Tap and leak repair' not in page
    assert plumber.get('/provider/bookings?sort=customer').status_code == 200
    # An unknown sort value falls back to date order instead of reaching the SQL.
    assert plumber.get('/provider/bookings?sort=1;DROP TABLE bookings').status_code == 200


def test_reviews_page_and_reply(plumber, db):
    page = plumber.get('/provider/reviews').get_data(as_text=True)
    assert 'Came on time and fixed the leak' in page and 'Ananya Kulkarni' in page

    review_id = db.execute('SELECT id FROM reviews').fetchone()[0]
    response = plumber.post(f'/provider/review/{review_id}/respond', {'response': 'See you next time!'},
                            follow_redirects=True)
    assert 'Your reply has been posted' in response.get_data(as_text=True)
    assert db.execute('SELECT provider_response FROM reviews WHERE id = ?',
                      (review_id,)).fetchone()[0] == 'See you next time!'

    assert plumber.post(f'/provider/review/{review_id}/respond', {'response': '   '},
                        follow_redirects=True).status_code == 200
    assert db.execute('SELECT provider_response FROM reviews WHERE id = ?',
                      (review_id,)).fetchone()[0] == 'See you next time!'


def test_provider_cannot_reply_to_someone_elses_review(app, db):
    cleaner = Browser(app.test_client())
    cleaner.login(CLEANER)
    review_id = db.execute('SELECT id FROM reviews').fetchone()[0]
    response = cleaner.post(f'/provider/review/{review_id}/respond', {'response': 'Spam'}, follow_redirects=True)
    assert 'Review not found' in response.get_data(as_text=True)


def test_reviews_page_with_no_reviews(app):
    cleaner = Browser(app.test_client())
    cleaner.login(CLEANER)
    assert 'No Reviews Yet' in cleaner.get('/provider/reviews').get_data(as_text=True)


def test_availability(plumber, db):
    assert plumber.fetch_post('/provider/availability', {'availability_status': 'busy'}).get_json()['success']
    assert db.execute('SELECT availability_status FROM providers WHERE id = ?',
                      (provider_id(db, PLUMBER),)).fetchone()[0] == 'busy'
    assert plumber.fetch_post('/provider/availability', {'availability_status': 'asleep'}).status_code == 400
