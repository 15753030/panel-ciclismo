"""Almacén local en SQLite: tu historia diaria, sin duplicados.

Una fila por fecha. Los datos que vienen de Intervals.icu y tus check-ins
(sensaciones, RPE, notas) conviven en la misma fila sin pisarse.
"""
from __future__ import annotations

import os
import sqlite3

import pandas as pd

CARPETA = os.path.dirname(os.path.abspath(__file__))
RUTA_DB = os.environ.get(
    "PANEL_DB", os.path.join(CARPETA, "panel_ciclismo.db"))

COLUMNAS_API = ["hrv", "rhr", "sueno", "ctl", "atl", "tsb", "eftp"]
COLUMNAS_CHECKIN = ["estado", "prescripcion", "sensacion", "piernas",
                    "animo", "dolor", "rpe", "notas"]
TODAS = COLUMNAS_API + COLUMNAS_CHECKIN
NUMERICAS = COLUMNAS_API + ["sensacion", "piernas", "animo", "dolor", "rpe"]

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS dia (
    fecha TEXT PRIMARY KEY,
    hrv REAL, rhr REAL, sueno REAL, ctl REAL, atl REAL, tsb REAL, eftp REAL,
    estado TEXT, prescripcion TEXT,
    sensacion INTEGER, piernas INTEGER, animo INTEGER, dolor INTEGER, rpe INTEGER,
    notas TEXT
)
"""


_ESQUEMA_ACTIVIDAD = """
CREATE TABLE IF NOT EXISTS actividad_extra (
    actividad_id TEXT PRIMARY KEY,
    tipo TEXT, rpe INTEGER, sensacion INTEGER, notas TEXT
)
"""


def _conectar(ruta: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(ruta or RUTA_DB)
    con.execute(_ESQUEMA)
    con.execute(_ESQUEMA_ACTIVIDAD)
    return con


def _limpio(valor):
    """Convierte NaN y tipos de numpy a algo que SQLite entienda."""
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    return valor.item() if hasattr(valor, "item") else valor


def _upsert(con, fecha: str, campos: dict, solo_vacios: bool = False) -> None:
    """Inserta o actualiza un día. Un valor None nunca borra un dato existente."""
    campos = {k: _limpio(v) for k, v in campos.items() if k in TODAS}
    if not campos:
        return
    cols = list(campos)
    marcas = ", ".join("?" * (len(cols) + 1))
    if solo_vacios:
        sets = ", ".join(f"{c}=COALESCE(dia.{c}, excluded.{c})" for c in cols)
    else:
        sets = ", ".join(f"{c}=COALESCE(excluded.{c}, dia.{c})" for c in cols)
    con.execute(
        f"INSERT INTO dia (fecha, {', '.join(cols)}) VALUES ({marcas}) "
        f"ON CONFLICT(fecha) DO UPDATE SET {sets}",
        [fecha, *campos.values()],
    )


def guardar_wellness(df: pd.DataFrame, ruta: str | None = None) -> None:
    """Guarda en la base los datos diarios descargados de Intervals.icu."""
    if df is None or df.empty:
        return
    with _conectar(ruta) as con:
        for fecha, fila in df.iterrows():
            _upsert(con, fecha.date().isoformat(),
                    {c: fila.get(c) for c in COLUMNAS_API})


def guardar_checkin(fecha: str, campos: dict, ruta: str | None = None) -> None:
    """Guarda (o actualiza) el check-in de una fecha. Una sola fila por día."""
    with _conectar(ruta) as con:
        _upsert(con, fecha, campos)


def leer_dias(ruta: str | None = None) -> pd.DataFrame:
    """Toda tu historia, indexada por fecha."""
    con = _conectar(ruta)
    try:
        df = pd.read_sql_query("SELECT * FROM dia ORDER BY fecha", con)
    finally:
        con.close()
    if df.empty:
        vacio = pd.DataFrame(
            columns=TODAS, index=pd.DatetimeIndex([], name="fecha"))
        return vacio
    df["fecha"] = pd.to_datetime(df["fecha"])
    df = df.set_index("fecha")
    for c in NUMERICAS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def borrar_dia(fecha: str, ruta: str | None = None) -> None:
    with _conectar(ruta) as con:
        con.execute("DELETE FROM dia WHERE fecha = ?", [fecha])


def importar_csv(ruta_csv: str, ruta: str | None = None) -> int:
    """Pasa tu historial CSV antiguo a la base (sin pisar datos existentes)."""
    h = pd.read_csv(ruta_csv).drop_duplicates("Fecha", keep="last")
    equivalencias = {"VFC": "hrv", "RHR": "rhr", "Sueño": "sueno",
                     "Estado": "estado", "Prescripción": "prescripcion"}
    with _conectar(ruta) as con:
        for _, fila in h.iterrows():
            campos = {nuevo: fila.get(viejo)
                      for viejo, nuevo in equivalencias.items()}
            _upsert(con, str(fila["Fecha"])[:10], campos, solo_vacios=True)
    return len(h)


# --------------------------------------------------------------------------
# Tus datos propios de cada entreno (tipo de sesión, RPE, sensación, notas)
# --------------------------------------------------------------------------
def guardar_extra_actividad(actividad_id: str, tipo=None, rpe=None,
                            sensacion=None, notas=None, ruta: str | None = None) -> None:
    with _conectar(ruta) as con:
        con.execute(
            "INSERT INTO actividad_extra (actividad_id, tipo, rpe, sensacion, notas) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(actividad_id) DO UPDATE SET "
            "tipo=excluded.tipo, rpe=excluded.rpe, sensacion=excluded.sensacion, "
            "notas=excluded.notas",
            [str(actividad_id), tipo, rpe, sensacion, notas],
        )


def leer_extra_actividad(actividad_id: str, ruta: str | None = None) -> dict:
    con = _conectar(ruta)
    try:
        fila = con.execute(
            "SELECT tipo, rpe, sensacion, notas FROM actividad_extra WHERE actividad_id = ?",
            [str(actividad_id)]).fetchone()
    finally:
        con.close()
    if not fila:
        return {}
    return dict(zip(["tipo", "rpe", "sensacion", "notas"], fila))
