"""
Metadata API Endpoints

Endpoints for searching and retrieving metadata from OMDB/TMDB.
"""

from flask import Blueprint, request

from arm.ui.api import api_auth_required, make_response, error_response, ui_utils

api = Blueprint('metadata', __name__, url_prefix='/metadata')


@api.route('/search', methods=['GET'])
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


@api.route('/details', methods=['GET'])
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


@api.route('/poster', methods=['GET'])
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
                found_imdb_id = poster_data['Search'][0].get('imdbID')
                if found_imdb_id:
                    imdb_id = found_imdb_id
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
