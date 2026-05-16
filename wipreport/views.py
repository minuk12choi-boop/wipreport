import json
import logging

from django.conf import settings
from django.db import OperationalError, ProgrammingError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .models import WipRefExclusionTypeRule, WipRefHotLotRule, WipRefModuleRule, WipRefProductRule
from .services import build_summary, get_latest_loaded_at, make_json_safe

logger = logging.getLogger(__name__)


def wip_root(request):
    return redirect('wip-summary')


def _base_context():
    return {"latest_loaded_at": get_latest_loaded_at()}


def summary_page(request):
    return render(request, 'wipreport/summary.html', _base_context())



def _rows_with_columns(qs, columns):
    return [{'values': [row.get(c, '') for c in columns]} for row in qs.values(*columns)]

def _build_ref_sections(product_rules, module_rules, exclusion_rules, hot_rules):
    return [
        {
            'key': 'product',
            'title': '제품구분자 설정',
            'description': 'LOT 문자열 기준 제품구분 규칙',
            'columns': ['lot_char_1', 'lot_char_2', 'lot_char_3', 'lot_char_4', 'lot_char_5', 'processed', 'product_name'],
            'rows': _rows_with_columns(product_rules, ['lot_char_1', 'lot_char_2', 'lot_char_3', 'lot_char_4', 'lot_char_5', 'processed', 'product_name']),
        },
        {
            'key': 'module',
            'title': '모듈 설정',
            'description': '제품/Layer/Step 기준 모듈 분류 규칙',
            'columns': ['product_name', 'start_layer', 'end_layer', 'start_stepseq', 'end_stepseq', 'module_name'],
            'rows': _rows_with_columns(module_rules, ['product_name', 'start_layer', 'end_layer', 'start_stepseq', 'end_stepseq', 'module_name']),
        },
        {
            'key': 'exclusion',
            'title': 'HOLD유형 설정',
            'description': 'HOLD/FTP/예약제외 분류 규칙',
            'columns': ['exclusion_kind', 'condition_1', 'condition_2', 'condition_3', 'type_name'],
            'rows': _rows_with_columns(exclusion_rules, ['exclusion_kind', 'condition_1', 'condition_2', 'condition_3', 'type_name']),
        },
        {
            'key': 'hot',
            'title': '초HOT 기준 설정',
            'description': 'Grade 및 조건식 기반 초HOT 규칙',
            'columns': ['grade', 'condition_1', 'condition_2', 'condition_3', 'type_name'],
            'rows': _rows_with_columns(hot_rules, ['grade', 'condition_1', 'condition_2', 'condition_3', 'type_name']),
        },
    ]


def ref_page(request):
    context = {**_base_context(), 'ref_sections': [], 'ref_error_message': ''}
    try:
        product_rules = WipRefProductRule.objects.filter(is_active=True).order_by('sort_no', 'id')
        module_rules = WipRefModuleRule.objects.filter(is_active=True).order_by('sort_no', 'id')
        exclusion_rules = WipRefExclusionTypeRule.objects.filter(is_active=True).order_by('sort_no', 'id')
        hot_rules = WipRefHotLotRule.objects.filter(is_active=True).order_by('sort_no', 'id')
        context['ref_sections'] = _build_ref_sections(product_rules, module_rules, exclusion_rules, hot_rules)
    except (ProgrammingError, OperationalError) as exc:
        logger.exception('[ref-page 오류] %s: %s', exc.__class__.__name__, exc)
        context['ref_error_message'] = '기준정보 테이블이 아직 생성되지 않았습니다. python manage.py migrate 실행 후 다시 접속하세요.'
        context['ref_sections'] = _build_ref_sections(
            WipRefProductRule.objects.none(),
            WipRefModuleRule.objects.none(),
            WipRefExclusionTypeRule.objects.none(),
            WipRefHotLotRule.objects.none(),
        )
    return render(request, 'wipreport/ref.html', context)


@require_GET
def summary_data(request):
    data = make_json_safe(build_summary(request.GET))
    if isinstance(data, dict) and not settings.DEBUG:
        data.pop('error_detail', None)
    return JsonResponse(data, safe=False)


def _validate_unique(rows, keys):
    seen = set()
    for row in rows:
        key = tuple((row.get(k) or '').strip() for k in keys)
        if key in seen:
            return False
        seen.add(key)
    return True


def _save_replace(model, rows):
    model.objects.filter(is_active=True).delete()
    objs = []
    allowed = {f.name for f in model._meta.fields}
    for i, row in enumerate(rows, start=1):
        payload = {k: v for k, v in row.items() if k in allowed and k not in {'id', 'created_at', 'updated_at'}}
        payload['sort_no'] = i
        payload['is_active'] = True
        objs.append(model(**payload))
    model.objects.bulk_create(objs)


@require_POST
def save_product_rules(request):
    rows = json.loads(request.body or '{}').get('rows', [])
    if not _validate_unique(rows, ['lot_char_1', 'lot_char_2', 'lot_char_3', 'lot_char_4', 'lot_char_5', 'processed']):
        return JsonResponse({'ok': False, 'message': '제품구분 규칙 중복'}, status=400)
    _save_replace(WipRefProductRule, rows)
    return JsonResponse({'ok': True})


@require_POST
def save_module_rules(request):
    rows = json.loads(request.body or '{}').get('rows', [])
    if not _validate_unique(rows, ['product_name', 'start_layer', 'end_layer', 'start_stepseq', 'end_stepseq', 'module_name']):
        return JsonResponse({'ok': False, 'message': '모듈 규칙 중복'}, status=400)
    _save_replace(WipRefModuleRule, rows)
    return JsonResponse({'ok': True})


@require_POST
def save_exclusion_rules(request):
    rows = json.loads(request.body or '{}').get('rows', [])
    valid_types = {'HOLD', 'FTP', '예약제외'}
    for r in rows:
        if (r.get('exclusion_kind') or '') not in valid_types:
            return JsonResponse({'ok': False, 'message': 'type 값 오류'}, status=400)
    if not _validate_unique(rows, ['exclusion_kind', 'condition_1', 'condition_2', 'condition_3']):
        return JsonResponse({'ok': False, 'message': 'HOLD유형 규칙 중복'}, status=400)
    _save_replace(WipRefExclusionTypeRule, rows)
    return JsonResponse({'ok': True})


@require_POST
def save_hot_rules(request):
    rows = json.loads(request.body or '{}').get('rows', [])
    if not _validate_unique(rows, ['grade', 'condition_1', 'condition_2', 'condition_3']):
        return JsonResponse({'ok': False, 'message': '초HOT 규칙 중복'}, status=400)
    _save_replace(WipRefHotLotRule, rows)
    return JsonResponse({'ok': True})
