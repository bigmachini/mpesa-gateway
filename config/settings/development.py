from .base import *  # noqa

DEBUG = True

INSTALLED_APPS += ['django_extensions']  # noqa: F405

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

CORS_ALLOW_ALL_ORIGINS = True
