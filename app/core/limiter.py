"""
Rate limiter global - ProfesorSYS

Instancia unica compartida por todos los routers.
NOTA: slowapi lee el .env automaticamente via starlette.Config.
El .env debe estar en ASCII puro (sin tildes) para evitar
el error de encoding cp1252 en Windows.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
