from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from accounts.views import me_view  # Add this import

urlpatterns = [
    path('i18n/', include('django.conf.urls.i18n')),
    path('admin/', admin.site.urls),
]

# URLs that should be internationalized
urlpatterns += i18n_patterns(
    path('accounts/', include('accounts.urls')),  # Accounts app URLs
    path('products/', include('products.urls')),  # Products app URLs
    path('balance/', include('balance.urls', namespace='balance')),  # Balance app
    path('stoppoints/', include('stoppoints.urls')),  # Stoppoints app
    path('wallet/', include('wallet.urls', namespace='wallet')),  # Wallet app
    path("commission/", include("commission.urls")),  # Commission app
    path('notifications/', include('notification.urls')),  # Notification app
    path('me/', me_view, name='me'), 
    path("chat/", include("chat.urls")), # Updated this line
   
)

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)