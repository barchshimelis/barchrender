from django.urls import path
from stoppoints import views as sp_views

app_name = "stoppoints"

urlpatterns = [
    path('add/<int:user_id>/', sp_views.add_stop_points_view, name='add_stop_points'),
    path('update/<int:user_id>/', sp_views.update_stop_point_view, name='update_stop_point'),
    path('delete/<int:user_id>/', sp_views.delete_stop_point_view, name='delete_stop_point'),
]