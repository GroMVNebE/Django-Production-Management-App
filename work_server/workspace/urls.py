from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('product/<int:pk>', views.product_detail_view, name='product-detail'),
    path('my_products/', views.my_products_view, name='my_products'),
    path('my_product/<int:pk>', views.my_product_view, name='my-product'),
    path('objects/<pk>', views.object_detail_view, name='object-detail'),
    path('in_work/', views.in_work_view, name='in_work'),
    path('workers_list/', views.workers_list_view, name='workers'),
    path('product_in_work/<int:pk>',
         views.product_in_work_detail_view, name='product-in-work'),
    path('worker/<int:pk>', views.worker_detail, name='worker'),
    path('questions/', views.questions_list, name='questions'),
    path('instance_details/<int:pk>',
         views.instance_details, name='instance-details'),
    path('migrate/', views.migrate_view, name="migrate"),
    path('queued_details/<int:pk>',
         views.queued_details, name='queued-details'),
    path('hidden/', views.hidden_view, name="hidden"),
    path('blacklist/', views.blacklist_settings_view, name="blacklist-settings")
]