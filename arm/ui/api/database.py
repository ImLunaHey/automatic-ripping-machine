"""
Database API Endpoints

Endpoints for database operations.
"""

from flask import Blueprint, request

from arm.ui.api import api_auth_required, admin_required, make_response, error_response, Job, cfg

api = Blueprint('database', __name__, url_prefix='/database')


@api.route('', methods=['GET'])
@api_auth_required
def get_database_info():
    """
    Get Database Information

    Retrieve database status and information.
    """
    from arm.ui.api import ui_utils
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


@api.route('/update', methods=['POST'])
@admin_required
def update_database():
    """
    Update Database

    Run database migrations to update schema.
    """
    try:
        from arm.ui.api import ui_utils
        success = ui_utils.arm_db_migrate()
        if success:
            return make_response(None, 'Database updated successfully')
        return error_response('Database update failed', 500)
    except Exception as e:
        return error_response(f'Database update failed: {str(e)}', 500)


@api.route('/import', methods=['POST'])
@admin_required
def import_movies():
    """
    Import Movies

    Import missing movie information from disc metadata.

    Request Body (optional):
        {
            "job_ids": [1, 2, 3]
        }
    """
    from arm.ui.api import ui_utils
    data = request.get_json() or {}
    job_ids = data.get('job_ids')

    try:
        if job_ids:
            jobs = Job.query.filter(Job.job_id.in_(job_ids)).all()
        else:
            jobs = Job.query.filter(Job.hasnicetitle == True, Job.disctype == 'dvd').all()

        results = []
        for job in jobs:
            try:
                poster = job.poster_url if job.poster_url else None
                my_path = ui_utils.find_folder_in_log(job.logfile, cfg.arm_config['COMPLETED_PATH'])
                if my_path:
                    result = ui_utils.import_movie_add(poster, job.imdb_id, job.video_type, my_path)
                    results.append({'job_id': job.job_id, 'status': 'imported' if result else 'skipped'})
            except Exception as e:
                results.append({'job_id': job.job_id, 'status': 'error', 'error': str(e)})

        imported_count = len([r for r in results if r['status'] == 'imported'])
        return make_response({'results': results}, f'Imported {imported_count} movies')
    except Exception as e:
        return error_response(f'Import failed: {str(e)}', 500)
