from django.urls import path
from . import views
urlpatterns=[
    path('', views.wip_root),
    path('summary/', views.summary_page, name='wip-summary'),
    path('ref/', views.ref_page, name='wip-ref'),
    path('api/summary-data/', views.summary_data),
    path('api/ref/product-rules/save/', views.save_product_rules),
    path('api/ref/module-rules/save/', views.save_module_rules),
    path('api/ref/exclusion-rules/save/', views.save_exclusion_rules),
    path('api/ref/hot-rules/save/', views.save_hot_rules),
]
