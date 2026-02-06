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
from arm.models.user import User
from arm.ui.settings import DriveUtils as drive_utils
import arm.ui.utils as ui_utils

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
# JOB TITLE/METADATA ENDPOINTS
# ==============================================================================


@api.route('/jobs/<int:job_id>/title', methods=['PATCH'])
@api_auth_required
def update_job_title(job_id):
    """
    Update Job Title and Metadata

    Update a job's title, year, video type, IMDB ID, and poster URL.

    Path Parameters:
        - job_id (int): The unique identifier of the job

    Request Body:
        {
            "title": "New Movie Title",
            "year": "2023",
            "video_type": "movie",  // or "series"
            "imdb_id": "tt1234567",
            "poster_url": "https://example.com/poster.jpg"
        }

    Returns:
        Updated job details

    Example Request:
        PATCH /api/v1/jobs/123/title
        Content-Type: application/json
        {"title": "New Title", "year": "2024"}
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

        # Create notification
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


@api.route('/jobs/<int:job_id>/params', methods=['PATCH'])
@api_auth_required
def update_job_params(job_id):
    """
    Update Job Parameters

    Update ripping/transcoding parameters for a job.

    Path Parameters:
        - job_id (int): The unique identifier of the job

    Request Body:
        {
            "disctype": "bluray",
            "minlength": "600",
            "maxlength": "99999",
            "ripmethod": "mkv",
            "mainfeature": true,
            "skip_transcode": false
        }

    Returns:
        Updated job config

    Example Request:
        PATCH /api/v1/jobs/123/params
        Content-Type: application/json
        {"ripmethod": "backup", "mainfeature": true}
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


@api.route('/jobs/<int:job_id>/tracks/batch', methods=['PATCH'])
@api_auth_required
def batch_update_tracks(job_id):
    """
    Batch Update Tracks

    Update multiple tracks for a job in a single request.

    Path Parameters:
        - job_id (int): The unique identifier of the job

    Request Body:
        {
            "tracks": [
                {"track_id": 1, "process": true},
                {"track_id": 2, "process": false}
            ]
        }

    Returns:
        Success message with count of updated tracks

    Example Request:
        PATCH /api/v1/jobs/123/tracks/batch
        Content-Type: application/json
        {"tracks": [{"track_id": 1, "process": true}, {"track_id": 2, "process": false}]}
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

            track = Track.query.filter_by(
                track_id=track_id,
                job_id=job_id
            ).first()

            if track:
                if 'process' in track_data:
                    track.process = bool(track_data['process'])
                if 'error' in track_data:
                    track.error = str(track_data['error']) if track_data['error'] else None
                updated_count += 1

        db.session.commit()

        # Mark job as ready to start if in manual mode
        job.manual_start = True
        db.session.commit()

        return make_response({'updated': updated_count}, f'{updated_count} tracks updated')

    except Exception as e:
        db.session.rollback()
        return error_response(f'Failed to update tracks: {str(e)}', 500)


# ==============================================================================
# METADATA ENDPOINTS
# ==============================================================================


@api.route('/metadata/search', methods=['GET'])
@api_auth_required
def search_metadata():
    """
    Search Metadata Providers

    Search OMDB/TMDB for movie/TV show information.

    Query Parameters:
        - title (str): Search title (required)
        - year (str): Release year (optional)
        - provider (str): Provider to use (omdb, tmdb, auto - default: auto)

    Returns:
        Search results from metadata provider

    Example Request:
        GET /api/v1/metadata/search?title=Matrix&year=1999
    """
    title = request.args.get('title', '').strip()
    year = request.args.get('year', '').strip()
    provider = request.args.get('provider', 'auto')

    if not title:
        return error_response('Title parameter is required', 400)

    try:
        if provider in ('auto', 'omdb'):
            results = ui_utils.metadata_selector('search', title, year)
            if results and 'Search' in results:
                return make_response(results)
            if provider == 'omdb':
                return error_response('No results found', 404)

        if provider in ('auto', 'tmdb'):
            results = ui_utils.metadata_selector('search', title, year)
            if results and 'Search' in results:
                return make_response(results)
            if provider == 'tmdb':
                return error_response('No results found', 404)

        return error_response('No results found', 404)

    except Exception as e:
        return error_response(f'Metadata search failed: {str(e)}', 500)


@api.route('/metadata/details', methods=['GET'])
@api_auth_required
def get_metadata_details():
    """
    Get Metadata Details

    Get detailed metadata for a specific title using IMDB ID.

    Query Parameters:
        - imdb_id (str): IMDB ID (required, format: tt1234567)
        - provider (str): Provider to use (omdb, tmdb, auto - default: auto)

    Returns:
        Detailed metadata including plot, poster, ratings

    Example Request:
        GET /api/v1/metadata/details?imdb_id=tt0133093
    """
    imdb_id = request.args.get('imdb_id', '').strip()
    provider = request.args.get('provider', 'auto')

    if not imdb_id:
        return error_response('imdb_id parameter is required', 400)

    try:
        results = ui_utils.metadata_selector('get_details', None, None, imdb_id)

        if results and 'Error' not in results:
            return make_response(results)

        return error_response('Could not fetch metadata details', 404)

    except Exception as e:
        return error_response(f'Metadata lookup failed: {str(e)}', 500)


@api.route('/metadata/poster', methods=['GET'])
@api_auth_required
def get_metadata_poster():
    """
    Get Poster URL

    Get the poster URL for a title.

    Query Parameters:
        - imdb_id (str): IMDB ID (optional)
        - title (str): Title (optional, requires year)
        - year (str): Release year (optional)
        - provider (str): Provider (auto, omdb, tmdb)

    Returns:
        Poster URL and metadata

    Example Request:
        GET /api/v1/metadata/poster?imdb_id=tt0133093
    """
    imdb_id = request.args.get('imdb_id', '').strip()
    title = request.args.get('title', '').strip()
    year = request.args.get('year', '').strip()
    provider = request.args.get('provider', 'auto')

    try:
        if imdb_id:
            poster_data = ui_utils.metadata_selector('get_details', None, None, imdb_id)
        elif title:
            poster_data = ui_utils.metadata_selector('search', title, year)
            if poster_data and 'Search' in poster_data and len(poster_data['Search']) > 0:
                imdb_id = poster_data['Search'][0].get('imdbID')
                if imdb_id:
                    poster_data = ui_utils.metadata_selector('get_details', None, None, imdb_id)
        else:
            return error_response('Either imdb_id or title is required', 400)

        if poster_data and 'Poster' in poster_data:
            return make_response({
                'poster_url': poster_data['Poster'],
                'title': poster_data.get('Title'),
                'imdb_id': imdb_id
            })

        return error_response('Poster not found', 404)

    except Exception as e:
        return error_response(f'Poster lookup failed: {str(e)}', 500)


# ==============================================================================
# SEND/EXPORT ENDPOINTS
# ==============================================================================


@api.route('/send/movies', methods=['POST'])
@api_auth_required
def send_movies():
    """
    Send Movies to Remote API

    Send DVD job CRC IDs to the ARM remote database API.

    Request Body (optional):
        {
            "job_ids": [1, 2, 3]  // specific jobs, or send all if omitted
        }

    Returns:
        List of job IDs that were/would be sent

    Example Request:
        POST /api/v1/send/movies
        Content-Type: application/json
        {"job_ids": [1, 2, 3]}
    """
    data = request.get_json() or {}
    job_ids = data.get('job_ids')

    try:
        if job_ids:
            job_list = Job.query.filter(
                Job.job_id.in_(job_ids),
                Job.hasnicetitle == True,
                Job.disctype == 'dvd'
            ).all()
        else:
            job_list = Job.query.filter_by(hasnicetitle=True, disctype='dvd').all()

        return_job_list = [job.job_id for job in job_list]

        # Actually send to remote API if requested
        if request.args.get('execute', 'false').lower() == 'true':
            results = []
            for job_id in return_job_list:
                try:
                    ui_utils.send_to_remote_db(job_id)
                    results.append({'job_id': job_id, 'status': 'sent'})
                except Exception as e:
                    results.append({'job_id': job_id, 'status': 'error', 'error': str(e)})
            return make_response({'results': results}, f'Sent {len([r for r in results if r["status"] == "sent"])} jobs')

        return make_response({
            'jobs': return_job_list,
            'count': len(return_job_list),
            'execute': 'Set ?execute=true to actually send to remote API'
        })

    except Exception as e:
        return error_response(f'Failed to get jobs for sending: {str(e)}', 500)


# ==============================================================================
# SETTINGS WRITE ENDPOINTS
# ==============================================================================


@api.route('/settings/arm', methods=['POST'])
@admin_required
def save_arm_settings():
    """
    Save ARM Configuration

    Update ARM configuration settings.

    Request Body:
        JSON object with ARM configuration keys and values.
        Sensitive keys (API keys, passwords) will be accepted but hidden.

    Returns:
        Success message and updated config

    Example Request:
        POST /api/v1/settings/arm
        Content-Type: application/json
        {"ARM_NAME": "My ARM", "LOGLEVEL": "DEBUG"}
    """
    import importlib

    data = request.get_json()
    if not data:
        return error_response('Request body must be JSON', 400)

    try:
        # Get comments for arm.yaml
        comments = ui_utils.generate_comments()

        # Build new config
        arm_cfg = ui_utils.build_arm_cfg(data, comments)

        # Save to file
        with open(cfg.arm_config_path, 'w') as f:
            f.write(arm_cfg)

        # Reload config
        importlib.reload(cfg)

        return make_response(cfg.arm_config, 'ARM settings saved successfully. Restart required for some changes.')

    except Exception as e:
        return error_response(f'Failed to save settings: {str(e)}', 500)


@api.route('/settings/abcde', methods=['POST'])
@admin_required
def save_abcde_settings():
    """
    Save ABCDE Configuration

    Update ABCDE (audio CD ripper) configuration.

    Request Body:
        {
            "config": "完整的abcde.conf内容..."
        }

    Returns:
        Success message

    Example Request:
        POST /api/v1/settings/abcde
        Content-Type: application/json
        {"config": "abcde.conf 内容..."}
    """
    data = request.get_json()
    if not data or 'config' not in data:
        return error_response('Request body must contain "config" field', 400)

    try:
        abcde_cfg_str = data['config']
        # Clean Windows line endings
        clean_cfg = '\n'.join(abcde_cfg_str.splitlines())

        with open(cfg.abcde_config_path, 'w') as f:
            f.write(clean_cfg)

        cfg.abcde_config = clean_cfg

        return make_response(None, 'ABCDE config saved successfully')

    except Exception as e:
        return error_response(f'Failed to save ABCDE config: {str(e)}', 500)


@api.route('/settings/apprise', methods=['POST'])
@admin_required
def save_apprise_settings():
    """
    Save Apprise Configuration

    Update Apprise notification configuration.

    Request Body:
        JSON object with apprise configuration keys and values.

    Returns:
        Success message

    Example Request:
        POST /api/v1/settings/apprise
        Content-Type: application/json
        {"tvs://emby_server:emby_port/"}
    """
    import importlib

    data = request.get_json()
    if not data:
        return error_response('Request body must be JSON', 400)

    try:
        # Build new apprise config
        apprise_cfg = ui_utils.build_apprise_cfg(data)

        with open(cfg.apprise_config_path, 'w') as f:
            f.write(apprise_cfg)

        importlib.reload(cfg)

        return make_response(cfg.apprise_config, 'Apprise config saved successfully')

    except Exception as e:
        return error_response(f'Failed to save Apprise config: {str(e)}', 500)


# ==============================================================================
# DRIVE MANAGEMENT ENDPOINTS
# ==============================================================================


@api.route('/system/drives/<int:drive_id>/remove', methods=['DELETE'])
@admin_required
def remove_drive(drive_id):
    """
    Remove Drive

    Remove a drive from the ARM database.

    Path Parameters:
        - drive_id (int): The unique identifier of the drive

    Returns:
        Success message

    Example Request:
        DELETE /api/v1/system/drives/1/remove
    """
    try:
        drive = SystemDrives.query.filter_by(drive_id=drive_id).first()

        if not drive:
            return error_response(f'Drive {drive_id} not found', 404)

        dev_path = drive.mount
        SystemDrives.query.filter_by(drive_id=drive_id).delete()
        db.session.commit()

        return make_response(None, f'Drive {dev_path} removed from ARM')

    except Exception as e:
        db.session.rollback()
        return error_response(f'Failed to remove drive: {str(e)}', 500)


@api.route('/system/drives/<int:drive_id>/start', methods=['POST'])
@admin_required
def manual_start_job(drive_id):
    """
    Manually Start Job

    Manually start a ripping job on a specific drive.

    Path Parameters:
        - drive_id (int): The unique identifier of the drive

    Returns:
        Success or error message

    Example Request:
        POST /api/v1/system/drives/1/start
    """
    import subprocess

    try:
        drive = SystemDrives.query.filter_by(drive_id=drive_id).first()

        if not drive:
            return error_response(f'Drive {drive_id} not found', 404)

        dev_path = drive.mount.lstrip('/dev/')

        cmd = os.path.join(
            cfg.arm_config['INSTALLPATH'],
            f'scripts/docker/docker_arm_wrapper.sh {dev_path}'
        )

        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd, output=stdout, stderr=stderr)

        return make_response({'output': stdout}, f'Manually started job on drive {drive.name}')

    except subprocess.CalledProcessError as e:
        return error_response(f'Failed to start job: {e.stderr}', 500)
    except Exception as e:
        return error_response(f'Failed to start job: {str(e)}', 500)


@api.route('/system/drives/scan', methods=['POST'])
@admin_required
def scan_drives():
    """
    Scan for Drives

    Scan the system for optical drives and update the database.

    Returns:
        Number of new drives found

    Example Request:
        POST /api/v1/system/drives/scan
    """
    try:
        new_count = drive_utils.drives_update()
        return make_response({'new_drives': new_count}, f'Found {new_count} new drives')

    except Exception as e:
        return error_response(f'Failed to scan drives: {str(e)}', 500)


@api.route('/system/drives/<int:drive_id>', methods=['PATCH'])
@admin_required
def update_drive(drive_id):
    """
    Update Drive

    Update drive information (name, description, mode).

    Path Parameters:
        - drive_id (int): The unique identifier of the drive

    Request Body:
        {
            "name": "Primary Blu-ray",
            "description": "Main ripping drive",
            "drive_mode": "auto"
        }

    Returns:
        Updated drive information

    Example Request:
        PATCH /api/v1/system/drives/1
        Content-Type: application/json
        {"name": "Primary Blu-ray", "drive_mode": "manual"}
    """
    drive = SystemDrives.query.filter_by(drive_id=drive_id).first()

    if not drive:
        return error_response(f'Drive {drive_id} not found', 404)

    data = request.get_json()
    if not data:
        return error_response('Request body must be JSON', 400)

    try:
        if 'name' in data:
            drive.name = str(data['name']).strip()
        if 'description' in data:
            drive.description = str(data['description']).strip()
        if 'drive_mode' in data:
            drive.drive_mode = str(data['drive_mode']).strip()

        db.session.commit()

        return make_response(drive_to_dict(drive), 'Drive updated successfully')

    except Exception as e:
        db.session.rollback()
        return error_response(f'Failed to update drive: {str(e)}', 500)


# ==============================================================================
# DATABASE ENDPOINTS
# ==============================================================================


@api.route('/database', methods=['GET'])
@api_auth_required
def get_database_info():
    """
    Get Database Information

    Retrieve database status and information.

    Returns:
        Database information including version, existence status
    """
    try:
        db_update = ui_utils.arm_db_check()

        return make_response({
            'exists': db_update.get('db_exists', False),
            'current': db_update.get('db_current', False),
            'version': db_update.get('db_version', None),
            'required_version': db_update.get('db_required_version', None)
        })

    except Exception as e:
        return error_response(f'Failed to get database info: {str(e)}', 500)


@api.route('/database/update', methods=['POST'])
@admin_required
def update_database():
    """
    Update Database

    Run database migrations to update schema.

    Returns:
        Success message

    Example Request:
        POST /api/v1/database/update
    """
    try:
        from arm.ui.utils import arm_db_migrate

        success = arm_db_migrate()

        if success:
            return make_response(None, 'Database updated successfully')
        else:
            return error_response('Database update failed', 500)

    except Exception as e:
        return error_response(f'Database update failed: {str(e)}', 500)


@api.route('/database/import', methods=['POST'])
@admin_required
def import_movies():
    """
    Import Movies

    Import missing movie information from disc metadata.

    Request Body (optional):
        {
            "job_ids": [1, 2, 3]  // specific jobs, or all if omitted
        }

    Returns:
        Import results

    Example Request:
        POST /api/v1/database/import
        Content-Type: application/json
        {"job_ids": [1, 2, 3]}
    """
    from arm.ui.utils import import_movie_add

    data = request.get_json() or {}
    job_ids = data.get('job_ids')

    try:
        if job_ids:
            jobs = Job.query.filter(Job.job_id.in_(job_ids)).all()
        else:
            jobs = Job.query.filter(
                Job.hasnicetitle == True,
                Job.disctype == 'dvd'
            ).all()

        results = []
        for job in jobs:
            try:
                poster = job.poster_url if job.poster_url else None
                my_path = ui_utils.find_folder_in_log(job.logfile, cfg.arm_config['COMPLETED_PATH'])
                if my_path:
                    result = import_movie_add(poster, job.imdb_id, job.video_type, my_path)
                    results.append({'job_id': job.job_id, 'status': 'imported' if result else 'skipped'})
            except Exception as e:
                results.append({'job_id': job.job_id, 'status': 'error', 'error': str(e)})

        return make_response({'results': results}, f'Imported {len([r for r in results if r["status"] == "imported"])} movies')

    except Exception as e:
        return error_response(f'Import failed: {str(e)}', 500)


# ==============================================================================
# SYSTEM ENDPOINTS
# ==============================================================================


@api.route('/system/sysinfo', methods=['POST'])
@admin_required
def update_system_info():
    """
    Update System Information

    Refresh system information in the database.

    Returns:
        Success message

    Example Request:
        POST /api/v1/system/sysinfo
    """
    try:
        current_system = SystemInfo.query.first()
        new_system = SystemInfo()

        if current_system:
            current_system.name = new_system.name
            current_system.cpu = new_system.cpu
            current_system.mem_total = new_system.mem_total
            db.session.add(current_system)
        else:
            db.session.add(new_system)

        db.session.commit()

        return make_response(None, 'System info updated')

    except Exception as e:
        db.session.rollback()
        return error_response(f'Failed to update system info: {str(e)}', 500)


@api.route('/system/test-apprise', methods=['POST'])
@admin_required
def test_apprise():
    """
    Test Apprise Notification

    Send a test notification via Apprise.

    Returns:
        Success message

    Example Request:
        POST /api/v1/system/test-apprise
    """
    from arm.ripper import utils as ripper_utils

    try:
        message = 'ARM API Test Notification'
        if cfg.arm_config.get('UI_BASE_URL') and cfg.arm_config.get('WEBSERVER_PORT'):
            message += f' Server URL: http://{cfg.arm_config["UI_BASE_URL"]}:{cfg.arm_config["WEBSERVER_PORT"]}'

        ripper_utils.notify(None, 'ARM notification', message)

        return make_response(None, 'Test notification sent')

    except Exception as e:
        return error_response(f'Failed to send test notification: {str(e)}', 500)


@api.route('/system/restart', methods=['POST'])
@admin_required
def restart_arm():
    """
    Restart ARM UI

    Restart the ARM web interface.

    Returns:
        Success message (UI will restart after this)

    Example Request:
        POST /api/v1/system/restart
    """
    import subprocess

    try:
        subprocess.Popen('pkill python3', shell=True)
        return make_response(None, 'ARM restart initiated')

    except Exception as e:
        return error_response(f'Failed to restart ARM: {str(e)}', 500)


# ==============================================================================
# USER ENDPOINTS
# ==============================================================================


@api.route('/user/status', methods=['GET'])
@api_auth_required
def get_user_status():
    """
    Get Current User Status

    Get information about the currently authenticated user.

    Returns:
        User information
    """
    user = g.user if hasattr(g, 'user') and g.user != 'api_key_auth' else current_user

    if user and user.is_authenticated:
        return make_response({
            'authenticated': True,
            'email': user.email,
            'user_id': user.user_id
        })

    # API key auth
    return make_response({
        'authenticated': True,
        'method': 'api_key',
        'email': None
    })


@api.route('/user/password', methods=['POST'])
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

    Returns:
        Success message

    Example Request:
        POST /api/v1/user/password
        Content-Type: application/json
        {"old_password": "old", "new_password": "new"}
    """
    import bcrypt

    data = request.get_json()
    if not data or 'old_password' not in data or 'new_password' not in data:
        return error_response('old_password and new_password are required', 400)

    user = User.query.first()
    if not user:
        return error_response('No user found', 404)

    try:
        old_pw = data['old_password'].strip().encode('utf-8')
        new_pw = data['new_password'].strip().encode('utf-8')

        # Verify old password
        login_hashed = bcrypt.hashpw(old_pw, user.hash)
        if login_hashed != user.password:
            return error_response('Current password is incorrect', 401)

        # Set new password
        hashed = bcrypt.gensalt()
        user.password = bcrypt.hashpw(new_pw, hashed)
        user.hash = hashed
        db.session.commit()

        return make_response(None, 'Password updated successfully. Please log in again.')

    except Exception as e:
        db.session.rollback()
        return error_response(f'Failed to change password: {str(e)}', 500)


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
