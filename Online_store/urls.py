from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from Blossom import views as blossom_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('Blossom.urls')),
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('signup/', blossom_views.signup_view, name='signup'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
