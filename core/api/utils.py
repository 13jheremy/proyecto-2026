import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings

if not firebase_admin._apps:
    cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT)
    firebase_admin.initialize_app(cred)
