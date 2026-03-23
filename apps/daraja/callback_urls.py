from django.urls import path

from .callbacks import c2b_validate, c2b_confirm, stk_callback

urlpatterns = [
    path('c2b/<uuid:uid>/validate/', c2b_validate, name='c2b-validate'),
    path('c2b/<uuid:uid>/confirm/', c2b_confirm, name='c2b-confirm'),
    path('stk/<uuid:uid>/callback/', stk_callback, name='stk-callback'),
]
