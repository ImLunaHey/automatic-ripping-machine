"""
User API Endpoints

Endpoints for user management and authentication.
"""

from flask import Blueprint, request

from arm.ui.api import api_auth_required, make_response, error_response, current_user, db, User, bcrypt, g

api = Blueprint('user', __name__, url_prefix='/user')


@api.route('/status', methods=['GET'])
@api_auth_required
def get_user_status():
    """
    Get Current User Status

    Get information about the currently authenticated user.
    """
    user = g.user if hasattr(g, 'user') and g.user != 'api_key_auth' else current_user

    if user and user.is_authenticated:
        return make_response({
            'authenticated': True,
            'email': user.email,
            'user_id': user.user_id
        })

    return make_response({
        'authenticated': True,
        'method': 'api_key',
        'email': None
    })


@api.route('/password', methods=['POST'])
@api_auth_required
def change_password():
    """
    Change Password

    Change the admin password.

    Request Body:
        {
            "old_password": "current_password",
            "new_password": "new_password"
        }
    """
    data = request.get_json()
    if not data or 'old_password' not in data or 'new_password' not in data:
        return error_response('old_password and new_password are required', 400)

    user = User.query.first()
    if not user:
        return error_response('No user found', 404)

    try:
        old_pw = data['old_password'].strip().encode('utf-8')
        new_pw = data['new_password'].strip().encode('utf-8')

        login_hashed = bcrypt.hashpw(old_pw, user.hash)
        if login_hashed != user.password:
            return error_response('Current password is incorrect', 401)

        hashed = bcrypt.gensalt()
        user.password = bcrypt.hashpw(new_pw, hashed)
        user.hash = hashed
        db.session.commit()

        return make_response(None, 'Password updated successfully. Please log in again.')
    except Exception as e:
        db.session.rollback()
        return error_response(f'Failed to change password: {str(e)}', 500)
