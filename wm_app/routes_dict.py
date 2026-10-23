from flask import Blueprint, current_app, jsonify

from .security.http import api_endpoint
from .services import dictionary, dictionary_promotions, word_ranges
from .services.errors import ApiError
from .services.pagination import ListQuery

bp = Blueprint('dicts', __name__)


@bp.get('/api/dicts')
@api_endpoint()
def api_get_dicts(data, user):
    return jsonify(success=True, **dictionary.list_dictionaries(user, ListQuery.parse(data)))


@bp.get('/api/dict/<int:dict_id>')
@api_endpoint()
def api_get_dict(data, user, dict_id):
    return jsonify(
        success=True,
        dict=dictionary.get_dictionary(user, dict_id),
        csv_limits={
            'max_bytes': current_app.config['CSV_MAX_BYTES'],
            'max_rows': current_app.config['CSV_MAX_ROWS'],
        },
    )


@bp.post('/api/dict')
@api_endpoint()
def api_create_dict(data, user):
    if set(data) - {'dictname', 'multiplier'}:
        raise ApiError('Only dictname and multiplier may be provided')
    return jsonify(
        success=True,
        **dictionary.create_dictionary(
            user['id'], data.get('dictname'), data.get('multiplier', '1.00')
        ),
    ), 201


@bp.put('/api/dict/<int:dict_id>')
@api_endpoint()
def api_update_dict(data, user, dict_id):
    if set(data) != {'dictname'}:
        raise ApiError('Use the reviewed multiplier endpoint to change multiplier configuration')
    return jsonify(
        success=True, **dictionary.update_dictionary(user['id'], dict_id, data.get('dictname'))
    )


@bp.put('/api/dict/<int:dict_id>/multiplier')
@api_endpoint()
def api_set_multiplier(data, user, dict_id):
    return jsonify(success=True, **dictionary.set_multiplier(user['id'], dict_id, data))


@bp.put('/api/dict/<int:dict_id>/difficulty')
@api_endpoint()
def api_set_difficulty(data, user, dict_id):
    return jsonify(success=True, **dictionary.set_difficulty(user['id'], dict_id, data))


@bp.get('/api/dictionary-promotions')
@api_endpoint()
def api_dictionary_promotions(data, user):
    return jsonify(success=True, **dictionary_promotions.listing(user['id'], ListQuery.parse(data)))


@bp.post('/api/dict/<int:dict_id>/promotions')
@api_endpoint()
def api_submit_promotion(data, user, dict_id):
    return jsonify(success=True, **dictionary_promotions.submit(user['id'], dict_id, data)), 201


@bp.get('/api/dict/<int:dict_id>/promotions/<request_id>')
@api_endpoint()
def api_review_promotion(data, user, dict_id, request_id):
    return jsonify(success=True, **dictionary_promotions.review(user['id'], dict_id, request_id))


@bp.post('/api/dict/<int:dict_id>/promotions/<request_id>')
@api_endpoint(root=True)
def api_decide_promotion(data, user, dict_id, request_id):
    return jsonify(
        success=True, **dictionary_promotions.decide(user['id'], dict_id, request_id, data)
    )


@bp.put('/api/dict/<int:dict_id>/rated-bounds')
@api_endpoint(root=True)
def api_set_rated_bounds(data, user, dict_id):
    return jsonify(success=True, **dictionary.set_rated_bounds(user['id'], dict_id, data))


@bp.delete('/api/dict/<int:dict_id>')
@api_endpoint()
def api_delete_dict(data, user, dict_id):
    return jsonify(success=True, **dictionary.delete_dictionary(user['id'], dict_id))


@bp.get('/api/dict/<int:dict_id>/words')
@api_endpoint()
def api_get_words(data, user, dict_id):
    return jsonify(success=True, **dictionary.get_words(dict_id, ListQuery.parse(data)))


@bp.post('/api/dict/<int:dict_id>/words/delete-range/preview')
@api_endpoint()
def api_preview_word_range(data, user, dict_id):
    return jsonify(success=True, **word_ranges.preview(user['id'], dict_id, data))


@bp.post('/api/dict/<int:dict_id>/words/delete-range')
@api_endpoint()
def api_delete_word_range(data, user, dict_id):
    return jsonify(success=True, **word_ranges.delete(user['id'], dict_id, data))


@bp.post('/api/dict/<int:dict_id>/word')
@api_endpoint()
def api_create_word(data, user, dict_id):
    return jsonify(
        success=True,
        **dictionary.create_word(user['id'], dict_id, data.get('english'), data.get('chinese')),
    ), 201


@bp.put('/api/word/<int:word_id>')
@api_endpoint()
def api_update_word(data, user, word_id):
    return jsonify(
        success=True,
        **dictionary.update_word(user['id'], word_id, data.get('english'), data.get('chinese')),
    )


@bp.delete('/api/word/<int:word_id>')
@api_endpoint()
def api_delete_word(data, user, word_id):
    return jsonify(success=True, **dictionary.delete_word(user['id'], word_id))


@bp.post('/api/dict/<int:dict_id>/import-csv')
@api_endpoint()
def api_import_csv(data, user, dict_id):
    return jsonify(success=True, **dictionary.import_csv(user['id'], dict_id, data.get('csv')))


@bp.get('/api/dict/<int:dict_id>/export-csv')
@api_endpoint()
def api_export_csv(data, user, dict_id):
    return jsonify(success=True, **dictionary.export_csv(dict_id))
