"""
System API Endpoints

Endpoints for system information, drives, and status.
"""

from flask import Blueprint, request

from arm.ui.api import (
    api_auth_required, admin_required, make_response, error_response,
    drive_to_dict, SystemInfo, SystemDrives, db, psutil, platform, cfg
)

api = Blueprint('system', __name__, url_prefix='/system')


@api.route('/info', methods=['GET'])
@api_auth_required
def get_system_info():
    """
    Get System Information

    Retrieve server/system information including CPU, memory, and ARM details.
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


@api.route('/status', methods=['GET'])
def get_system_status():
    """
    Get System Status

    Retrieve current system status including drive usage and resource usage.
    This endpoint is public (no authentication required).
    """
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(cfg.arm_config.get('COMPLETED_PATH', '/'))

    active_jobs = Job.query.filter(~Job.finished).count()

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


@api.route('/drives', methods=['GET'])
@api_auth_required
def get_drives():
    """
    List System Drives

    Retrieve information about all configured optical drives.

    Query Parameters:
        - include_jobs (bool): Include current job information (default: true)
    """
    include_jobs = request.args.get('include_jobs', 'true').lower() == 'true'

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


@api.route('/drives/<int:drive_id>', methods=['GET'])
@api_auth_required
def get_drive(drive_id):
    """
    Get Drive Details

    Retrieve detailed information about a specific drive.
    """
    drive = SystemDrives.query.get(drive_id)
    if not drive:
        return error_response(f'Drive with ID {drive_id} not found', 404)
    return make_response(drive_to_dict(drive))


@api.route('/drives/<int:drive_id>/eject', methods=['POST'])
@api_auth_required
def eject_drive(drive_id):
    """
    Eject Drive

    Toggle the eject status of a drive.
    """
    drive = SystemDrives.query.get(drive_id)
    if not drive:
        return error_response(f'Drive with ID {drive_id} not found', 404)

    if drive.job_id_current:
        if not drive.open:
            return error_response(f'Job {drive.job_id_current} in progress. Cannot eject.', 400)

    error = drive.eject(method="toggle", logger=app.logger)
    if error:
        return error_response(error, 400)

    return make_response(None, 'Drive ejected successfully')


@api.route('/drives/<int:drive_id>', methods=['PATCH'])
@api_auth_required
@admin_required
def update_drive(drive_id):
    """
    Update Drive

    Update drive information (name, description, mode).

    Request Body:
        {
            "name": "Primary Blu-ray",
            "description": "Main ripping drive",
            "drive_mode": "auto"
        }
    """
    drive = SystemDrives.query.get(drive_id)
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


@api.route('/drives/<int:drive_id>/remove', methods=['DELETE'])
@api_auth_required
@admin_required
def remove_drive(drive_id):
    """
    Remove Drive

    Remove a drive from the ARM database.
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


@api.route('/drives/<int:drive_id>/start', methods=['POST'])
@api_auth_required
@admin_required
def manual_start_job(drive_id):
    """
    Manually Start Job

    Manually start a ripping job on a specific drive.
    """
    drive = SystemDrives.query.filter_by(drive_id=drive_id).first()
    if not drive:
        return error_response(f'Drive {drive_id} not found', 404)

    dev_path = drive.mount.lstrip('/dev/')
    cmd = os.path.join(cfg.arm_config['INSTALLPATH'], f"scripts/docker/docker_arm_wrapper.sh {dev_path}")

    try:
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd, output=stdout, stderr=stderr)

        return make_response({'output': stdout}, f'Manually started job on drive {drive.name}')
    except subprocess.CalledProcessError as e:
        return error_response(f'Failed to start job: {e.stderr}', 500)
    except Exception as e:
        return error_response(f'Failed to start job: {str(e)}', 500)


@api.route('/drives/scan', methods=['POST'])
@api_auth_required
@admin_required
def scan_drives():
    """
    Scan for Drives

    Scan the system for optical drives and update the database.
    """
    try:
        new_count = drive_utils.drives_update()
        return make_response({'new_drives': new_count}, f'Found {new_count} new drives')
    except Exception as e:
        return error_response(f'Failed to scan drives: {str(e)}', 500)


@api.route('/sysinfo', methods=['POST'])
@admin_required
def update_system_info():
    """
    Update System Information

    Refresh system information in the database.
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


@api.route('/test-apprise', methods=['POST'])
@admin_required
def test_apprise():
    """
    Test Apprise Notification

    Send a test notification via Apprise.
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


@api.route('/restart', methods=['POST'])
@admin_required
def restart_arm():
    """
    Restart ARM UI

    Restart the ARM web interface.
    """
    try:
        subprocess.Popen('pkill python3', shell=True)
        return make_response(None, 'ARM restart initiated')
    except Exception as e:
        return error_response(f'Failed to restart ARM: {str(e)}', 500)


# Import needed dependencies
from arm.ui.api import (
    Job, app, os, subprocess, datetime, drive_utils
)

# Import git hash function
from arm.ui.api import get_git_hash
