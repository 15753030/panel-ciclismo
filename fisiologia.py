"""Fisiología personalizada: todo se deriva de los datos del atleta.

No hay valores fijos del atleta (ni VFC base, ni FTP, ni umbrales en watts).
Las únicas constantes son parámetros estadísticos del método (ventanas y
cantidad de desvíos), que no dependen de la persona.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

VENTANA_BASE = 60        # días que forman la línea base
DIAS_RECIENTES = 7       # ventana de tendencia
MIN_DATOS_BASE = 14      # mínimo de días para confiar en la base
BANDA_SD = 0.75          # ancho de la zona de "variación normal", en desvíos
MAX_EDAD_EFTP = 42       # días tras los cuales el eFTP se considera viejo

ZONAS_COGGAN = [
    ("Z1 Recuperación", 0, 55),
    ("Z2 Resistencia", 56, 75),
    ("Z3 Tempo", 76, 90),
    ("Z4 Umbral", 91, 105),
    ("Z5 VO2max", 106, 120),
    ("Z6 Capacidad anaeróbica", 121, 150),
]


# --------------------------------------------------------------------------
# 1. Limpieza: un registro por día, sin duplicados
# --------------------------------------------------------------------------
def _col(df: pd.DataFrame, nombre: str) -> pd.Series:
    if nombre in df:
        return pd.to_numeric(df[nombre], errors="coerce")
    return pd.Series(np.nan, index=df.index)


def _eftp(sport_info) -> float | None:
    if not isinstance(sport_info, list):
        return None
    for item in sport_info:
        if item.get("type") in ("Ride", "VirtualRide") and item.get("eftp"):
            return float(item["eftp"])
    return None


def limpiar_wellness(registros: list[dict]) -> pd.DataFrame:
    """Convierte el JSON de Intervals.icu en una tabla diaria sin duplicados."""
    if not registros:
        return pd.DataFrame()
    df = pd.DataFrame(registros).drop_duplicates(subset="id", keep="last")
    df["fecha"] = pd.to_datetime(df["id"])
    df = df.sort_values("fecha").set_index("fecha")

    out = pd.DataFrame(index=df.index)
    out["hrv"] = _col(df, "hrv")
    out["rhr"] = _col(df, "restingHR")
    horas = _col(df, "sleepSecs") / 3600.0
    out["sueno"] = horas.fillna(_col(df, "sleep"))
    out["ctl"] = _col(df, "ctl")
    out["atl"] = _col(df, "atl")
    out["tsb"] = out["ctl"] - out["atl"]
    sport = df["sportInfo"] if "sportInfo" in df else pd.Series(None, index=df.index)
    out["eftp"] = sport.apply(_eftp)
    return out


def guardar_checkin(ruta: str, registro: dict) -> None:
    """Guarda el check-in con una sola fila por fecha (si existe, la reemplaza)."""
    nuevo = pd.DataFrame([registro])
    if os.path.exists(ruta):
        previo = pd.read_csv(ruta)
        previo = previo[previo["Fecha"] != registro["Fecha"]]
        nuevo = pd.concat([previo, nuevo], ignore_index=True)
    nuevo.sort_values("Fecha").to_csv(ruta, index=False)


# --------------------------------------------------------------------------
# 2. Línea base personal y semáforo
# --------------------------------------------------------------------------
def _base(serie: pd.Series) -> dict | None:
    """Media y desvío de la ventana previa a la semana reciente."""
    s = serie.dropna()
    historico = s.iloc[-VENTANA_BASE:-DIAS_RECIENTES] if len(s) > DIAS_RECIENTES else s.iloc[:0]
    if len(historico) < MIN_DATOS_BASE:
        return None
    media = float(historico.mean())
    sd = max(float(historico.std()), abs(media) * 0.01, 1e-6)
    return {"media": media, "sd": sd, "n": len(historico)}


def evaluar_readiness(df: pd.DataFrame) -> dict:
    """Semáforo comparando contra TU propia línea base."""
    if df.empty:
        return {"estado": "SIN_DATOS", "motivos": ["No hay datos de wellness."]}

    lnhrv = np.log(df["hrv"].where(df["hrv"] > 0))
    base_hrv, base_rhr = _base(lnhrv), _base(df["rhr"])
    if base_hrv is None or base_rhr is None:
        return {
            "estado": "SIN_DATOS",
            "motivos": [f"Se necesitan al menos {MIN_DATOS_BASE} días de VFC y FC en reposo "
                        "para construir tu línea base."],
        }

    hrv_hoy = lnhrv.dropna().iloc[-1]
    hrv_7d = lnhrv.dropna().iloc[-DIAS_RECIENTES:].mean()
    rhr_7d = df["rhr"].dropna().iloc[-DIAS_RECIENTES:].mean()
    rhr_hoy = df["rhr"].dropna().iloc[-1]

    z_hrv_hoy = (hrv_hoy - base_hrv["media"]) / base_hrv["sd"]
    z_hrv_7d = (hrv_7d - base_hrv["media"]) / base_hrv["sd"]
    z_rhr_hoy = (rhr_hoy - base_rhr["media"]) / base_rhr["sd"]
    z_rhr_7d = (rhr_7d - base_rhr["media"]) / base_rhr["sd"]

    banderas = []
    if z_hrv_7d < -BANDA_SD:
        banderas.append("Tu VFC de la última semana está por debajo de tu rango normal.")
    elif z_hrv_hoy < -2:
        banderas.append("La VFC de hoy es una caída fuerte respecto a tu base.")
    if z_rhr_7d > BANDA_SD or z_rhr_hoy > 2:
        banderas.append("Tu FC en reposo está por encima de tu rango normal.")

    sueno = df["sueno"].dropna()
    if len(sueno) >= MIN_DATOS_BASE and sueno.iloc[-1] < sueno.iloc[-30:].quantile(0.25):
        banderas.append("Dormiste menos que en el 75% de tus últimas noches.")

    tsb = df["tsb"].dropna()
    if len(tsb) >= MIN_DATOS_BASE and tsb.iloc[-1] <= tsb.iloc[-VENTANA_BASE:].quantile(0.10):
        banderas.append("Tu forma (TSB) está en el 10% más bajo de los últimos 60 días.")

    estado = "VERDE" if not banderas else ("AMARILLO" if len(banderas) == 1 else "ROJO")
    return {
        "estado": estado,
        "motivos": banderas or ["Tus señales están dentro de tu rango normal."],
        "hrv_hoy_ms": float(np.exp(hrv_hoy)),
        "hrv_base_ms": float(np.exp(base_hrv["media"])),
        "hrv_7d_ms": float(np.exp(hrv_7d)),
        "rhr_hoy": float(rhr_hoy),
        "rhr_base": base_rhr["media"],
        "sueno_hoy": float(sueno.iloc[-1]) if len(sueno) else None,
        "sueno_tipico": float(sueno.iloc[-30:].median()) if len(sueno) else None,
        "dias_base": base_hrv["n"],
    }


def describir_forma(df: pd.DataFrame) -> dict:
    """Describe la forma con tus propios datos (reemplaza el texto fijo)."""
    tsb, ctl = df["tsb"].dropna(), df["ctl"].dropna()
    if len(tsb) < MIN_DATOS_BASE:
        return {"tsb": None, "texto": "Faltan datos de carga para describir tu forma."}

    tsb_hoy = float(tsb.iloc[-1])
    pct = float((tsb.iloc[-VENTANA_BASE:] <= tsb_hoy).mean() * 100)
    if pct >= 80:
        frescura = "Fresco (alto dentro de tu rango de los últimos 60 días)"
    elif pct <= 20:
        frescura = "Fatigado (bajo dentro de tu rango de los últimos 60 días)"
    else:
        frescura = "Equilibrado dentro de tu rango habitual"

    cambio = float(ctl.iloc[-1] - ctl.iloc[-15]) if len(ctl) >= 15 else 0.0
    umbral = abs(float(ctl.iloc[-1])) * 0.03
    tendencia = ("subiendo" if cambio > umbral else "bajando" if cambio < -umbral else "estable")
    return {"tsb": tsb_hoy, "percentil": pct, "tendencia_fitness": tendencia,
            "cambio_ctl_14d": cambio, "texto": f"{frescura}. Fitness {tendencia}."}


# --------------------------------------------------------------------------
# 3. FTP estimado desde tus datos y zonas derivadas
# --------------------------------------------------------------------------
def potencia_critica(mejores: dict[int, float]) -> dict | None:
    """Modelo de 2 parámetros: trabajo = CP * t + W'. mejores = {segundos: watts}."""
    pts = [(t, p * t) for t, p in mejores.items() if 120 <= t <= 1800 and p]
    if len(pts) < 3:
        return None
    t, w = zip(*pts)
    cp, w_prime = np.polyfit(t, w, 1)
    return {"cp": float(cp), "w_prime_kj": float(w_prime) / 1000.0}


def estimar_ftp(df: pd.DataFrame, mejores: dict[int, float] | None = None) -> dict:
    """Combina el eFTP de Intervals.icu con modelos sobre tus mejores esfuerzos."""
    fuentes = {}
    eftp = df["eftp"].dropna() if "eftp" in df else pd.Series(dtype=float)
    if len(eftp):
        edad = (df.index[-1] - eftp.index[-1]).days
        fuentes["eFTP Intervals.icu"] = {"watts": float(eftp.iloc[-1]), "edad_dias": edad}
    if mejores:
        cp = potencia_critica(mejores)
        if cp:
            fuentes["Potencia crítica (modelo)"] = {"watts": cp["cp"], "edad_dias": None}
        if mejores.get(1200):
            fuentes["95% de tu mejor 20 min"] = {"watts": 0.95 * mejores[1200], "edad_dias": None}

    if not fuentes:
        return {"ftp": None, "fuente": None, "fuentes": {},
                "aviso": "No hay datos de potencia suficientes para estimar tu FTP."}

    elegido = "eFTP Intervals.icu" if "eFTP Intervals.icu" in fuentes else next(iter(fuentes))
    aviso = None
    edad = fuentes[elegido]["edad_dias"]
    if edad is not None and edad > MAX_EDAD_EFTP:
        aviso = (f"Tu último eFTP tiene {edad} días: sin esfuerzos máximos recientes "
                 "la estimación puede estar desactualizada.")
    return {"ftp": round(fuentes[elegido]["watts"]), "fuente": elegido,
            "fuentes": fuentes, "aviso": aviso}


def zonas_potencia(ftp: float) -> list[dict]:
    """Zonas de Coggan como porcentaje de tu FTP estimado."""
    return [{"zona": n, "min_w": round(ftp * a / 100), "max_w": round(ftp * b / 100)}
            for n, a, b in ZONAS_COGGAN]


# --------------------------------------------------------------------------
# 4. Calibración: ¿el semáforo coincide con cómo te sientes?
# --------------------------------------------------------------------------
def calibracion(dias: pd.DataFrame) -> pd.DataFrame:
    """Promedios de tus sensaciones y RPE según el color del semáforo."""
    if dias.empty or "estado" not in dias:
        return pd.DataFrame()
    cols = ["sensacion", "piernas", "animo", "dolor", "rpe"]
    d = dias[dias["estado"].isin(["VERDE", "AMARILLO", "ROJO"])]
    d = d.dropna(subset=cols, how="all")
    if d.empty:
        return pd.DataFrame()
    g = d.groupby("estado").agg(dias=("estado", "size"),
                                **{c: (c, "mean") for c in cols})
    orden = [e for e in ("VERDE", "AMARILLO", "ROJO") if e in g.index]
    return g.reindex(orden).round(1)
