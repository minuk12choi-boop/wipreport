import json
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST
from .models import WipRefProductRule,WipRefModuleRule,WipRefExclusionTypeRule,WipRefHotLotRule
from .services import build_summary

def wip_root(request): return redirect('wip-summary')
def summary_page(request): return render(request,'wipreport/summary.html',{})
def ref_page(request): return render(request,'wipreport/ref.html',{'product_rules':WipRefProductRule.objects.all().order_by('sort_no'),'module_rules':WipRefModuleRule.objects.all().order_by('sort_no'),'exclusion_rules':WipRefExclusionTypeRule.objects.all().order_by('sort_no'),'hot_rules':WipRefHotLotRule.objects.all().order_by('sort_no')})
@require_GET
def summary_data(request):
    data=build_summary({'lot_type':request.GET.getlist('lot_type')})
    return JsonResponse(data, safe=False)

def _save_all(model, rows):
    model.objects.all().delete()
    objs=[]
    for i,r in enumerate(rows, start=1):
        r['sort_no']=i
        field_names = {f.name for f in model._meta.fields}
        objs.append(model(**{k:v for k,v in r.items() if k in field_names and k not in {'id','created_at','updated_at'}}))
    for o in objs: o.save()
@require_POST
def save_product_rules(request):
    rows=json.loads(request.body or '{}').get('rows',[]); _save_all(WipRefProductRule, rows); return JsonResponse({'ok':True})
@require_POST
def save_module_rules(request):
    rows=json.loads(request.body or '{}').get('rows',[]); _save_all(WipRefModuleRule, rows); return JsonResponse({'ok':True})
@require_POST
def save_exclusion_rules(request):
    rows=json.loads(request.body or '{}').get('rows',[]); _save_all(WipRefExclusionTypeRule, rows); return JsonResponse({'ok':True})
@require_POST
def save_hot_rules(request):
    rows=json.loads(request.body or '{}').get('rows',[]); _save_all(WipRefHotLotRule, rows); return JsonResponse({'ok':True})
