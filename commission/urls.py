from django.urls import path
from . import views

app_name = "commission"

urlpatterns = [
    path("set/<int:user_id>/", views.set_commission, name="set_commission"),
    path("update-user-commission/", views.update_user_commission, name="update_user_commission"),
    path('update-user-referral-commission/', views.update_user_referral_commission, name='update_user_referral_commission'),
]
