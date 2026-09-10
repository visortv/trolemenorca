"""Entrada compatible con el comando antiguo de Render.

No bloquea el arranque realizando una sincronización completa. La aplicación
V12.16 inicia Gunicorn inmediatamente y ejecuta sync_all.py --force en segundo
plano tras arrancar, conservando mientras tanto cualquier snapshot válido.
"""
from domain import VERSION

def main():
    print(f'Menorca Bus {VERSION}: arranque web; sincronización completa en segundo plano.',flush=True)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
