from django.urls import path
from . import views

app_name = 'borrow_app'

urlpatterns = [
    path('', views.home_view, name='home'),
    path('request/', views.request_form_view, name='request_form'),  # 🟢 แก้ตรงนี้จาก 'request-form' เป็น 'request_form'
    path('request/summary/', views.request_summary_view, name='request_summary'),
    path('request/confirm/', views.confirm_request_view, name='confirm_request'),
    path('api/bundle/<str:asset_no_main>/', views.bundle_detail_api, name='bundle_detail_api'),
    path('add-to-cart/', views.add_to_cart_view, name='add_to_cart'),
    path('add-group-to-cart/<str:group_id>/', views.add_group_to_cart_view, name='add_group_to_cart'),
    path('remove-from-cart/<int:index>/', views.remove_from_cart_view, name='remove_from_cart'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('my-requests/', views.my_requests_view, name='my_requests'),
    path('history/', views.history_view, name='history'),
    path('admin-console/dashboard/', views.admin_dashboard_view, name='admin_dashboard'),
    path('admin-console/requests/', views.admin_manage_requests_view, name='admin_manage_requests'),
    path('admin-console/manual-request/', views.admin_manual_request_view, name='admin_manual_request'),
    path('admin-console/history/', views.admin_all_history_view, name='admin_all_history'),
    path('admin-console/equipment/', views.equipment_manage_view, name='equipment_manage'),
    path('cancel-request/<str:request_id>/', views.cancel_request_view, name='cancel_request'),
    path('return-request/<str:request_id>/', views.return_request_view, name='return_request'),
    path('equipment/sync-ssms/', views.sync_ssms_direct_view, name='sync_ssms_direct'),
]