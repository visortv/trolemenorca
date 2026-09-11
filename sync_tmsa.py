"""Bootstrap de compatibilidad para el servicio Render existente.

El servicio histórico ejecuta `python sync_tmsa.py && gunicorn app:app`.
Este bootstrap despliega en el directorio de trabajo el runtime V12.16 completo
y después ejecuta la sincronización inteligente de los tres operadores.
"""
from pathlib import Path
import sys, zipfile

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / 'runtime_v12_16.zip'


def _extract_runtime():
    if not ARCHIVE.is_file():
        raise RuntimeError('Falta runtime_v12_16.zip')
    root = ROOT.resolve()
    with zipfile.ZipFile(ARCHIVE) as z:
        for info in z.infolist():
            target = (ROOT / info.filename).resolve()
            if not target.is_relative_to(root):
                raise RuntimeError('Ruta no permitida en runtime: ' + info.filename)
        z.extractall(ROOT)


def main():
    _extract_runtime()
    sys.path.insert(0, str(ROOT))
    from sync_all import main as sync_main
    return sync_main()


if __name__ == '__main__':
    raise SystemExit(main())
