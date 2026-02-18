# accounts/urls.py
from django.urls import path
from django.views.generic import RedirectView
from . import views

app_name = "accounts"  

urlpatterns = [
    # Root URL redirects to home dashboard
    path('', RedirectView.as_view(url='home/', permanent=False), name='root_redirect'),
    
    # Super Admin URLs
    path('superadmin/', views.superadminlogin, name='superadminlogin'),
    path('superadmin-dashboard/', views.superadmin_dashboard, name='superadmin_dashboard'),

    # Admin URLs
    path('adminlogin/', views.adminlogin, name='adminlogin'),
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-dashboard/events/', views.admin_dashboard_events, name='admin_dashboard_events'),
    path('admin-dashboard/events/clear/', views.admin_dashboard_events_mark_read, name='admin_dashboard_events_mark_read'),
    path('admin-dashboard/summary/', views.admin_dashboard_summary, name='admin_dashboard_summary'),
    
    # Customer Service URLs
    path('cslogin/', views.customerservicelogin, name='customerservicelogin'),
    path('cs-dashboard/', views.customerservice_dashboard, name='customerservice_dashboard'),
    path('cs/admin/<int:admin_id>/', views.admin_overview_for_cs, name='cs_admin_overview'),
    
    # Regular User URLs
    path('register/', views.user_register, name='user_register'),
    path('userlogin/', views.user_login, name='user_login'),
    path('home/', views.home_dashboard, name='home_dashboard'),
    path('', views.home_dashboard, name='index'),
   
    
    # Other URLs
    path('profile/', views.profile_view, name='profile'),
    path('payment/', views.payment_view, name='payment'),
    path('settings/', views.settings_view, name='settings'),
    path('faq/', views.faq_view, name='faq'),
    path('logout/', views.logout_view, name='logout'),
    path('balance/', views.balance_view, name='balance'),
    path('activities/', views.activities_view, name='activities'),
    path('analytics/', views.analytics_page, name='analytics'),
    
    # Individual Analytics Pages
    path('analytics/financial/', views.financial_analytics_page, name='financial_analytics'),
    path('analytics/tasks/', views.task_analytics_page, name='task_analytics'),
    path('analytics/performance/', views.performance_analytics_page, name='performance_analytics'),
    path('analytics/geography/', views.geography_analytics_page, name='geography_analytics'),
    path('analytics/referrals/', views.referral_analytics_page, name='referral_analytics'),
    path('analytics/withdrawals/', views.withdrawal_analytics_page, name='withdrawal_analytics'),
    path('analytics/activity/', views.activity_analytics_page, name='activity_analytics'),
    
    # API URLs for admin functionality
    path('user/<int:user_id>/history/', views.user_history, name='user_history'),
    path('user/<int:user_id>/adjust-balance/', views.admin_adjust_balance, name='admin_adjust_balance'),
    path('user/<int:user_id>/info-alert/clear/', views.clear_info_alert, name='clear_info_alert'),
    path('cs/guest-unread/', views.customerservice_guest_unread, name='customerservice_guest_unread'),
    path('cs/user-support-unread/', views.customerservice_support_unread, name='customerservice_support_unread'),
]