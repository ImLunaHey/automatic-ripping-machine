"""
History API Endpoints

Endpoints for viewing completed/failed jobs.
"""

from flask import Blueprint, request

from arm.ui.api import (
    api_auth_required, make_response, error_response,
    paginate_query, Job, db, desc
)

api = Blueprint('history', __name__, url_prefix='/history')


@api.route('', methods=['GET'])
@api_auth_required
def list_history():
    """
    List Job History

    Retrieve completed jobs with pagination.

    Query Parameters:
        - page (int): Page number (default: 1)
        - per_page (int): Items per page (default: 20, max: 100)
        - status (str): Filter by status (success, fail)
        - disctype (str): Filter by disc type
        - video_type (str): Filter by video type
        - search (str): Search in title
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status_filter = request.args.get('status')
    disctype_filter = request.args.get('disctype')
    video_type_filter = request.args.get('video_type')
    search_query = request.args.get('search')

    query = Job.query.filter(Job.finished)

    if status_filter in ['success', 'fail']:
        query = query.filter_by(status=status_filter)
    if disctype_filter:
        query = query.filter_by(disctype=disctype_filter)
    if video_type_filter:
        query = query.filter_by(video_type=video_type_filter)
    if search_query:
        search_term = f"%{search_query}%"
        query = query.filter(Job.title.ilike(search_term))

    query = query.order_by(desc(Job.job_id))
    jobs, pagination = paginate_query(query, page, per_page)

    history_items = []
    for job in jobs:
        history_items.append({
            'job_id': job.job_id,
            'title': job.title,
            'year': job.year,
            'status': job.status,
            'disctype': job.disctype,
            'video_type': job.video_type,
            'label': job.label,
            'start_time': job.start_time.isoformat() if job.start_time else None,
            'stop_time': job.stop_time.isoformat() if job.stop_time else None,
            'job_length': job.job_length
        })

    return make_response({
        'history': history_items,
        'pagination': pagination
    })


@api.route('/statistics', methods=['GET'])
@api_auth_required
def history_statistics():
    """
    Get History Statistics

    Retrieve aggregated statistics for completed jobs.
    """
    total = Job.query.filter(Job.finished).count()
    success = Job.query.filter_by(status='success').count()
    failed = Job.query.filter_by(status='fail').count()

    stats = {
        'total': total,
        'success': success,
        'failed': failed,
        'success_rate': round(success / total * 100, 2) if total > 0 else 0,
        'by_disctype': {},
        'by_video_type': {},
        'by_month': {}
    }

    for disctype in ['bluray', 'dvd', 'music', 'data']:
        stats['by_disctype'][disctype] = Job.query.filter(
            Job.finished, Job.disctype == disctype
        ).count()

    for video_type in ['movie', 'series']:
        stats['by_video_type'][video_type] = Job.query.filter(
            Job.finished, Job.video_type == video_type
        ).count()

    return make_response(stats)
