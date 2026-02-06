"""
Notifications API Endpoints

Endpoints for managing ARM notifications.
"""

from flask import Blueprint, request
from datetime import datetime

from arm.ui.api import (
    api_auth_required, make_response, error_response,
    paginate_query, Notifications, db, desc
)

api = Blueprint('notifications', __name__, url_prefix='/notifications')


@api.route('', methods=['GET'])
@api_auth_required
def list_notifications():
    """
    List Notifications

    Retrieve notifications with optional filtering.

    Query Parameters:
        - page (int): Page number (default: 1)
        - per_page (int): Items per page (default: 20, max: 100)
        - seen (bool): Filter by seen status
        - limit (int): Limit to N most recent notifications
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    seen_filter = request.args.get('seen')
    limit = request.args.get('limit', type=int)

    query = Notifications.query

    if seen_filter is not None:
        seen = seen_filter.lower() == 'true'
        query = query.filter_by(seen=seen)

    if limit:
        query = query.limit(limit)

    query = query.order_by(desc(Notifications.trigger_time))

    if limit:
        notifications = query.all()
        pagination = None
    else:
        notifications, pagination = paginate_query(query, page, per_page)

    return make_response({
        'notifications': [n.get_d() for n in notifications],
        'pagination': pagination
    })


@api.route('/unread', methods=['GET'])
@api_auth_required
def list_unread_notifications():
    """
    List Unread Notifications

    Retrieve all unread (unseen) notifications.
    """
    notifications = Notifications.query.filter_by(seen=False).order_by(
        desc(Notifications.trigger_time)
    ).all()

    return make_response({
        'notifications': [n.get_d() for n in notifications],
        'count': len(notifications)
    })


@api.route('/<int:notification_id>/read', methods=['POST'])
@api_auth_required
def mark_notification_read(notification_id):
    """
    Mark Notification as Read

    Mark a specific notification as seen/read.
    """
    notification = Notifications.query.get(notification_id)
    if not notification:
        return error_response(f'Notification with ID {notification_id} not found', 404)

    notification.seen = True
    notification.dismiss_time = datetime.now()
    db.session.commit()

    return make_response(None, 'Notification marked as read')


@api.route('/read-all', methods=['POST'])
@api_auth_required
def mark_all_notifications_read():
    """
    Mark All Notifications as Read

    Mark all unread notifications as seen.
    """
    count = Notifications.query.filter_by(seen=False).update({
        'seen': True,
        'dismiss_time': datetime.now()
    })
    db.session.commit()

    return make_response(None, f'{count} notifications marked as read')
