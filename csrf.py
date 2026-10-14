"""Small CSRF protection, so no extra package is needed.

Every session gets a random token. Each form sends it back in a hidden
``csrf_token`` field and each ``fetch`` call sends it in an ``X-CSRFToken``
header. Any POST without the matching token is refused with 400.
"""
import hmac
import secrets

from flask import abort, request, session

SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}


def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_urlsafe(32)
    return session['_csrf_token']


def init_csrf(app):
    app.jinja_env.globals['csrf_token'] = generate_csrf_token

    @app.before_request
    def check_csrf():
        if not app.config.get('CSRF_ENABLED', True) or request.method in SAFE_METHODS:
            return
        expected = session.get('_csrf_token')
        sent = request.form.get('csrf_token') or request.headers.get('X-CSRFToken')
        if not expected or not sent or not hmac.compare_digest(expected, sent):
            abort(400, description='The form expired or was sent from another site. '
                                   'Please reload the page and try again.')
