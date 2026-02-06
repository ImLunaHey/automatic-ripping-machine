"""
Settings API Endpoints

Endpoints for reading and modifying ARM configuration.
"""

from flask import Blueprint, request

from arm.ui.api import (
    api_auth_required, admin_required, make_response, error_response,
    UISettings, db, cfg, importlib
)

api = Blueprint('settings', __name__, url_prefix='/settings')


@api.route('', methods=['GET'])
@api_auth_required
def get_settings():
    """
    Get ARM Settings

    Retrieve all ARM configuration settings.
    Sensitive values are hidden.
    """
    settings = {}
    hidden_keys = ('OMDB_API_KEY', 'EMBY_USERID', 'EMBY_PASSWORD', 'EMBY_API_KEY',
                   'PB_KEY', 'IFTTT_KEY', 'PO_KEY', 'PO_USER_KEY', 'PO_APP_KEY',
                   'ARM_API_KEY', 'TMDB_API_KEY')
    for key, value in cfg.arm_config.items():
        settings[key] = '<hidden>' if key in hidden_keys else value
    return make_response(settings)


@api.route('/ui', methods=['GET'])
@api_auth_required
def get_ui_settings():
    """
    Get UI Settings

    Retrieve ARM UI configuration settings from database.
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


@api.route('/ui', methods=['PATCH'])
@api_auth_required
@admin_required
def update_ui_settings():
    """
    Update UI Settings

    Update ARM UI configuration settings.

    Request Body:
        {
            "use_icons": true,
            "save_remote_images": false,
            "bootstrap_skin": "darkly",
            "language": "en",
            "index_refresh": 5,
            "database_limit": 100,
            "notify_refresh": 6500
        }
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


@api.route('/abcde', methods=['GET'])
@api_auth_required
def get_abcde_config():
    """
    Get ABCDE Configuration

    Retrieve the ABCDE (audio CD ripper) configuration.
    """
    return make_response({'config': cfg.abcde_config})


@api.route('/abcde', methods=['POST'])
@api_auth_required
@admin_required
def save_abcde_settings():
    """
    Save ABCDE Configuration

    Update ABCDE (audio CD ripper) configuration.

    Request Body:
        {
            "config": "完整的abcde.conf内容..."
        }
    """
    data = request.get_json()
    if not data or 'config' not in data:
        return error_response('Request body must contain "config" field', 400)

    try:
        abcde_cfg_str = data['config']
        clean_cfg = '\n'.join(abcde_cfg_str.splitlines())

        with open(cfg.abcde_config_path, 'w') as f:
            f.write(clean_cfg)

        cfg.abcde_config = clean_cfg
        return make_response(None, 'ABCDE config saved successfully')
    except Exception as e:
        return error_response(f'Failed to save ABCDE config: {str(e)}', 500)


@api.route('/apprise', methods=['GET'])
@api_auth_required
def get_apprise_config():
    """
    Get Apprise Configuration

    Retrieve the Apprise notification configuration.
    Sensitive values are hidden.
    """
    apprise_cfg = {}
    hidden = ('password', 'token', 'key', 'secret')
    for key, value in cfg.apprise_config.items():
        if any(h in key.lower() for h in hidden):
            apprise_cfg[key] = '<hidden>'
        else:
            apprise_cfg[key] = value
    return make_response(apprise_cfg)


@api.route('/apprise', methods=['POST'])
@api_auth_required
@admin_required
def save_apprise_settings():
    """
    Save Apprise Configuration

    Update Apprise notification configuration.

    Request Body:
        JSON object with apprise configuration.
    """
    data = request.get_json()
    if not data:
        return error_response('Request body must be JSON', 400)

    try:
        from arm.ui.api import ui_utils
        apprise_cfg = ui_utils.build_apprise_cfg(data)

        with open(cfg.apprise_config_path, 'w') as f:
            f.write(apprise_cfg)

        importlib.reload(cfg)
        return make_response(cfg.apprise_config, 'Apprise config saved successfully')
    except Exception as e:
        return error_response(f'Failed to save Apprise config: {str(e)}', 500)


@api.route('/arm', methods=['POST'])
@admin_required
def save_arm_settings():
    """
    Save ARM Configuration

    Update ARM configuration settings.

    Request Body:
        JSON object with ARM configuration keys and values.
    """
    data = request.get_json()
    if not data:
        return error_response('Request body must be JSON', 400)

    try:
        from arm.ui.api import ui_utils
        comments = ui_utils.generate_comments()
        arm_cfg = ui_utils.build_arm_cfg(data, comments)

        with open(cfg.arm_config_path, 'w') as f:
            f.write(arm_cfg)

        importlib.reload(cfg)
        return make_response(cfg.arm_config, 'ARM settings saved successfully. Restart required for some changes.')
    except Exception as e:
        return error_response(f'Failed to save settings: {str(e)}', 500)
