from django.shortcuts import redirect
from django.urls import include, path


def root_redirect(request):
    return redirect('/wip/summary/')


urlpatterns = [
    path('', root_redirect, name='root'),
    path('wip/', include('wipreport.urls')),
]
