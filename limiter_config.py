# limiter_config.py
from slowapi import Limiter
from slowapi.util import get_remote_address

# Definimos el limiter aquí para poder importarlo en las rutas
limiter = Limiter(key_func=get_remote_address)