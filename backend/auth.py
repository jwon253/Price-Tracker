import os

from flask import jsonify
from flask_login import LoginManager, UserMixin
from werkzeug.security import check_password_hash

login_manager = LoginManager()


class User(UserMixin):
    """There's only ever one account, so its id is a fixed string."""
    id = "admin"


@login_manager.user_loader
def load_user(user_id):
    return User() if user_id == "admin" else None


@login_manager.unauthorized_handler
def unauthorized():
    return jsonify({"error": "Login required"}), 401


def verify_credentials(username, password):
    if not username or not password:
        return False
    expected_username = os.environ["AUTH_USERNAME"]
    expected_hash = os.environ["AUTH_PASSWORD_HASH"]
    return username == expected_username and check_password_hash(expected_hash, password)
