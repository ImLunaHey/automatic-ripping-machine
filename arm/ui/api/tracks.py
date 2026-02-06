"""
Track API Endpoints

Endpoints for managing disc tracks.
"""

from flask import Blueprint, request

from arm.ui.api import (
    api_auth_required, make_response, error_response,
    paginate_query, track_to_dict, Track, db, desc
)

api = Blueprint('tracks', __name__, url_prefix='/tracks')


@api.route('', methods=['GET'])
@api_auth_required
def list_tracks():
    """
    List Tracks

    Retrieve a paginated list of all tracks with optional filtering.

    Query Parameters:
        - page (int): Page number (default: 1)
        - per_page (int): Items per page (default: 20, max: 100)
        - job_id (int): Filter by job ID
        - ripped (bool): Filter by rip status
        - main_feature (bool): Filter by main feature flag

    Returns:
        Paginated list of tracks
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    job_id = request.args.get('job_id', type=int)
    ripped = request.args.get('ripped')
    main_feature = request.args.get('main_feature')

    query = Track.query

    if job_id:
        query = query.filter_by(job_id=job_id)
    if ripped is not None:
        query = query.filter_by(ripped=ripped.lower() == 'true')
    if main_feature is not None:
        query = query.filter_by(main_feature=main_feature.lower() == 'true')

    query = query.order_by(desc(Track.track_id))
    tracks, pagination = paginate_query(query, page, per_page)

    return make_response({
        'tracks': [track_to_dict(t) for t in tracks],
        'pagination': pagination
    })


@api.route('/<int:track_id>', methods=['GET'])
@api_auth_required
def get_track(track_id):
    """
    Get Track Details

    Retrieve detailed information about a specific track.
    """
    track = Track.query.get(track_id)
    if not track:
        return error_response(f'Track with ID {track_id} not found', 404)
    return make_response(track_to_dict(track))


@api.route('/<int:track_id>', methods=['PATCH'])
@api_auth_required
def update_track(track_id):
    """
    Update Track

    Update properties of a specific track.

    Request Body:
        {
            "process": true,
            "error": "Error message"
        }
    """
    track = Track.query.get(track_id)
    if not track:
        return error_response(f'Track with ID {track_id} not found', 404)

    data = request.get_json()
    if not data:
        return error_response('Request body must be JSON', 400)

    try:
        if 'process' in data:
            track.process = bool(data['process'])
        if 'error' in data:
            track.error = str(data['error']) if data['error'] else None

        db.session.commit()
        return make_response(track_to_dict(track), 'Track updated successfully')
    except Exception as e:
        db.session.rollback()
        return error_response(f'Failed to update track: {str(e)}', 500)
