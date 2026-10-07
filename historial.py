"""
Histórico local en SQLite para "Resultados del bot de cobranza".

Guarda los registros ya normalizados por la app (envíos, Meta, gestiones del
bot, asesoras, NLP y pagos) con una clave única por registro, de modo que
recargar un archivo o cargar archivos que se cruzan nunca duplica datos.
Cada carga queda registrada y se puede eliminar completa.
"""
import json
import os
import shutil
import sqlite3
from datetime import datetime

TIPOS = ("base", "campaign", "gestiones", "chat", "nlp", "pagos")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS cargas(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    archivos TEXT NOT NULL,
    resumen TEXT,
    origen TEXT DEFAULT 'local'
);
CREATE TABLE IF NOT EXISTS registros(
    tipo TEXT NOT NULL,
    clave TEXT NOT NULL,
    carga_id INTEGER NOT NULL,
    dia INTEGER,
    nit TEXT,
    datos TEXT NOT NULL,
    PRIMARY KEY (tipo, clave)
);
CREATE INDEX IF NOT EXISTS ix_registros_carga ON registros(carga_id);
CREATE INDEX IF NOT EXISTS ix_registros_tipo_nit ON registros(tipo, nit);
CREATE TABLE IF NOT EXISTS cobertura_pagos(
    carga_id INTEGER NOT NULL,
    desde INTEGER NOT NULL,
    hasta INTEGER NOT NULL
);
"""


class Historial:
    def __init__(self, ruta):
        self.ruta = ruta
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with self._con() as con:
            con.executescript(ESQUEMA)

    def _con(self):
        con = sqlite3.connect(self.ruta, timeout=15)
        con.execute("PRAGMA journal_mode=DELETE")  # sin archivos -wal: mejor para OneDrive
        con.execute("PRAGMA foreign_keys=ON")
        return con

    # ---------------------------------------------------------------- lectura
    def nits(self):
        with self._con() as con:
            filas = con.execute("SELECT DISTINCT nit FROM registros WHERE tipo='base'").fetchall()
        return [f[0] for f in filas if f[0]]

    def datos_json(self):
        """Todo el histórico como texto JSON (se arma por partes, es más rápido)."""
        partes = []
        with self._con() as con:
            for tipo in TIPOS:
                filas = con.execute("SELECT datos FROM registros WHERE tipo=? ORDER BY dia", (tipo,)).fetchall()
                partes.append('"%s":[%s]' % (tipo, ",".join(f[0] for f in filas)))
            cob = con.execute("SELECT desde, hasta FROM cobertura_pagos ORDER BY desde").fetchall()
        partes.append('"cobertura":%s' % json.dumps([[a, b] for a, b in cob]))
        return "{" + ",".join(partes) + "}"

    def info(self):
        with self._con() as con:
            cargas = con.execute("SELECT id, fecha, archivos, resumen, origen FROM cargas ORDER BY id DESC").fetchall()
            conteo = dict(con.execute("SELECT tipo, COUNT(*) FROM registros GROUP BY tipo").fetchall())
            rango = dict(
                (t, (a, b))
                for t, a, b in con.execute("SELECT tipo, MIN(dia), MAX(dia) FROM registros GROUP BY tipo").fetchall()
            )
        try:
            tamano = os.path.getsize(self.ruta)
        except OSError:
            tamano = 0
        return {
            "ruta": self.ruta,
            "tamano": tamano,
            "conteo": conteo,
            "rango": rango,
            "cargas": [
                {
                    "id": c[0],
                    "fecha": c[1],
                    "archivos": json.loads(c[2] or "[]"),
                    "resumen": json.loads(c[3] or "{}"),
                    "origen": c[4] or "local",
                }
                for c in cargas
            ],
        }

    # ------------------------------------------------------------- escritura
    def guardar(self, payload):
        registros = payload.get("registros", {})
        cobertura = payload.get("cobertura", [])
        nuevos, repetidos = {}, {}
        with self._con() as con:
            cur = con.execute(
                "INSERT INTO cargas(fecha, archivos) VALUES(?, ?)",
                (datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(payload.get("archivos", []), ensure_ascii=False)),
            )
            carga_id = cur.lastrowid
            for tipo in TIPOS:
                n = r = 0
                for reg in registros.get(tipo, []):
                    c = con.execute(
                        "INSERT OR IGNORE INTO registros(tipo, clave, carga_id, dia, nit, datos) VALUES(?,?,?,?,?,?)",
                        (tipo, str(reg["k"]), carga_id, reg.get("d"), reg.get("nit", ""),
                         json.dumps(reg, ensure_ascii=False, separators=(",", ":"))),
                    )
                    if c.rowcount:
                        n += 1
                    else:
                        r += 1
                if n:
                    nuevos[tipo] = n
                if r:
                    repetidos[tipo] = r
            existentes = con.execute("SELECT desde, hasta FROM cobertura_pagos").fetchall()
            cob_nueva = 0
            for desde, hasta in cobertura:
                if not any(a <= desde and hasta <= b for a, b in existentes):
                    con.execute("INSERT INTO cobertura_pagos VALUES(?,?,?)", (carga_id, desde, hasta))
                    cob_nueva += 1
            if not nuevos and not cob_nueva:
                con.execute("DELETE FROM cargas WHERE id=?", (carga_id,))
                carga_id = None
            else:
                con.execute("UPDATE cargas SET resumen=? WHERE id=?", (json.dumps(nuevos), carga_id))
        return {"carga_id": carga_id, "nuevos": nuevos, "repetidos": repetidos}

    def borrar_carga(self, carga_id):
        with self._con() as con:
            con.execute("DELETE FROM registros WHERE carga_id=?", (carga_id,))
            con.execute("DELETE FROM cobertura_pagos WHERE carga_id=?", (carga_id,))
            con.execute("DELETE FROM cargas WHERE id=?", (carga_id,))
        return True

    def importar(self, ruta_otro):
        """Suma a este histórico lo que tenga otro archivo de histórico, sin duplicar."""
        if os.path.abspath(ruta_otro) == os.path.abspath(self.ruta):
            return {"ok": False, "error": "es el mismo archivo que ya se está usando."}
        otro = sqlite3.connect(ruta_otro)
        try:
            tablas = {t[0] for t in otro.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"cargas", "registros"} <= tablas:
                return {"ok": False, "error": "el archivo no es un histórico de esta aplicación."}
            cargas = otro.execute("SELECT id, fecha, archivos FROM cargas ORDER BY id").fetchall()
            total = 0
            with self._con() as con:
                for viejo_id, fecha, archivos in cargas:
                    cid = con.execute(
                        "INSERT INTO cargas(fecha, archivos, origen) VALUES(?,?,?)",
                        (fecha, archivos, "importado de " + os.path.basename(ruta_otro)),
                    ).lastrowid
                    nuevos = {}
                    for tipo, clave, dia, nit, datos in otro.execute(
                        "SELECT tipo, clave, dia, nit, datos FROM registros WHERE carga_id=?", (viejo_id,)
                    ):
                        c = con.execute(
                            "INSERT OR IGNORE INTO registros(tipo, clave, carga_id, dia, nit, datos) VALUES(?,?,?,?,?,?)",
                            (tipo, clave, cid, dia, nit, datos),
                        )
                        if c.rowcount:
                            nuevos[tipo] = nuevos.get(tipo, 0) + 1
                    cob = 0
                    if "cobertura_pagos" in tablas:
                        existentes = con.execute("SELECT desde, hasta FROM cobertura_pagos").fetchall()
                        for desde, hasta in otro.execute(
                            "SELECT desde, hasta FROM cobertura_pagos WHERE carga_id=?", (viejo_id,)
                        ):
                            if not any(a <= desde and hasta <= b for a, b in existentes):
                                con.execute("INSERT INTO cobertura_pagos VALUES(?,?,?)", (cid, desde, hasta))
                                cob += 1
                    if not nuevos and not cob:
                        con.execute("DELETE FROM cargas WHERE id=?", (cid,))
                    else:
                        con.execute("UPDATE cargas SET resumen=? WHERE id=?", (json.dumps(nuevos), cid))
                        total += sum(nuevos.values())
            return {"ok": True, "nuevos": total}
        finally:
            otro.close()

    def vaciar(self):
        """Deja el histórico en blanco, guardando antes una copia de respaldo al lado."""
        carpeta = os.path.dirname(self.ruta)
        respaldo = os.path.join(carpeta, "respaldo_antes_de_vaciar_" + datetime.now().strftime("%Y-%m-%d_%H%M") + ".db")
        self.copiar_a(respaldo)
        with self._con() as con:
            con.execute("DELETE FROM registros")
            con.execute("DELETE FROM cobertura_pagos")
            con.execute("DELETE FROM cargas")
        with self._con() as con:
            con.execute("VACUUM")
        return respaldo

    def copiar_a(self, destino):
        """Copia segura del histórico (funciona aunque esté en uso)."""
        dst = sqlite3.connect(destino)
        try:
            with self._con() as src:
                src.backup(dst)
        finally:
            dst.close()
        return destino

    def mover_a(self, nueva_ruta):
        """Cambia la ubicación del histórico. Si ya existe uno allá, se usa ese."""
        if os.path.abspath(nueva_ruta) == os.path.abspath(self.ruta):
            return self.ruta
        if not os.path.exists(nueva_ruta):
            os.makedirs(os.path.dirname(nueva_ruta), exist_ok=True)
            shutil.copy2(self.ruta, nueva_ruta)
        self.ruta = nueva_ruta
        with self._con() as con:
            con.executescript(ESQUEMA)
        return self.ruta
