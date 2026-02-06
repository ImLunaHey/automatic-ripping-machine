"""
ARM REST API Blueprint - Main Aggregator

This module provides a comprehensive REST API for the Automatic Ripping Machine,
enabling external applications to interact with ARM programmatically.

Base URL: /api/v1

Authentication:
- Session-based or Bearer token (ARM_API_KEY from config)

Content Type:
- All responses are JSON (application/json)
- Request bodies should be JSON (application/json)

Response Format:
{
    "success": true,
    "data": {...},
    "message": "Optional human-readable message"
}

For full documentation, see API.md or visit /api/v1/docs (Swagger UI)

Endpoints by Domain:
- jobs: /api/v1/jobs
- tracks: /api/v1/tracks
- system: /api/v1/system
- settings: /api/v1/settings
- metadata: /api/v1/metadata
- notifications: /api/v1/notifications
- logs: /api/v1/logs
- history: /api/v1/history
- send: /api/v1/send
- database: /api/v1/database
- user: /api/v1/user
"""

from flask import Blueprint
from flask_cors import CORS

# Create main API blueprint
api = Blueprint('api', __name__, url_prefix='/api/v1')

# Enable CORS for API
CORS(api)

# Import and register all API modules
from arm.ui.api import jobs  # noqa: F401
from arm.ui.api import tracks  # noqa: F401
from arm.ui.api import system  # noqa: F401
from arm.ui.api import settings  # noqa: F401
from arm.ui.api import metadata  # noqa: F401
from arm.ui.api import notifications  # noqa: F401
from arm.ui.api import logs  # noqa: F401
from arm.ui.api import history  # noqa: F401
from arm.ui.api import send  # noqa: F401
from arm.ui.api import database  # noqa: F401
from arm.ui.api import user  # noqa: F401

# Register sub-blueprints
api.register_blueprint(jobs.api)
api.register_blueprint(tracks.api)
api.register_blueprint(system.api)
api.register_blueprint(settings.api)
api.register_blueprint(metadata.api)
api.register_blueprint(notifications.api)
api.register_blueprint(logs.api)
api.register_blueprint(history.api)
api.register_blueprint(send.api)
api.register_blueprint(database.api)
api.register_blueprint(user.api)


# ==============================================================================
# COMMON IMPORTS & UTILITIES
# ==============================================================================

import os
import psutil
import platform
import subprocess
import re
import bcrypt
from datetime import datetime
from functools import wraps
from flask import request, jsonify, g, current_app
from flask_login import current_user
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


def api_auth_required(f):
    """Decorator for API authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.is_authenticated:
            g.user = current_user
            return f(*args, **kwargs)

        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            api_key = auth_header[7:]
            valid_key = cfg.arm_config.get('ARM_API_KEY', '')
            if api_key == valid_key and valid_key:
                g.user = 'api_key_auth'
                return f(*args, **kwargs)

        api_key_param = request.args.get('api_key')
        if api_key_param:
            valid_key = cfg.arm_config.get('ARM_API_KEY', '')
            if api_key_param == valid_key and valid_key:
                g.user = 'api_key_auth'
                return f(*args, **kwargs)

        return jsonify({
            'success': False,
            'error': 'Authentication required',
            'message': 'Please login or provide a valid API key'
        }), 401

    return decorated


def admin_required(f):
    """Decorator requiring admin privileges."""
    @wraps(f)
    def decorated(*args, **kwargs):
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
                'message': 'This endpoint requires admin privileges'
            }), 403

        return f(*args, **kwargs)

    return decorated


def make_response(data, message=None, status_code=200):
    """Standard API response builder."""
    response = {
        'success': 200 <= status_code < 300,
        'data': data
    }
    if message:
        response['message'] = message
    return jsonify(response), status_code


def error_response(message, status_code=400, errors=None):
    """Standard error response builder."""
    response = {
        'success': False,
        'error': message,
        'message': message
    }
    if errors:
        response['errors'] = errors
    return jsonify(response), status_code


def paginate_query(query, page=1, per_page=20):
    """Paginate a SQLAlchemy query."""
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
    """Convert Job model to dictionary."""
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
    """Convert Track model to dictionary."""
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
    """Convert Config model to dictionary (sanitized)."""
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
    """Convert SystemDrives model to dictionary."""
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


@api.route('/', methods=['GET'])
def api_index():
    """API Index - returns metadata and available endpoints."""
    return make_response({
        'name': 'ARM API',
        'version': '2.0.0',
        'description': 'Automatic Ripping Machine REST API',
        'endpoints': {
            'jobs': '/api/v1/jobs',
            'tracks': '/api/v1/tracks',
            'system': '/api/v1/system',
            'settings': '/api/v1/settings',
            'metadata': '/api/v1/metadata',
            'notifications': '/api/v1/notifications',
            'logs': '/api/v1/logs',
            'history': '/api/v1/history',
            'send': '/api/v1/send',
            'database': '/api/v1/database',
            'user': '/api/v1/user'
        }
    })


@api.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return error_response('Resource not found', 404)


@api.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    app.logger.error(f'API Error: {error}')
    return error_response('Internal server error', 500)
