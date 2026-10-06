"""
Resultados del bot de cobranza - versión de escritorio.

Abre la app (app/index.html) en una ventana propia usando el motor de Edge
(WebView2) que trae Windows. Los archivos se procesan en el equipo; nada se
envía a internet.
"""
import base64
import os
import sys

import webview

NOMBRE_APP = "ResultadosBot"
TITULO = "Resultados del bot de cobranza"


def recurso(ruta_relativa):
    """Ruta a un archivo incluido, tanto en desarrollo como dentro del .exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, ruta_relativa)


def carpeta_datos():
    """Carpeta donde se guardan las reglas y tarifas que ajuste la líder."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    ruta = os.path.join(base, NOMBRE_APP)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def carpeta_descargas():
    ruta = os.path.join(os.path.expanduser("~"), "Downloads")
    return ruta if os.path.isdir(ruta) else os.path.expanduser("~")


class Api:
    """Funciones que la página puede llamar desde JavaScript."""

    def __init__(self):
        self._ventana = None  # con guion bajo para que no se exponga a la página

    def guardar_excel(self, contenido_b64, nombre):
        tipo = getattr(getattr(webview, "FileDialog", None), "SAVE", None)
        if tipo is None:
            tipo = webview.SAVE_DIALOG  # versiones anteriores de pywebview
        ruta = self._ventana.create_file_dialog(
            tipo,
            directory=carpeta_descargas(),
            save_filename=nombre,
            file_types=("Libro de Excel (*.xlsx)",),
        )
        if not ruta:
            return {"ok": False, "cancelado": True}
        if isinstance(ruta, (list, tuple)):
            ruta = ruta[0]
        if not str(ruta).lower().endswith(".xlsx"):
            ruta = f"{ruta}.xlsx"
        try:
            with open(ruta, "wb") as f:
                f.write(base64.b64decode(contenido_b64))
            return {"ok": True, "ruta": ruta}
        except PermissionError:
            return {"ok": False, "error": "el archivo está abierto en Excel o no hay permiso para guardar en esa carpeta."}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def abrir_archivo(self, ruta):
        try:
            if sys.platform.startswith("win"):
                os.startfile(ruta)  # type: ignore[attr-defined]
            return True
        except Exception:  # noqa: BLE001
            return False


def main():
    api = Api()
    ventana = webview.create_window(
        TITULO,
        url=recurso(os.path.join("app", "index.html")),
        js_api=api,
        width=1320,
        height=900,
        min_size=(900, 640),
        text_select=True,
    )
    api._ventana = ventana
    webview.start(private_mode=False, storage_path=carpeta_datos())


if __name__ == "__main__":
    main()
