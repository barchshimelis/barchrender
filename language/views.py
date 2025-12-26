from django.shortcuts import redirect
from django.http import HttpResponseRedirect
from django.utils.translation import activate
from django.conf import settings
from django.urls import translate_url
from django.utils import translation

def set_language(request):
    if request.method == 'POST':
        language = request.POST.get('language', settings.LANGUAGE_CODE)
        next_url = request.META.get('HTTP_REFERER', '/')
        
        # Activate the selected language
        translation.activate(language)
        request.session[translation.LANGUAGE_SESSION_KEY] = language
        
        # Get the translated URL if needed
        response = HttpResponseRedirect(next_url)
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language)
        
        return response
    
    # If not a POST request, redirect to home
    return redirect('/')
