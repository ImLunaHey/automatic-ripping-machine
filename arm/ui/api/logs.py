"""
Logs API Endpoints

Endpoints for viewing ARM log files.
"""

from flask import Blueprint, request

from arm.ui.api import api_auth_required, make_response, error_response, cfg, os

api = Blueprint('logs', __name__, url_prefix='/logs')


@api.route('', methods=['GET'])
@api_auth_required
def list_logs():
    """
    List Log Files

    Retrieve information about available log files.

    Query Parameters:
        - job_id (int): Filter logs by job ID
        - limit (int): Maximum number of logs to return
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


@api.route('/<path:filename>', methods=['GET'])
@api_auth_required
def get_log(filename):
    """
    Get Log File Contents

    Retrieve the contents of a specific log file.

    Query Parameters:
        - lines (int): Maximum number of lines to return (default: 100)
        - offset (int): Start from this line number (default: 0)
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


@api.route('/job/<int:job_id>', methods=['GET'])
@api_auth_required
def get_job_log(job_id):
    """
    Get Job Log

    Retrieve the log file for a specific job.
    """
    from arm.ui.api import Job
    job = Job.query.get(job_id)

    if not job or not job.logfile:
        return error_response(f'Job {job_id} or log file not found', 404)

    return get_log(job.logfile)


# Import datetime for timestamp
from datetime import datetime
