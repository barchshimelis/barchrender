from django.urls import path
from . import views

app_name = "products" 

urlpatterns = [
    path('', views.products_view, name='products'), 
    path("get_balance/", views.get_balance, name="get_balance"),
    path("regulation/", views.regulation_policy, name="regulation"),
]