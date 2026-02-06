"""
Job API Endpoints

Endpoints for managing ripping jobs.
"""

from flask import Blueprint
from sqlalchemy import or_

from arm.ui.api import (
    api_auth_required, admin_required, make_response, error_response,
    paginate_query, job_to_dict, Job, JobState, db, desc
)

api = Blueprint('jobs', __name__, url_prefix='/jobs')


@api.route('', methods=['GET'])
@api_auth_required
def list_jobs():
    """
    List Jobs

    Retrieve a paginated list of all jobs with optional filtering.

    Query Parameters:
        - page (int): Page number (default: 1)
        - per_page (int): Items per page (default: 20, max: 100)
        - status (str): Filter by job status (active, ripping, transcoding, success, fail, waiting)
        - disctype (str): Filter by disc type (bluray, dvd, music, data)
        - video_type (str): Filter by video type (movie, series)
        - search (str): Search in job title

    Returns:
        Paginated list of jobs
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status_filter = request.args.get('status')
    disctype_filter = request.args.get('disctype')
    video_type_filter = request.args.get('video_type')
    search_query = request.args.get('search')

    query = Job.query

    if status_filter:
        if status_filter == 'active':
            query = query.filter(~Job.finished)
        elif status_filter in ['ripping', 'transcoding', 'waiting', 'success', 'fail']:
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

    return make_response({
        'jobs': [job_to_dict(job) for job in jobs],
        'pagination': pagination
    })


@api.route('/active', methods=['GET'])
def list_active_jobs():
    """
    List Active Jobs

    Retrieve all currently active (non-finished) jobs.
    This endpoint is public (no authentication required).
    """
    jobs = Job.query.filter(~Job.finished).order_by(desc(Job.job_id)).all()

    active_jobs = []
    for job in jobs:
        active_jobs.append({
            'job_id': job.job_id,
            'title': job.title,
            'label': job.label,
            'status': job.status,
            'status_display': JobState(job.status).name if JobState(job.status) else job.status,
            'disctype': job.disctype,
            'stage': getattr(job, 'stage', None),
            'progress': getattr(job, 'progress', None),
            'progress_round': getattr(job, 'progress_round', None),
            'eta': getattr(job, 'eta', None),
            'no_of_titles': job.no_of_titles,
            'start_time': job.start_time.isoformat() if job.start_time else None,
            'video_type': job.video_type,
            'imdb_id': job.imdb_id,
            'poster_url': job.poster_url
        })

    return make_response({
        'jobs': active_jobs,
        'count': len(active_jobs)
    })


@api.route('/statistics', methods=['GET'])
@api_auth_required
def job_statistics():
    """
    Get Job Statistics

    Retrieve aggregated statistics about jobs.
    """
    stats = {
        'total': Job.query.count(),
        'active': Job.query.filter(~Job.finished).count(),
        'success': Job.query.filter_by(status='success').count(),
        'fail': Job.query.filter_by(status='fail').count(),
        'by_disctype': {},
        'by_video_type': {}
    }

    for disctype in ['bluray', 'dvd', 'music', 'data']:
        stats['by_disctype'][disctype] = Job.query.filter_by(disctype=disctype).count()
    for video_type in ['movie', 'series', 'music']:
        stats['by_video_type'][video_type] = Job.query.filter_by(video_type=video_type).count()

    return make_response(stats)


@api.route('/<int:job_id>', methods=['GET'])
@api_auth_required
def get_job(job_id):
    """
    Get Job Details

    Retrieve detailed information about a specific job.
    """
    job = Job.query.get(job_id)
    if not job:
        return error_response(f'Job with ID {job_id} not found', 404)
    return make_response(job_to_dict(job))


@api.route('/<int:job_id>', methods=['DELETE'])
@api_auth_required
@admin_required
def delete_job(job_id):
    """
    Delete Job

    Delete a job and its associated tracks and config.
    """
    job = Job.query.get(job_id)
    if not job:
        return error_response(f'Job with ID {job_id} not found', 404)

    delete_files = request.args.get('delete_files', 'false').lower() == 'true'

    try:
        Track.query.filter_by(job_id=job_id).delete()
        Config.query.filter_by(job_id=job_id).delete()
        db.session.delete(job)
        db.session.commit()

        if delete_files and job.path:
            import shutil
            try:
                if os.path.exists(job.path):
                    shutil.rmtree(job.path)
            except OSError:
                pass

        return make_response(None, f'Job {job_id} deleted successfully')
    except Exception as e:
        db.session.rollback()
        return error_response(f'Failed to delete job: {str(e)}', 500)


@api.route('/<int:job_id>/abandon', methods=['POST'])
@api_auth_required
def abandon_job(job_id):
    """
    Abandon Job

    Forcefully terminate a running job.
    """
    import psutil

    job = Job.query.get(job_id)
    if not job:
        return error_response(f'Job with ID {job_id} not found', 404)
    if job.finished:
        return error_response('Cannot abandon a finished job', 400)

    try:
        if job.pid:
            try:
                process = psutil.Process(job.pid)
                process.terminate()
            except psutil.NoSuchProcess:
                pass

        job.status = JobState.FAILURE.value
        job.stop_time = datetime.now()

        notification = Notifications(
            f'Job {job_id} was abandoned',
            f'Job {job_id} was forcefully terminated by user'
        )
        db.session.add(notification)
        db.session.commit()

        return make_response(None, f'Job {job_id} abandoned successfully')
    except Exception as e:
        db.session.rollback()
        return error_response(f'Failed to abandon job: {str(e)}', 500)


@api.route('/<int:job_id>/tracks', methods=['GET'])
@api_auth_required
def get_job_tracks(job_id):
    """
    Get Job Tracks

    Retrieve all tracks associated with a specific job.
    """
    job = Job.query.get(job_id)
    if not job:
        return error_response(f'Job with ID {job_id} not found', 404)

    tracks = job.tracks.all()
    return make_response({
        'job_id': job_id,
        'tracks': [track_to_dict(t) for t in tracks]
    })


@api.route('/<int:job_id>/title', methods=['PATCH'])
@api_auth_required
def update_job_title(job_id):
    """
    Update Job Title and Metadata

    Update a job's title, year, video type, IMDB ID, and poster URL.

    Request Body:
        {
            "title": "New Movie Title",
            "year": "2023",
            "video_type": "movie",
            "imdb_id": "tt1234567",
            "poster_url": "https://example.com/poster.jpg"
        }
    """
    job = Job.query.get(job_id)
    if not job:
        return error_response(f'Job with ID {job_id} not found', 404)

    data = request.get_json()
    if not data:
        return error_response('Request body must be JSON', 400)

    try:
        if 'title' in data:
            job.title = job.title_manual = ui_utils.clean_for_filename(data['title'])
            job.hasnicetitle = True
        if 'year' in data:
            job.year = job.year_manual = str(data['year'])
        if 'video_type' in data:
            job.video_type = job.video_type_manual = data['video_type']
        if 'imdb_id' in data:
            job.imdb_id = job.imdb_id_manual = data['imdb_id']
        if 'poster_url' in data:
            job.poster_url = job.poster_url_manual = data['poster_url']

        db.session.commit()

        notification = Notifications(
            f'Job {job_id} title updated',
            f'Title: {job.title} ({job.year})'
        )
        db.session.add(notification)
        db.session.commit()

        return make_response(job_to_dict(job), 'Job title updated successfully')
    except Exception as e:
        db.session.rollback()
        return error_response(f'Failed to update job title: {str(e)}', 500)


@api.route('/<int:job_id>/params', methods=['PATCH'])
@api_auth_required
def update_job_params(job_id):
    """
    Update Job Parameters

    Update ripping/transcoding parameters for a job.

    Request Body:
        {
            "disctype": "bluray",
            "minlength": "600",
            "maxlength": "99999",
            "ripmethod": "mkv",
            "mainfeature": true,
            "skip_transcode": false
        }
    """
    job = Job.query.get(job_id)
    if not job:
        return error_response(f'Job with ID {job_id} not found', 404)

    data = request.get_json()
    if not data:
        return error_response('Request body must be JSON', 400)

    try:
        config = job.config

        if 'disctype' in data:
            job.disctype = data['disctype']
        if 'minlength' in data:
            config.MINLENGTH = str(data['minlength'])
            cfg.arm_config['MINLENGTH'] = config.MINLENGTH
        if 'maxlength' in data:
            config.MAXLENGTH = str(data['maxlength'])
            cfg.arm_config['MAXLENGTH'] = config.MAXLENGTH
        if 'ripmethod' in data:
            config.RIPMETHOD = data['ripmethod']
            cfg.arm_config['RIPMETHOD'] = config.RIPMETHOD
        if 'mainfeature' in data:
            config.MAINFEATURE = 1 if data['mainfeature'] else 0
            cfg.arm_config['MAINFEATURE'] = config.MAINFEATURE
        if 'skip_transcode' in data:
            config.SKIP_TRANSCODE = data['skip_transcode']
        if 'videotype' in data:
            config.VIDEOTYPE = data['videotype']

        db.session.commit()
        return make_response(config_to_dict(config), 'Job parameters updated successfully')
    except Exception as e:
        db.session.rollback()
        return error_response(f'Failed to update job params: {str(e)}', 500)


@api.route('/<int:job_id>/tracks/batch', methods=['PATCH'])
@api_auth_required
def batch_update_tracks(job_id):
    """
    Batch Update Tracks

    Update multiple tracks for a job in a single request.

    Request Body:
        {
            "tracks": [
                {"track_id": 1, "process": true},
                {"track_id": 2, "process": false}
            ]
        }
    """
    job = Job.query.get(job_id)
    if not job:
        return error_response(f'Job with ID {job_id} not found', 404)

    data = request.get_json()
    if not data or 'tracks' not in data:
        return error_response('Request body must contain "tracks" array', 400)

    try:
        updated_count = 0
        for track_data in data['tracks']:
            track_id = track_data.get('track_id')
            if not track_id:
                continue

            track = Track.query.filter_by(track_id=track_id, job_id=job_id).first()
            if track:
                if 'process' in track_data:
                    track.process = bool(track_data['process'])
                if 'error' in track_data:
                    track.error = str(track_data['error']) if track_data['error'] else None
                updated_count += 1

        db.session.commit()
        job.manual_start = True
        db.session.commit()

        return make_response({'updated': updated_count}, f'{updated_count} tracks updated')
    except Exception as e:
        db.session.rollback()
        return error_response(f'Failed to update tracks: {str(e)}', 500)


# Import Track-related function for use above
from arm.ui.api import track_to_dict, Notifications, os, ui_utils
