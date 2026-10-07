"""
Resultados del bot de cobranza - versión de escritorio.

Abre la app (app/index.html) en una ventana propia usando el motor de Edge
(WebView2) que trae Windows. Los archivos se procesan en el equipo y el
histórico se guarda en una base SQLite local; nada se envía a internet.
"""
import base64
import json
import os
import sys
from datetime import datetime

import webview

from historial import Historial

NOMBRE_APP = "ResultadosBot"
TITULO = "Resultados del bot de cobranza"
NOMBRE_HISTORIAL = "historial_resultados_bot.db"


def recurso(ruta_relativa):
    """Ruta a un archivo incluido, tanto en desarrollo como dentro del .exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, ruta_relativa)


def carpeta_datos():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    ruta = os.path.join(base, NOMBRE_APP)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def carpeta_descargas():
    ruta = os.path.join(os.path.expanduser("~"), "Downloads")
    return ruta if os.path.isdir(ruta) else os.path.expanduser("~")


RUTA_CONFIG = os.path.join(carpeta_datos(), "config.json")


def leer_config():
    try:
        with open(RUTA_CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def guardar_config(cfg):
    with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def tipo_dialogo(nombre):
    fd = getattr(webview, "FileDialog", None)
    if fd is not None:
        return getattr(fd, nombre)
    return getattr(webview, nombre + "_DIALOG")  # versiones anteriores de pywebview


def primera(ruta):
    if isinstance(ruta, (list, tuple)):
        return ruta[0] if ruta else None
    return ruta


def abrir_en_windows(ruta):
    if sys.platform.startswith("win"):
        os.startfile(ruta)  # type: ignore[attr-defined]


class Api:
    """Funciones que la página puede llamar desde JavaScript."""

    def __init__(self):
        self._ventana = None  # con guion bajo para que no se exponga a la página
        cfg = leer_config()
        ruta = cfg.get("ruta_historial") or os.path.join(carpeta_datos(), NOMBRE_HISTORIAL)
        try:
            self._hist = Historial(ruta)
        except Exception:  # noqa: BLE001  (por ejemplo, una carpeta de red que ya no existe)
            self._hist = Historial(os.path.join(carpeta_datos(), NOMBRE_HISTORIAL))

    # ------------------------------------------------------------ Excel
    def guardar_excel(self, contenido_b64, nombre):
        ruta = primera(self._ventana.create_file_dialog(
            tipo_dialogo("SAVE"),
            directory=carpeta_descargas(),
            save_filename=nombre,
            file_types=("Libro de Excel (*.xlsx)",),
        ))
        if not ruta:
            return {"ok": False, "cancelado": True}
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
            abrir_en_windows(ruta)
            return True
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------ Histórico
    def historial_nits(self):
        return json.dumps(self._hist.nits())

    def historial_guardar(self, payload_json):
        try:
            return json.dumps(self._hist.guardar(json.loads(payload_json)))
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": str(e)})

    def historial_datos(self):
        return self._hist.datos_json()

    def historial_info(self):
        return json.dumps(self._hist.info(), ensure_ascii=False)

    def historial_borrar_carga(self, carga_id):
        self._hist.borrar_carga(int(carga_id))
        return True

    def historial_vaciar(self):
        try:
            return json.dumps({"ok": True, "respaldo": self._hist.vaciar()})
        except Exception as e:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(e)})

    def historial_abrir_carpeta(self):
        try:
            abrir_en_windows(os.path.dirname(self._hist.ruta))
            return True
        except Exception:  # noqa: BLE001
            return False

    def historial_cambiar_ubicacion(self):
        carpeta = primera(self._ventana.create_file_dialog(tipo_dialogo("FOLDER")))
        if not carpeta:
            return json.dumps({"ok": False, "cancelado": True})
        try:
            nueva = self._hist.mover_a(os.path.join(carpeta, NOMBRE_HISTORIAL))
            cfg = leer_config()
            cfg["ruta_historial"] = nueva
            guardar_config(cfg)
            return json.dumps({"ok": True, "ruta": nueva})
        except Exception as e:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(e)})

    def historial_exportar(self):
        nombre = "historial_resultados_bot_" + datetime.now().strftime("%Y-%m-%d") + ".db"
        ruta = primera(self._ventana.create_file_dialog(
            tipo_dialogo("SAVE"), directory=carpeta_descargas(), save_filename=nombre,
            file_types=("Histórico (*.db)",),
        ))
        if not ruta:
            return json.dumps({"ok": False, "cancelado": True})
        if not str(ruta).lower().endswith(".db"):
            ruta = f"{ruta}.db"
        try:
            self._hist.copiar_a(ruta)
            return json.dumps({"ok": True, "ruta": ruta})
        except Exception as e:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(e)})

    def historial_importar(self):
        ruta = primera(self._ventana.create_file_dialog(
            tipo_dialogo("OPEN"), directory=carpeta_descargas(), allow_multiple=False,
            file_types=("Histórico (*.db)",),
        ))
        if not ruta:
            return json.dumps({"ok": False, "cancelado": True})
        try:
            return json.dumps(self._hist.importar(ruta))
        except Exception as e:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(e)})


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
