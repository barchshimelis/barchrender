from django.urls import path
from . import views

app_name = "wallet"

urlpatterns = [
    path("", views.wallet_management_view, name="manage"),
    path("withdraw/", views.wallet_management_view, name="withdraw"),
    path("bind/", views.wallet_management_view, name="bind_user_wallet"),
    path('withdraw/approve/<int:withdrawal_id>/', views.approve_withdrawal, name='approve_withdrawal'),
    path('withdraw/reject/<int:withdrawal_id>/', views.reject_withdrawal, name='reject_withdrawal'),
    path('withdraw/processing/<int:withdrawal_id>/', views.set_processing, name='set_processing'),
  
]