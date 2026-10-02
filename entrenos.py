"""Entrenamientos: descarga desde Intervals.icu y métricas calculadas por ti.

Las funciones de red devuelven (dato, error) y no usan Streamlit, así que
se pueden probar solas. Las métricas se calculan desde los datos segundo a
segundo (potencia, pulso, cadencia), con fórmulas públicas.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

import fisiologia as fis

BASE = "https://intervals.icu/api/v1"
DURACIONES = [5, 30, 60, 300, 600, 1200, 3600]   # segundos para mejores esfuerzos
NOMBRES_ZONAS = [n for n, _, _ in fis.ZONAS_COGGAN] + ["Z7 Neuromuscular"]
LIMITES_ZONAS = [-np.inf, 55, 75, 90, 105, 120, 150, np.inf]


# --------------------------------------------------------------------------
# Descarga desde Intervals.icu
# --------------------------------------------------------------------------
def _get(ruta: str, api_key: str, params: dict | None = None):
    try:
        r = requests.get(f"{BASE}{ruta}", auth=("API_KEY", api_key),
                         params=params, timeout=30)
    except requests.RequestException as e:
        return None, f"Error de conexión ({e.__class__.__name__})."
    if r.status_code != 200:
        return None, f"Intervals.icu respondió con código {r.status_code}."
    try:
        return r.json(), None
    except ValueError:
        return None, "Intervals.icu devolvió una respuesta que no pude leer."


def listar_actividades(athlete_id: str, api_key: str, dias: int = 30):
    """Resumen de todos tus entrenos del período, con todos los campos que entrega la API."""
    hoy = date.today()
    datos, error = _get(f"/athlete/{athlete_id}/activities", api_key, {
        "oldest": (hoy - timedelta(days=dias)).isoformat(),
        "newest": hoy.isoformat(),
    })
    if error:
        return pd.DataFrame(), error
    if not isinstance(datos, list) or not datos:
        return pd.DataFrame(), None
    df = pd.DataFrame([d for d in datos if isinstance(d, dict)])
    if "start_date_local" in df:
        df = df.sort_values("start_date_local", ascending=False)
    return df.reset_index(drop=True), None


def detalle_actividad(api_key: str, actividad_id: str):
    """Ficha completa de un entreno, con intervalos detectados."""
    datos, error = _get(f"/activity/{actividad_id}", api_key, {"intervals": "true"})
    if error:
        return {}, error
    return (datos if isinstance(datos, dict) else {}), None


def parsear_streams(datos) -> pd.DataFrame:
    """Acepta una lista [{type, data}] o un diccionario {tipo: [valores]}."""
    columnas = {}
    if isinstance(datos, list):
        for s in datos:
            if isinstance(s, dict) and isinstance(s.get("data"), list):
                columnas[s.get("type") or s.get("name")] = s["data"]
    elif isinstance(datos, dict):
        for k, v in datos.items():
            if isinstance(v, list):
                columnas[k] = v
    columnas = {k: v for k, v in columnas.items()
                if k and v and not isinstance(v[0], (list, dict))}
    if not columnas:
        return pd.DataFrame()
    df = pd.DataFrame({k: pd.Series(v) for k, v in columnas.items()})
    return df.apply(pd.to_numeric, errors="coerce")


def a_1hz(df: pd.DataFrame) -> pd.DataFrame:
    """Deja un dato por segundo, rellenando pausas (potencia en 0)."""
    if df.empty:
        return df
    if "time" in df:
        t = df["time"]
        if t.notna().all() and t.is_monotonic_increasing and (t.diff().dropna() != 1).any():
            df = df.drop(columns="time").set_index(t.astype(int))
            df = df[~df.index.duplicated()]
            df = df.reindex(np.arange(int(t.iloc[0]), int(t.iloc[-1]) + 1))
            if "watts" in df:
                df["watts"] = df["watts"].fillna(0)
            return df.interpolate(limit=10)
        df = df.drop(columns="time")
    return df.reset_index(drop=True)


def streams_actividad(api_key: str, actividad_id: str):
    """Datos segundo a segundo (potencia, pulso, cadencia, altitud...)."""
    datos, error = _get(f"/activity/{actividad_id}/streams.json", api_key)
    if error:
        return pd.DataFrame(), error
    return a_1hz(parsear_streams(datos)), None


# --------------------------------------------------------------------------
# Métricas calculadas por ti
# --------------------------------------------------------------------------
def _np(w) -> float | None:
    """Potencia normalizada: media móvil de 30 s, a la 4ª, promedio, raíz 4ª."""
    w = pd.Series(w).fillna(0).astype(float)
    if len(w) < 30:
        return None
    r = w.rolling(30).mean().dropna()
    return float((r ** 4).mean() ** 0.25)


def metricas_propias(df: pd.DataFrame, ftp: float | None) -> dict:
    """Todas las métricas que se pueden calcular desde los datos del entreno."""
    if df.empty or "watts" not in df:
        return {}
    w = df["watts"].fillna(0).astype(float)
    n = len(w)
    media = float(w.mean())
    np_ = _np(w)
    m = {"duracion_s": n, "pot_media": media, "np": np_,
         "trabajo_kj": float(w.sum()) / 1000.0}
    if np_ and media:
        m["vi"] = np_ / media
    if np_ and ftp:
        i_f = np_ / ftp
        m["if"] = i_f
        m["tss"] = n * np_ * i_f / (ftp * 3600.0) * 100.0

    if "heartrate" in df:
        hr = df["heartrate"].replace(0, np.nan)
        if hr.notna().any():
            m["fc_media"] = float(hr.mean())
            m["fc_max"] = float(hr.max())
            if np_:
                m["ef"] = np_ / m["fc_media"]
            mitad = n // 2

            def ef_tramo(a, b):
                p, h = _np(w.iloc[a:b]), hr.iloc[a:b].mean()
                return p / h if p and h and not np.isnan(h) else None

            ef1, ef2 = ef_tramo(0, mitad), ef_tramo(mitad, n)
            if ef1 and ef2:
                m["desacople_pct"] = (ef1 - ef2) / ef1 * 100.0

    if "cadence" in df:
        c = df["cadence"]
        if (c > 0).any():
            m["cadencia_media"] = float(c[c > 0].mean())

    m["mejores"] = {d: float(w.rolling(d).mean().max()) for d in DURACIONES if d <= n}
    if ftp:
        categorias = pd.cut(w / ftp * 100.0, bins=LIMITES_ZONAS, labels=NOMBRES_ZONAS)
        m["zonas_s"] = (categorias.value_counts()
                        .reindex(NOMBRES_ZONAS, fill_value=0).astype(int).to_dict())
    return m


def aplanar(d: dict, prefijo: str = "") -> dict:
    """Convierte la ficha (con diccionarios anidados) en una lista plana campo → valor."""
    filas = {}
    for k, v in d.items():
        clave = f"{prefijo}{k}"
        if isinstance(v, dict):
            filas.update(aplanar(v, clave + "."))
        elif isinstance(v, list):
            largo = len(v) > 12 or (v and isinstance(v[0], (dict, list)))
            filas[clave] = f"[{len(v)} elementos]" if largo else str(v)
        else:
            filas[clave] = v
    return filas
