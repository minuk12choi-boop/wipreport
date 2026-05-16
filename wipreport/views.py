import json
import logging

from django.conf import settings
from django.db import OperationalError, ProgrammingError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .models import (
    WipRefExclusionTypeRule,
    WipRefHotLotRule,
    WipRefModuleRule,
    WipRefProductRule,
)
from .services import build_summary

logger = logging.getLogger(__name__)


def wip_root(request):
    return redirect('wip-summary')


def summary_page(request):
    return render(request, 'wipreport/summary.html', {})


def ref_page(request):
    context = {
        'product_rules': [],
        'module_rules': [],
        'exclusion_rules': [],
        'hot_rules': [],
        'ref_error_message': '',
    }
    try:
        context.update(
            {
                'product_rules': WipRefProductRule.objects.all().order_by('sort_no'),
                'module_rules': WipRefModuleRule.objects.all().order_by('sort_no'),
                'exclusion_rules': WipRefExclusionTypeRule.objects.all().order_by('sort_no'),
                'hot_rules': WipRefHotLotRule.objects.all().order_by('sort_no'),
            }
        )
    except (ProgrammingError, OperationalError) as exc:
        logger.exception('[ref-page 오류] %s: %s', exc.__class__.__name__, exc)
        context['ref_error_message'] = (
            '기준정보 테이블이 아직 생성되지 않았습니다. '
            'python manage.py migrate 실행 후 다시 접속하세요.'
        )
    return render(request, 'wipreport/ref.html', context)


@require_GET
def summary_data(request):
    data = build_summary({'lot_type': request.GET.getlist('lot_type')})
    if isinstance(data, dict) and data.get('error') and settings.DEBUG and data.get('error_detail'):
        return JsonResponse(data, safe=False)
    if isinstance(data, dict):
        data.pop('error_detail', None)
    return JsonResponse(data, safe=False)


def _save_all(model, rows):
    model.objects.all().delete()
    objs = []
    for i, r in enumerate(rows, start=1):
        r['sort_no'] = i
        field_names = {f.name for f in model._meta.fields}
        objs.append(
            model(
                **{
                    k: v
                    for k, v in r.items()
                    if k in field_names and k not in {'id', 'created_at', 'updated_at'}
                }
            )
        )
    for o in objs:
        o.save()


@require_POST
def save_product_rules(request):
    rows = json.loads(request.body or '{}').get('rows', [])
    _save_all(WipRefProductRule, rows)
    return JsonResponse({'ok': True})


@require_POST
def save_module_rules(request):
    rows = json.loads(request.body or '{}').get('rows', [])
    _save_all(WipRefModuleRule, rows)
    return JsonResponse({'ok': True})


@require_POST
def save_exclusion_rules(request):
    rows = json.loads(request.body or '{}').get('rows', [])
    _save_all(WipRefExclusionTypeRule, rows)
    return JsonResponse({'ok': True})


@require_POST
def save_hot_rules(request):
    rows = json.loads(request.body or '{}').get('rows', [])
    _save_all(WipRefHotLotRule, rows)
    return JsonResponse({'ok': True})
