"""
ARM REST API Blueprint

This module provides a comprehensive REST API for the Automatic Ripping Machine,
enabling external applications (mobile apps, web UIs, automation tools) to interact
with ARM programmatically.

Base URL: /api/v1

Authentication:
- Most endpoints require authentication via session or API key
- Some endpoints (like job status) are publicly accessible
- Use Authorization header with Bearer token for API key auth:
  Authorization: Bearer <api_key>

Content Type:
- All responses are JSON (application/json)
- Request bodies should be JSON (application/json)

Response Format:
All responses follow this structure:
{
    "success": true,
    "data": {...},        // or "data": [...] for lists
    "message": "Optional human-readable message",
    "errors": [...]       // only present on failure
}

Error Codes:
- 400: Bad Request (invalid parameters)
- 401: Unauthorized (authentication required)
- 403: Forbidden (insufficient permissions)
- 404: Not Found (resource doesn't exist)
- 500: Internal Server Error

Rate Limiting:
- Not currently implemented, but planned for future versions

Versioning:
- API versioning is done via URL prefix (/api/v1/)
- Breaking changes will increment the version number

Endpoints by Category:
- Jobs: /api/v1/jobs
- Tracks: /api/v1/tracks
- System: /api/v1/system (info, drives)
- Settings: /api/v1/settings
- Notifications: /api/v1/notifications
- Logs: /api/v1/logs
- History: /api/v1/history
"""

import os
import psutil
import platform
import subprocess
import re
from datetime import datetime
from functools import wraps
from flask import Blueprint, request, jsonify, current_app, g
from flask_login import login_required, current_user
from sqlalchemy import desc
import arm.config.config as cfg
from arm.ui import app, db
from arm.models.job import Job, JobState
from arm.models.track import Track
from arm.models.config import Config
from arm.models.system_info import SystemInfo
from arm.models.system_drives import SystemDrives
from arm.models.notifications import Notifications
from arm.models.ui_settings import UISettings
from arm.ui.settings import DriveUtils as drive_utils

# Create API blueprint
api = Blueprint('api', __name__, url_prefix='/api/v1')

# ==============================================================================
# AUTHENTICATION DECORATORS
# ==============================================================================


def api_auth_required(f):
    """
    Decorator that requires authentication for API endpoints.

    Checks if user is authenticated via session or valid API key.
    Sets g.user to the authenticated user for downstream use.

    Returns:
        - 401 Unauthorized if not authenticated
        - Proceeds to wrapped function if authenticated
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check if user is logged in via session
        if current_user.is_authenticated:
            g.user = current_user
            return f(*args, **kwargs)

        # Check for API key in Authorization header
        # ARM uses a global ARM_API_KEY from config, not per-user keys
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            api_key = auth_header[7:]  # Remove 'Bearer ' prefix
            # Validate against the global ARM_API_KEY from config
            valid_key = cfg.arm_config.get('ARM_API_KEY', '')
            if api_key == valid_key and valid_key:
                g.user = 'api_key_auth'
                return f(*args, **kwargs)

        # Also allow api_key as query parameter (for simple integrations)
        api_key_param = request.args.get('api_key')
        if api_key_param:
            valid_key = cfg.arm_config.get('ARM_API_KEY', '')
            if api_key_param == valid_key and valid_key:
                g.user = 'api_key_auth'
                return f(*args, **kwargs)

        return jsonify({
            'success': False,
            'error': 'Authentication required',
            'message': 'Please login or provide a valid API key (ARM_API_KEY from config)'
        }), 401

    return decorated


def admin_required(f):
    """
    Decorator that requires admin authentication for API endpoints.

    In ARM, all users are admins (there's only one user account).
    This decorator checks for valid session or API key authentication.

    Returns:
        - 403 Forbidden if not authenticated
        - Proceeds to wrapped function if authenticated
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check if user is authenticated via session or valid API key
        is_authenticated = False

        if current_user.is_authenticated:
            g.user = current_user
            is_authenticated = True
        elif hasattr(g, 'user') and g.user == 'api_key_auth':
            is_authenticated = True

        if not is_authenticated:
            return jsonify({
                'success': False,
                'error': 'Admin authentication required',
                'message': 'This endpoint requires admin privileges. Please login or provide a valid API key.'
            }), 403

        return f(*args, **kwargs)

    return decorated


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


def make_response(data, message=None, status_code=200):
    """
    Standard API response builder.

    Args:
        data: Data to return (dict or list)
        message: Optional human-readable message
        status_code: HTTP status code

    Returns:
        JSON response with standard format
    """
    response = {
        'success': 200 <= status_code < 300,
        'data': data
    }
    if message:
        response['message'] = message

    return jsonify(response), status_code


def error_response(message, status_code=400, errors=None):
    """
    Standard error response builder.

    Args:
        message: Human-readable error message
        status_code: HTTP status code
        errors: Optional list of specific errors

    Returns:
        JSON error response
    """
    response = {
        'success': False,
        'error': message,
        'message': message
    }
    if errors:
        response['errors'] = errors

    return jsonify(response), status_code


def paginate_query(query, page=1, per_page=20):
    """
    Paginate a SQLAlchemy query.

    Args:
        query: SQLAlchemy query object
        page: Page number (1-based)
        per_page: Items per page (default 20, max 100)

    Returns:
        Tuple of (items, pagination_info)
    """
    if per_page > 100:
        per_page = 100
    if per_page < 1:
        per_page = 1
    if page < 1:
        page = 1

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return pagination.items, {
        'page': page,
        'per_page': per_page,
        'total': pagination.total,
        'pages': pagination.pages,
        'has_prev': pagination.has_prev,
        'has_next': pagination.has_next,
        'has_range': pagination.iter_pages() is not None
    }


def job_to_dict(job, include_tracks=True, include_config=True):
    """
    Convert Job model to dictionary for API responses.

    Args:
        job: Job model instance
        include_tracks: Include related tracks
        include_config: Include related config

    Returns:
        Dictionary representation of Job
    """
    result = {
        'job_id': job.job_id,
        'arm_version': job.arm_version,
        'crc_id': job.crc_id,
        'logfile': job.logfile,
        'start_time': job.start_time.isoformat() if job.start_time else None,
        'stop_time': job.stop_time.isoformat() if job.stop_time else None,
        'job_length': job.job_length,
        'status': job.status,
        'status_display': JobState(job.status).name if JobState(job.status) else job.status,
        'stage': job.stage,
        'no_of_titles': job.no_of_titles,
        'title': job.title,
        'title_auto': job.title_auto,
        'title_manual': job.title_manual,
        'year': job.year,
        'year_auto': job.year_auto,
        'year_manual': job.year_manual,
        'video_type': job.video_type,
        'video_type_auto': job.video_type_auto,
        'video_type_manual': job.video_type_manual,
        'imdb_id': job.imdb_id,
        'imdb_id_auto': job.imdb_id_auto,
        'imdb_id_manual': job.imdb_id_manual,
        'poster_url': job.poster_url,
        'poster_url_auto': job.poster_url_auto,
        'poster_url_manual': job.poster_url_manual,
        'devpath': job.devpath,
        'mountpoint': job.mountpoint,
        'hasnicetitle': job.hasnicetitle,
        'errors': job.errors,
        'disctype': job.disctype,
        'label': job.label,
        'path': job.path,
        'ejected': job.ejected,
        'updated': job.updated,
        'pid': job.pid,
        'is_iso': job.is_iso,
        'manual_start': job.manual_start,
        'manual_mode': job.manual_mode,
        'progress': getattr(job, 'progress', None),
        'progress_round': getattr(job, 'progress_round', None),
        'eta': getattr(job, 'eta', None),
        'finished': job.finished,
        'idle': job.idle,
        'ripping': job.ripping,
        'created_at': job.start_time.isoformat() if job.start_time else None
    }

    if include_tracks:
        result['tracks'] = [track_to_dict(t) for t in job.tracks.all()]

    if include_config and job.config:
        result['config'] = config_to_dict(job.config)

    return result


def track_to_dict(track):
    """
    Convert Track model to dictionary for API responses.

    Args:
        track: Track model instance

    Returns:
        Dictionary representation of Track
    """
    return {
        'track_id': track.track_id,
        'job_id': track.job_id,
        'track_number': track.track_number,
        'length': track.length,
        'aspect_ratio': track.aspect_ratio,
        'fps': track.fps,
        'main_feature': track.main_feature,
        'basename': track.basename,
        'filename': track.filename,
        'orig_filename': track.orig_filename,
        'new_filename': track.new_filename,
        'ripped': track.ripped,
        'status': track.status,
        'error': track.error,
        'source': track.source,
        'process': track.process
    }


def config_to_dict(config):
    """
    Convert Config model to dictionary for API responses.

    Args:
        config: Config model instance

    Returns:
        Dictionary representation of Config (sanitized)
    """
    hidden = ('OMDB_API_KEY', 'EMBY_USERID', 'EMBY_PASSWORD', 'EMBY_API_KEY',
              'PB_KEY', 'IFTTT_KEY', 'PO_KEY', 'PO_USER_KEY', 'PO_APP_KEY',
              'ARM_API_KEY', 'TMDB_API_KEY')

    result = {}
    for key, value in config.__dict__.items():
        if key == '_sa_instance_state':
            continue
        if key in hidden:
            result[key] = '<hidden>'
        else:
            result[key] = str(value) if value is not None else None

    result['config_id'] = config.CONFIG_ID
    result['job_id'] = config.job_id

    return result


def drive_to_dict(drive):
    """
    Convert SystemDrives model to dictionary for API responses.

    Args:
        drive: SystemDrives model instance

    Returns:
        Dictionary representation of SystemDrives
    """
    return {
        'drive_id': drive.drive_id,
        'name': drive.name,
        'description': drive.description,
        'serial_id': drive.serial_id,
        'maker': drive.maker,
        'model': drive.model,
        'serial': drive.serial,
        'connection': drive.connection,
        'read_cd': drive.read_cd,
        'read_dvd': drive.read_dvd,
        'read_bd': drive.read_bd,
        'mount': drive.mount,
        'firmware': drive.firmware,
        'location': drive.location,
        'stale': drive.stale,
        'mdisc': drive.mdisc,
        'drive_type': drive.type,
        'drive_mode': drive.drive_mode,
        'job_id_current': drive.job_id_current,
        'job_id_previous': drive.job_id_previous,
        'tray_status': drive.tray.name if drive.tray else None,
        'tray_open': drive.open,
        'ready': drive.ready,
        'processing': drive.processing
    }


# ==============================================================================
# ROOT ENDPOINTS
# ==============================================================================


@api.route('/', methods=['GET'])
def api_index():
    """
    API Index

    Provides information about the API and available endpoints.

    Returns:
        JSON object with API metadata and available routes

    Example Response:
    {
        "success": true,
        "data": {
            "name": "ARM API",
            "version": "1.0.0",
            "description": "Automatic Ripping Machine REST API",
            "endpoints": {
                "jobs": "/api/v1/jobs",
                "tracks": "/api/v1/tracks",
                "system": "/api/v1/system",
                "settings": "/api/v1/settings",
                "notifications": "/api/v1/notifications",
                "logs": "/api/v1/logs",
                "history": "/api/v1/history"
            },
            "authentication": "Session or Bearer token required for most endpoints",
            "documentation": "/api/v1/docs"
        }
    }
    """
    return make_response({
        'name': 'ARM API',
        'version': '1.0.0',
        'description': 'Automatic Ripping Machine REST API',
        'endpoints': {
            'jobs': '/api/v1/jobs',
            'tracks': '/api/v1/tracks',
            'system': '/api/v1/system',
            'settings': '/api/v1/settings',
            'notifications': '/api/v1/notifications',
            'logs': '/api/v1/logs',
            'history': '/api/v1/history'
        },
        'authentication': 'Session or Bearer token required for most endpoints',
        'documentation': '/api/v1/docs'
    })


# ==============================================================================
# JOB ENDPOINTS
# ==============================================================================


@api.route('/jobs', methods=['GET'])
@api_auth_required
def list_jobs():
    """
    List Jobs

    Retrieve a paginated list of all jobs with optional filtering.

    Query Parameters:
        - page (int): Page number (default: 1)
        - per_page (int): Items per page (default: 20, max: 100)
        - status (str): Filter by job status
            - active: Currently active jobs
            - ripping: Jobs currently ripping
            - transcoding: Jobs currently transcoding
            - success: Successfully completed jobs
            - fail: Failed jobs
            - waiting: Jobs waiting for user input
        - disctype (str): Filter by disc type (bluray, dvd, music, data)
        - video_type (str): Filter by video type (movie, series)
        - search (str): Search in job title

    Returns:
        Paginated list of jobs

    Example Request:
        GET /api/v1/jobs?status=active&page=1&per_page=10

    Example Response:
    {
        "success": true,
        "data": [...],
        "pagination": {
            "page": 1,
            "per_page": 10,
            "total": 150,
            "pages": 15,
            "has_prev": false,
            "has_next": true
        }
    }
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
        query = query.filter(Job.title.like(search_term))

    # Order by job_id descending (newest first)
    query = query.order_by(desc(Job.job_id))

    jobs, pagination = paginate_query(query, page, per_page)

    return make_response({
        'jobs': [job_to_dict(job) for job in jobs],
        'pagination': pagination
    })


@api.route('/jobs/active', methods=['GET'])
def list_active_jobs():
    """
    List Active Jobs

    Retrieve all currently active (non-finished) jobs.
    This endpoint is public (no authentication required).

    Returns:
        List of active jobs with their current status and progress

    Example Request:
        GET /api/v1/jobs/active

    Example Response:
    {
        "success": true,
        "data": [
            {
                "job_id": 123,
                "title": "Movie Title",
                "status": "ripping",
                "disctype": "bluray",
                "progress": 45.5,
                "stage": "2/3 - Ripping title 2",
                "eta": "00:15:30"
            }
        ],
        "count": 1
    }
    """
    jobs = Job.query.filter(~Job.finished).order_by(desc(Job.job_id)).all()

    active_jobs = []
    for job in jobs:
        job_dict = {
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
        }
        active_jobs.append(job_dict)

    return make_response({
        'jobs': active_jobs,
        'count': len(active_jobs)
    })


@api.route('/jobs/statistics', methods=['GET'])
@api_auth_required
def job_statistics():
    """
    Get Job Statistics

    Retrieve aggregated statistics about jobs.

    Returns:
        Object containing various job statistics

    Example Request:
        GET /api/v1/jobs/statistics

    Example Response:
    {
        "success": true,
        "data": {
            "total": 500,
            "active": 5,
            "success": 450,
            "fail": 45,
            "by_disctype": {
                "bluray": 200,
                "dvd": 250,
                "music": 40,
                "data": 10
            },
            "by_video_type": {
                "movie": 400,
                "series": 50
            }
        }
    }
    """
    stats = {
        'total': Job.query.count(),
        'active': Job.query.filter(~Job.finished).count(),
        'success': Job.query.filter_by(status='success').count(),
        'fail': Job.query.filter_by(status='fail').count(),
        'by_disctype': {},
        'by_video_type': {}
    }

    # Count by disc type
    for disctype in ['bluray', 'dvd', 'music', 'data']:
        stats['by_disctype'][disctype] = Job.query.filter_by(disctype=disctype).count()

    # Count by video type
    for video_type in ['movie', 'series', 'music']:
        stats['by_video_type'][video_type] = Job.query.filter_by(video_type=video_type).count()

    return make_response(stats)


@api.route('/jobs/<int:job_id>', methods=['GET'])
@api_auth_required
def get_job(job_id):
    """
    Get Job Details

    Retrieve detailed information about a specific job.

    Path Parameters:
        - job_id (int): The unique identifier of the job

    Returns:
        Detailed job object with tracks and config

    Example Request:
        GET /api/v1/jobs/123

    Example Response:
    {
        "success": true,
        "data": {
            "job_id": 123,
            "title": "Movie Title",
            "year": "2023",
            "status": "success",
            "tracks": [...],
            "config": {...}
        }
    }
    """
    job = Job.query.get(job_id)

    if not job:
        return error_response(f'Job with ID {job_id} not found', 404)

    return make_response(job_to_dict(job))


@api.route('/jobs/<int:job_id>', methods=['DELETE'])
@api_auth_required
@admin_required
def delete_job(job_id):
    """
    Delete Job

    Delete a job and its associated tracks and config.
    Requires admin authentication.

    Path Parameters:
        - job_id (int): The unique identifier of the job

    Query Parameters:
        - delete_files (bool): Also delete associated files (default: false)

    Returns:
        Success message

    Example Request:
        DELETE /api/v1/jobs/123?delete_files=true

    Example Response:
    {
        "success": true,
        "message": "Job 123 deleted successfully"
    }
    """
    job = Job.query.get(job_id)

    if not job:
        return error_response(f'Job with ID {job_id} not found', 404)

    delete_files = request.args.get('delete_files', 'false').lower() == 'true'

    try:
        # Delete associated tracks
        Track.query.filter_by(job_id=job_id).delete()
        # Delete associated config
        Config.query.filter_by(job_id=job_id).delete()
        # Delete the job
        db.session.delete(job)
        db.session.commit()

        if delete_files and job.path:
            import shutil
            try:
                if os.path.exists(job.path):
                    shutil.rmtree(job.path)
            except OSError as e:
                app.logger.warning(f'Could not delete job files: {e}')

        return make_response(None, f'Job {job_id} deleted successfully')

    except Exception as e:
        db.session.rollback()
        return error_response(f'Failed to delete job: {str(e)}', 500)


@api.route('/jobs/<int:job_id>/abandon', methods=['POST'])
@api_auth_required
def abandon_job(job_id):
    """
    Abandon Job

    Forcefully terminate a running job.
    Sets job status to 'fail' and attempts to kill the process.

    Path Parameters:
        - job_id (int): The unique identifier of the job

    Returns:
        Success or error message

    Example Request:
        POST /api/v1/jobs/123/abandon

    Example Response:
    {
        "success": true,
        "message": "Job 123 abandoned successfully"
    }
    """
    job = Job.query.get(job_id)

    if not job:
        return error_response(f'Job with ID {job_id} not found', 404)

    if job.finished:
        return error_response('Cannot abandon a finished job', 400)

    try:
        # Kill the process if running
        if job.pid:
            try:
                process = psutil.Process(job.pid)
                process.terminate()
            except psutil.NoSuchProcess:
                pass  # Process already dead

        # Update job status
        job.status = JobState.FAILURE.value
        job.stop_time = datetime.now()

        # Create notification
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


@api.route('/jobs/<int:job_id>/tracks', methods=['GET'])
@api_auth_required
def get_job_tracks(job_id):
    """
    Get Job Tracks

    Retrieve all tracks associated with a specific job.

    Path Parameters:
        - job_id (int): The unique identifier of the job

    Returns:
        List of tracks for the job

    Example Request:
        GET /api/v1/jobs/123/tracks

    Example Response:
    {
        "success": true,
        "data": [
            {
                "track_id": 1,
                "track_number": "1",
                "length": 7200,
                "main_feature": true,
                "ripped": true
            }
        ]
    }
    """
    job = Job.query.get(job_id)

    if not job:
        return error_response(f'Job with ID {job_id} not found', 404)

    tracks = job.tracks.all()

    return make_response({
        'job_id': job_id,
        'tracks': [track_to_dict(t) for t in tracks]
    })


# ==============================================================================
# TRACK ENDPOINTS
# ==============================================================================


@api.route('/tracks', methods=['GET'])
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

    Example Request:
        GET /api/v1/tracks?job_id=123&ripped=false
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


@api.route('/tracks/<int:track_id>', methods=['GET'])
@api_auth_required
def get_track(track_id):
    """
    Get Track Details

    Retrieve detailed information about a specific track.

    Path Parameters:
        - track_id (int): The unique identifier of the track

    Returns:
        Track details

    Example Request:
        GET /api/v1/tracks/1
    """
    track = Track.query.get(track_id)

    if not track:
        return error_response(f'Track with ID {track_id} not found', 404)

    return make_response(track_to_dict(track))


@api.route('/tracks/<int:track_id>', methods=['PATCH'])
@api_auth_required
def update_track(track_id):
    """
    Update Track

    Update properties of a specific track.
    Only certain fields can be updated: process, error

    Path Parameters:
        - track_id (int): The unique identifier of the track

    Request Body:
        JSON object with fields to update:
        - process (bool): Whether to process this track
        - error (str): Error message if track failed

    Returns:
        Updated track details

    Example Request:
        PATCH /api/v1/tracks/1
        Content-Type: application/json
        {"process": true}
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


# ==============================================================================
# SYSTEM ENDPOINTS
# ==============================================================================


@api.route('/system/info', methods=['GET'])
@api_auth_required
def get_system_info():
    """
    Get System Information

    Retrieve server/system information including CPU, memory, and ARM details.

    Returns:
        System information object

    Example Request:
        GET /api/v1/system/info

    Example Response:
    {
        "success": true,
        "data": {
            "name": "ARM Server",
            "cpu": "Intel(R) Core(TM) i7-10700K",
            "memory_total_gb": 32.0,
            "python_version": "3.11.0",
            "arm_version": "2.0.0",
            "git_commit": "abc1234"
        }
    }
    """
    server = SystemInfo.query.filter_by(id="1").first()

    system_info = {
        'name': server.name if server else 'ARM Server',
        'cpu': server.cpu if server else 'Unknown',
        'memory_total_gb': server.mem_total if server else 0,
        'python_version': platform.python_version(),
        'arm_version': cfg.arm_config.get('ARM_VERSION', 'Unknown'),
        'git_commit': get_git_hash()
    }

    return make_response(system_info)


@api.route('/system/drives', methods=['GET'])
@api_auth_required
def get_drives():
    """
    List System Drives

    Retrieve information about all configured optical drives.

    Query Parameters:
        - include_jobs (bool): Include current job information (default: true)

    Returns:
        List of optical drives with their status

    Example Request:
        GET /api/v1/system/drives

    Example Response:
    {
        "success": true,
        "data": [
            {
                "drive_id": 1,
                "name": "Drive 1",
                "mount": "/dev/sr0",
                "drive_type": "CD/DVD/BluRay",
                "tray_status": "DISC_OK",
                "processing": true
            }
        ]
    }
    """
    include_jobs = request.args.get('include_jobs', 'true').lower() == 'true'

    # Update drive status
    drive_utils.update_job_status()
    drives = drive_utils.get_drives()
    drive_utils.update_tray_status(drives)

    drive_list = []
    for drive in drives:
        drive_dict = drive_to_dict(drive)
        if not include_jobs:
            drive_dict.pop('job_id_current', None)
            drive_dict.pop('job_id_previous', None)
        drive_list.append(drive_dict)

    return make_response({
        'drives': drive_list,
        'count': len(drive_list)
    })


@api.route('/system/drives/<int:drive_id>', methods=['GET'])
@api_auth_required
def get_drive(drive_id):
    """
    Get Drive Details

    Retrieve detailed information about a specific drive.

    Path Parameters:
        - drive_id (int): The unique identifier of the drive

    Returns:
        Drive details

    Example Request:
        GET /api/v1/system/drives/1
    """
    drive = SystemDrives.query.get(drive_id)

    if not drive:
        return error_response(f'Drive with ID {drive_id} not found', 404)

    return make_response(drive_to_dict(drive))


@api.route('/system/drives/<int:drive_id>/eject', methods=['POST'])
@api_auth_required
def eject_drive(drive_id):
    """
    Eject Drive

    Toggle the eject status of a drive.

    Path Parameters:
        - drive_id (int): The unique identifier of the drive

    Returns:
        Success or error message

    Example Request:
        POST /api/v1/system/drives/1/eject

    Example Response:
    {
        "success": true,
        "message": "Drive ejected successfully"
    }
    """
    drive = SystemDrives.query.get(drive_id)

    if not drive:
        return error_response(f'Drive with ID {drive_id} not found', 404)

    # Check for running jobs
    if drive.job_id_current:
        if not drive.open:
            return error_response(f'Job {drive.job_id_current} in progress. Cannot eject.', 400)

    error = drive.eject(method="toggle", logger=app.logger)

    if error:
        return error_response(error, 400)

    return make_response(None, 'Drive ejected successfully')


@api.route('/system/status', methods=['GET'])
def get_system_status():
    """
    Get System Status

    Retrieve current system status including drive usage and resource usage.
    This endpoint is public (no authentication required).

    Returns:
        System status object

    Example Request:
        GET /api/v1/system/status

    Example Response:
    {
        "success": true,
        "data": {
            "cpu_percent": 45.2,
            "memory_percent": 62.5,
            "disk_usage": {
                "total_gb": 2000,
                "used_gb": 1200,
                "free_gb": 800,
                "percent": 60.0
            },
            "active_jobs": 2,
            "drives_ready": 3
        }
    }
    """
    # Get resource usage
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(cfg.arm_config.get('COMPLETED_PATH', '/'))

    # Get active jobs count
    active_jobs = Job.query.filter(~Job.finished).count()

    # Get drives info
    drives = SystemDrives.query.all()
    drives_ready = sum(1 for d in drives if d.ready)

    return make_response({
        'cpu_percent': cpu_percent,
        'memory_percent': memory.percent,
        'memory_used_gb': round(memory.used / 1073741824, 1),
        'memory_total_gb': round(memory.total / 1073741824, 1),
        'disk_usage': {
            'total_gb': round(disk.total / 1073741824, 1),
            'used_gb': round(disk.used / 1073741824, 1),
            'free_gb': round(disk.free / 1073741824, 1),
            'percent': disk.percent
        },
        'active_jobs': active_jobs,
        'drives_ready': drives_ready,
        'timestamp': datetime.now().isoformat()
    })


# ==============================================================================
# SETTINGS ENDPOINTS
# ==============================================================================


@api.route('/settings', methods=['GET'])
@api_auth_required
def get_settings():
    """
    Get ARM Settings

    Retrieve all ARM configuration settings.

    Returns:
        ARM settings object (sensitive values hidden)

    Example Request:
        GET /api/v1/settings

    Example Response:
    {
        "success": true,
        "data": {
            "arm_name": "My ARM",
            "log_level": "INFO",
            "rip_method": "mkv",
            "main_feature": true
        }
    }
    """
    settings = {}
    for key, value in cfg.arm_config.items():
        if key in ('OMDB_API_KEY', 'EMBY_USERID', 'EMBY_PASSWORD', 'EMBY_API_KEY',
                   'PB_KEY', 'IFTTT_KEY', 'PO_KEY', 'PO_USER_KEY', 'PO_APP_KEY',
                   'ARM_API_KEY', 'TMDB_API_KEY'):
            settings[key] = '<hidden>'
        else:
            settings[key] = value

    return make_response(settings)


@api.route('/settings/ui', methods=['GET'])
@api_auth_required
def get_ui_settings():
    """
    Get UI Settings

    Retrieve ARM UI configuration settings from database.

    Returns:
        UI settings object

    Example Request:
        GET /api/v1/settings/ui
    """
    ui_settings = UISettings.query.first()

    if not ui_settings:
        return make_response({
            'use_icons': True,
            'save_remote_images': False,
            'bootstrap_skin': 'default',
            'language': 'en',
            'index_refresh': 5,
            'database_limit': 100,
            'notify_refresh': 6500
        })

    return make_response(ui_settings.get_d())


@api.route('/settings/ui', methods=['PATCH'])
@api_auth_required
@admin_required
def update_ui_settings():
    """
    Update UI Settings

    Update ARM UI configuration settings.

    Request Body:
        JSON object with fields to update:
        - use_icons (bool): Use icons in UI
        - save_remote_images (bool): Save remote images locally
        - bootstrap_skin (str): Bootstrap theme
        - language (str): Language code
        - index_refresh (int): Index page refresh rate (seconds)
        - database_limit (int): Database entries per page
        - notify_refresh (int): Notification refresh rate (ms)

    Returns:
        Updated UI settings

    Example Request:
        PATCH /api/v1/settings/ui
        Content-Type: application/json
        {"bootstrap_skin": "darkly", "index_refresh": 10}
    """
    data = request.get_json()
    if not data:
        return error_response('Request body must be JSON', 400)

    ui_settings = UISettings.query.first()
    if not ui_settings:
        ui_settings = UISettings()
        db.session.add(ui_settings)

    try:
        if 'use_icons' in data:
            ui_settings.use_icons = bool(data['use_icons'])
        if 'save_remote_images' in data:
            ui_settings.save_remote_images = bool(data['save_remote_images'])
        if 'bootstrap_skin' in data:
            ui_settings.bootstrap_skin = str(data['bootstrap_skin'])
        if 'language' in data:
            ui_settings.language = str(data['language'])
        if 'index_refresh' in data:
            ui_settings.index_refresh = int(data['index_refresh'])
        if 'database_limit' in data:
            ui_settings.database_limit = int(data['database_limit'])
        if 'notify_refresh' in data:
            ui_settings.notify_refresh = int(data['notify_refresh'])

        db.session.commit()

        return make_response(ui_settings.get_d(), 'UI settings updated successfully')

    except Exception as e:
        db.session.rollback()
        return error_response(f'Failed to update settings: {str(e)}', 500)


@api.route('/settings/abcde', methods=['GET'])
@api_auth_required
def get_abcde_config():
    """
    Get ABCDE Configuration

    Retrieve the ABCDE (audio CD ripper) configuration.

    Returns:
        ABCDE configuration as string

    Example Request:
        GET /api/v1/settings/abcde
    """
    abcde_config = cfg.abcde_config

    return make_response({
        'config': abcde_config
    })


@api.route('/settings/apprise', methods=['GET'])
@api_auth_required
def get_apprise_config():
    """
    Get Apprise Configuration

    Retrieve the Apprise notification configuration.

    Returns:
        Apprise configuration (sanitized)

    Example Request:
        GET /api/v1/settings/apprise
    """
    apprise_cfg = {}
    for key, value in cfg.apprise_config.items():
        if 'password' in key.lower() or 'token' in key.lower() or 'key' in key.lower():
            apprise_cfg[key] = '<hidden>'
        else:
            apprise_cfg[key] = value

    return make_response(apprise_cfg)


# ==============================================================================
# NOTIFICATION ENDPOINTS
# ==============================================================================


@api.route('/notifications', methods=['GET'])
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

    Returns:
        Paginated list of notifications

    Example Request:
        GET /api/v1/notifications?seen=false
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


@api.route('/notifications/unread', methods=['GET'])
@api_auth_required
def list_unread_notifications():
    """
    List Unread Notifications

    Retrieve all unread (unseen) notifications.

    Returns:
        List of unread notifications

    Example Request:
        GET /api/v1/notifications/unread
    """
    notifications = Notifications.query.filter_by(seen=False).order_by(
        desc(Notifications.trigger_time)
    ).all()

    return make_response({
        'notifications': [n.get_d() for n in notifications],
        'count': len(notifications)
    })


@api.route('/notifications/<int:notification_id>/read', methods=['POST'])
@api_auth_required
def mark_notification_read(notification_id):
    """
    Mark Notification as Read

    Mark a specific notification as seen/read.

    Path Parameters:
        - notification_id (int): The unique identifier of the notification

    Returns:
        Success message

    Example Request:
        POST /api/v1/notifications/5/read
    """
    notification = Notifications.query.get(notification_id)

    if not notification:
        return error_response(f'Notification with ID {notification_id} not found', 404)

    notification.seen = True
    notification.dismiss_time = datetime.now()
    db.session.commit()

    return make_response(None, 'Notification marked as read')


@api.route('/notifications/read-all', methods=['POST'])
@api_auth_required
def mark_all_notifications_read():
    """
    Mark All Notifications as Read

    Mark all unread notifications as seen.

    Returns:
        Success message with count of updated notifications

    Example Request:
        POST /api/v1/notifications/read-all
    """
    count = Notifications.query.filter_by(seen=False).update({
        'seen': True,
        'dismiss_time': datetime.now()
    })
    db.session.commit()

    return make_response(None, f'{count} notifications marked as read')


# ==============================================================================
# LOG ENDPOINTS
# ==============================================================================


@api.route('/logs', methods=['GET'])
@api_auth_required
def list_logs():
    """
    List Log Files

    Retrieve information about available log files.

    Query Parameters:
        - job_id (int): Filter logs by job ID
        - limit (int): Maximum number of logs to return

    Returns:
        List of log file information

    Example Request:
        GET /api/v1/logs?job_id=123
    """
    logpath = cfg.arm_config.get('LOGPATH', '/var/log/arm')
    job_id = request.args.get('job_id', type=int)
    limit = request.args.get('limit', 50, type=int)

    logs = []
    try:
        if os.path.exists(logpath):
            for filename in sorted(os.listdir(logpath), reverse=True)[:limit]:
                if filename.endswith('.log'):
                    filepath = os.path.join(logpath, filename)
                    if os.path.isfile(filepath):
                        stat = os.stat(filepath)
                        logs.append({
                            'filename': filename,
                            'size': stat.st_size,
                            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                        })

            if job_id:
                logs = [l for l in logs if f'_{job_id}' in l['filename']]

    except OSError as e:
        return error_response(f'Error reading log directory: {str(e)}', 500)

    return make_response({
        'logs': logs,
        'count': len(logs)
    })


@api.route('/logs/<path:filename>', methods=['GET'])
@api_auth_required
def get_log(filename):
    """
    Get Log File Contents

    Retrieve the contents of a specific log file.

    Path Parameters:
        - filename (path): The filename or path of the log

    Query Parameters:
        - lines (int): Maximum number of lines to return (default: 100)
        - offset (int): Start from this line number (default: 0)

    Returns:
        Log file contents

    Example Request:
        GET /api/v1/logs/arm_rip_20240101.log?lines=50
    """
    logpath = cfg.arm_config.get('LOGPATH', '/var/log/arm')
    max_lines = request.args.get('lines', 100, type=int)
    offset = request.args.get('offset', 0, type=int)

    # Security: prevent directory traversal
    filename = os.path.basename(filename)
    filepath = os.path.join(logpath, filename)

    if not os.path.exists(filepath):
        return error_response(f'Log file not found: {filename}', 404)

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        total_lines = len(lines)
        lines = lines[offset:offset + max_lines]

        return make_response({
            'filename': filename,
            'total_lines': total_lines,
            'returned_lines': len(lines),
            'offset': offset,
            'content': ''.join(lines)
        })

    except OSError as e:
        return error_response(f'Error reading log file: {str(e)}', 500)


@api.route('/logs/job/<int:job_id>', methods=['GET'])
@api_auth_required
def get_job_log(job_id):
    """
    Get Job Log

    Retrieve the log file for a specific job.

    Path Parameters:
        - job_id (int): The unique identifier of the job

    Returns:
        Job log contents

    Example Request:
        GET /api/v1/logs/job/123
    """
    job = Job.query.get(job_id)

    if not job or not job.logfile:
        return error_response(f'Job {job_id} or log file not found', 404)

    return get_log(job.logfile)


# ==============================================================================
# HISTORY ENDPOINTS
# ==============================================================================


@api.route('/history', methods=['GET'])
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

    Returns:
        Paginated list of completed jobs

    Example Request:
        GET /api/v1/history?status=success&page=1&per_page=25
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
        query = query.filter(Job.title.like(search_term))

    query = query.order_by(desc(Job.job_id))

    jobs, pagination = paginate_query(query, page, per_page)

    # Lightweight job representation for history
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


@api.route('/history/statistics', methods=['GET'])
@api_auth_required
def history_statistics():
    """
    Get History Statistics

    Retrieve aggregated statistics for completed jobs.

    Returns:
        History statistics object

    Example Request:
        GET /api/v1/history/statistics
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

    # Count by disc type
    for disctype in ['bluray', 'dvd', 'music', 'data']:
        stats['by_disctype'][disctype] = Job.query.filter(
            Job.finished,
            Job.disctype == disctype
        ).count()

    # Count by video type
    for video_type in ['movie', 'series']:
        stats['by_video_type'][video_type] = Job.query.filter(
            Job.finished,
            Job.video_type == video_type
        ).count()

    return make_response(stats)


# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================


def get_git_hash():
    """
    Get the current git commit hash.

    Returns:
        Git commit hash or 'Unknown' if not available
    """
    try:
        import subprocess
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            capture_output=True,
            text=True
        )
        return result.stdout.strip()[:7] if result.returncode == 0 else 'Unknown'
    except Exception:
        return 'Unknown'


# ==============================================================================
# ERROR HANDLERS
# ==============================================================================


@api.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return error_response('Resource not found', 404)


@api.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    app.logger.error(f'API Error: {error}')
    return error_response('Internal server error', 500)
