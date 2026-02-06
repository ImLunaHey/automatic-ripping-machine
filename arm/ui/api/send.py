"""
Send/Export API Endpoints

Endpoints for sending data to external APIs.
"""

from flask import Blueprint, request

from arm.ui.api import api_auth_required, make_response, error_response, Job

api = Blueprint('send', __name__, url_prefix='/send')


@api.route('/movies', methods=['POST'])
@api_auth_required
def send_movies():
    """
    Send Movies to Remote API

    Send DVD job CRC IDs to the ARM remote database API.

    Request Body (optional):
        {
            "job_ids": [1, 2, 3]
        }

    Query Parameters:
        - execute (bool): Set to "true" to actually send (default: false)
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
            from arm.ui.api import ui_utils
            results = []
            for job_id in return_job_list:
                try:
                    ui_utils.send_to_remote_db(job_id)
                    results.append({'job_id': job_id, 'status': 'sent'})
                except Exception as e:
                    results.append({'job_id': job_id, 'status': 'error', 'error': str(e)})
            sent_count = len([r for r in results if r['status'] == 'sent'])
            return make_response({'results': results}, f'Sent {sent_count} jobs')

        return make_response({
            'jobs': return_job_list,
            'count': len(return_job_list),
            'execute': 'Set ?execute=true to actually send to remote API'
        })

    except Exception as e:
        return error_response(f'Failed to get jobs for sending: {str(e)}', 500)
