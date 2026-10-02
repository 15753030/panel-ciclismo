"""Pantalla de entrenamientos: lista, detalle y todos los datos disponibles."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import almacen
import entrenos

TIPOS = ["Sin definir", "Rodaje Z2", "Sweet spot", "Umbral", "VO2max",
         "Torque / fuerza", "Competencia", "Recuperación", "Otro"]

COLUMNAS_LISTA = [
    ("start_date_local", "Fecha"), ("name", "Nombre"), ("type", "Tipo"),
    ("moving_time", "Duración"), ("distance", "Km"),
    ("icu_average_watts", "Pot. media (W)"), ("icu_weighted_avg_watts", "NP (W)"),
    ("average_heartrate", "FC media"), ("icu_training_load", "Carga (TSS)"),
    ("perceived_exertion", "RPE"),
]
NOMBRES_DURACION = {5: "5 s", 30: "30 s", 60: "1 min", 300: "5 min",
                    600: "10 min", 1200: "20 min", 3600: "60 min"}


@st.cache_data(ttl=600, show_spinner=False)
def _lista(athlete_id, api_key, dias):
    return entrenos.listar_actividades(athlete_id, api_key, dias)


@st.cache_data(ttl=3600, show_spinner=False)
def _detalle(api_key, actividad_id):
    return entrenos.detalle_actividad(api_key, actividad_id)


@st.cache_data(ttl=3600, show_spinner=False)
def _streams(api_key, actividad_id):
    return entrenos.streams_actividad(api_key, actividad_id)


# --------------------------------------------------------------------------
# Formato
# --------------------------------------------------------------------------
def _valido(v):
    return v is not None and not (isinstance(v, float) and pd.isna(v))


def _primero(d: dict, *claves):
    for k in claves:
        if _valido(d.get(k)):
            return d[k]
    return None


def _hms(seg):
    if not _valido(seg):
        return "—"
    seg = int(seg)
    return f"{seg // 3600}:{(seg % 3600) // 60:02d}:{seg % 60:02d}"


def _num(v, formato="{:.0f}", sufijo=""):
    try:
        return formato.format(float(v)) + sufijo if _valido(v) else "—"
    except (TypeError, ValueError):
        return "—"


def _etiqueta(fila: dict) -> str:
    fecha = str(fila.get("start_date_local", ""))[:10]
    nombre = fila.get("name") or fila.get("type") or "Entrenamiento"
    return f"{fecha} · {nombre} · {_hms(fila.get('moving_time'))}"


# --------------------------------------------------------------------------
# Pantalla
# --------------------------------------------------------------------------
def seccion_entrenamientos(athlete_id, api_key, ftp_app):
    st.markdown("---")
    st.subheader("🚴 Entrenamientos")
    if not (athlete_id and api_key):
        st.info("Conecta Intervals.icu en la barra lateral para ver tus entrenamientos.")
        return

    dias = st.selectbox("Período", [14, 30, 60, 90], index=1,
                        format_func=lambda d: f"Últimos {d} días")
    acts, error = _lista(athlete_id, api_key, dias)
    if error:
        st.warning(error)
        return
    if acts.empty or "id" not in acts:
        st.info("No hay entrenamientos en ese período.")
        return

    _tabla_lista(acts)
    ids = list(acts["id"].astype(str))
    etiquetas = {i: _etiqueta(f) for i, (_, f) in zip(ids, acts.iterrows())}
    elegido = st.selectbox("Elige un entrenamiento para ver todo su detalle", ids,
                           format_func=lambda i: etiquetas[i])
    fila = acts[acts["id"].astype(str) == elegido].iloc[0].to_dict()
    _detalle_vista(api_key, elegido, fila, ftp_app)


def _tabla_lista(acts: pd.DataFrame):
    vista = pd.DataFrame()
    for clave, titulo in COLUMNAS_LISTA:
        if clave in acts:
            vista[titulo] = acts[clave]
    if vista.empty:
        return
    if "Fecha" in vista:
        vista["Fecha"] = vista["Fecha"].astype(str).str[:10]
    if "Duración" in vista:
        vista["Duración"] = vista["Duración"].apply(_hms)
    if "Km" in vista:
        vista["Km"] = (pd.to_numeric(vista["Km"], errors="coerce") / 1000).round(1)
    st.dataframe(vista, hide_index=True, use_container_width=True)


def _detalle_vista(api_key, actividad_id, fila, ftp_app):
    detalle, error_d = _detalle(api_key, actividad_id)
    if error_d or not detalle:
        st.warning(f"No pude traer el detalle completo. {error_d or ''} Muestro el resumen.")
        detalle = fila
    streams, error_s = _streams(api_key, actividad_id)
    ftp = _primero(detalle, "icu_ftp") or ftp_app
    propias = entrenos.metricas_propias(streams, ftp) if not streams.empty else {}

    t_resumen, t_graf, t_metricas, t_inter, t_mios, t_campos = st.tabs([
        "Resumen", "Gráficos", "Mis métricas vs Intervals", "Intervalos",
        "Mis datos", "Todos los campos"])

    with t_resumen:
        _tab_resumen(detalle, ftp)
    with t_graf:
        _tab_graficos(streams, error_s)
    with t_metricas:
        _tab_metricas(detalle, propias, ftp, streams.empty)
    with t_inter:
        _tab_intervalos(detalle)
    with t_mios:
        _tab_mis_datos(actividad_id)
    with t_campos:
        _tab_campos(detalle)


def _tab_resumen(d, ftp):
    dist = _primero(d, "distance")
    items = [
        ("Duración", _hms(_primero(d, "moving_time", "elapsed_time"))),
        ("Distancia", _num(dist / 1000 if dist else None, "{:.1f}", " km")),
        ("Desnivel", _num(_primero(d, "total_elevation_gain"), "{:.0f}", " m")),
        ("Potencia media", _num(_primero(d, "icu_average_watts", "average_watts"), "{:.0f}", " W")),
        ("Potencia normalizada", _num(_primero(d, "icu_weighted_avg_watts"), "{:.0f}", " W")),
        ("Carga (TSS)", _num(_primero(d, "icu_training_load"))),
        ("Intensidad", _num(_primero(d, "icu_intensity"), "{:.1f}")),
        ("FTP de ese día", _num(_primero(d, "icu_ftp") or ftp, "{:.0f}", " W")),
        ("FC media", _num(_primero(d, "average_heartrate"), "{:.0f}", " bpm")),
        ("FC máxima", _num(_primero(d, "max_heartrate"), "{:.0f}", " bpm")),
        ("Cadencia media", _num(_primero(d, "average_cadence"), "{:.0f}", " rpm")),
        ("Calorías", _num(_primero(d, "calories"))),
    ]
    for i in range(0, len(items), 4):
        for col, (etiqueta, valor) in zip(st.columns(4), items[i:i + 4]):
            col.metric(etiqueta, valor)
    st.caption("Los valores que Intervals.icu no entrega para este entreno aparecen como —. "
               "En la pestaña «Todos los campos» ves todo lo que sí llegó.")


def _tab_graficos(streams, error):
    if error:
        st.warning(error)
    if streams.empty:
        st.info("Este entreno no trae datos segundo a segundo.")
        return
    minutos = streams.index / 60.0
    paso = max(1, len(streams) // 2000)
    series = [
        ("watts", "Potencia (W, media de 30 s)", "orange", 30),
        ("heartrate", "Frecuencia cardíaca (bpm)", "red", 1),
        ("cadence", "Cadencia (rpm)", "deepskyblue", 5),
        ("altitude", "Altitud (m)", "gray", 1),
    ]
    dibujados = 0
    for col, titulo, color, suavizado in series:
        if col not in streams or not streams[col].notna().any():
            continue
        y = streams[col].rolling(suavizado, min_periods=1).mean() if suavizado > 1 else streams[col]
        fig = go.Figure(go.Scatter(x=minutos[::paso], y=y.iloc[::paso], mode="lines",
                                   line=dict(color=color, width=1.5), name=titulo))
        fig.update_layout(title=titulo, xaxis_title="Minutos", height=260,
                          template="plotly_dark", margin=dict(l=10, r=10, t=40, b=30),
                          showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        dibujados += 1
    if not dibujados:
        st.info("No hay potencia, pulso ni cadencia en este entreno.")


def _tab_metricas(d, propias, ftp, sin_streams):
    if sin_streams or not propias:
        st.info("Para calcular tus métricas hacen falta los datos de potencia segundo a segundo.")
        return
    filas = [
        ("Potencia media (W)", propias.get("pot_media"), _primero(d, "icu_average_watts", "average_watts"), True),
        ("Potencia normalizada (W)", propias.get("np"), _primero(d, "icu_weighted_avg_watts"), True),
        ("TSS", propias.get("tss"), _primero(d, "icu_training_load"), True),
        ("Factor de intensidad (IF)", propias.get("if"), _primero(d, "icu_intensity"), False),
        ("Índice de variabilidad", propias.get("vi"), _primero(d, "icu_variability_index"), True),
        ("Eficiencia (NP / FC)", propias.get("ef"), _primero(d, "icu_efficiency_factor"), True),
        ("Desacople potencia-pulso (%)", propias.get("desacople_pct"), _primero(d, "decoupling"), True),
        ("Trabajo (kJ)", propias.get("trabajo_kj"), None, False),
    ]
    tabla = []
    for nombre, mio, de_icu, comparar in filas:
        dif = (float(mio) - float(de_icu)) if comparar and _valido(mio) and _valido(de_icu) else None
        tabla.append({"Métrica": nombre, "Calculada por ti": _num(mio, "{:.2f}"),
                      "Intervals.icu": _num(de_icu, "{:.2f}"),
                      "Diferencia": _num(dif, "{:+.2f}")})
    st.dataframe(pd.DataFrame(tabla), hide_index=True, use_container_width=True)
    st.caption(f"Calculado con un FTP de {_num(ftp)} W. Intervals.icu puede mostrar la intensidad "
               "en porcentaje, por eso ahí no se calcula la diferencia. Pequeñas diferencias son "
               "normales: cada programa trata las pausas y el suavizado a su manera. El desacople "
               "solo tiene sentido en rodajes constantes, no en entrenos con series.")

    mejores = propias.get("mejores", {})
    if mejores:
        st.markdown("**Mejores esfuerzos de este entreno**")
        st.dataframe(pd.DataFrame([{"Duración": NOMBRES_DURACION[s], "Potencia media (W)": round(w)}
                                   for s, w in mejores.items()]),
                     hide_index=True, use_container_width=True)

    zonas = propias.get("zonas_s")
    if zonas:
        total = sum(zonas.values()) or 1
        st.markdown("**Tiempo en cada zona de potencia (según tu FTP)**")
        st.dataframe(pd.DataFrame([{"Zona": z, "Tiempo": _hms(s), "% del total": round(s / total * 100, 1)}
                                   for z, s in zonas.items()]),
                     hide_index=True, use_container_width=True)


def _tab_intervalos(d):
    intervalos = d.get("icu_intervals")
    if not isinstance(intervalos, list) or not intervalos:
        st.info("Este entreno no trae intervalos detectados (o la API los entrega con otro nombre). "
                "Revisa «Todos los campos».")
        return
    df = pd.DataFrame([i for i in intervalos if isinstance(i, dict)])
    preferidas = ["type", "label", "moving_time", "distance", "average_watts",
                  "weighted_average_watts", "average_heartrate", "max_heartrate",
                  "average_cadence", "intensity", "training_load", "decoupling"]
    columnas = [c for c in preferidas if c in df]
    st.dataframe(df[columnas] if columnas else df, hide_index=True, use_container_width=True)


def _tab_mis_datos(actividad_id):
    previo = almacen.leer_extra_actividad(actividad_id)
    st.caption("Lo que anotes aquí se guarda en tu base de datos, no en Intervals.icu.")
    tipo_prev = previo.get("tipo") if previo.get("tipo") in TIPOS else "Sin definir"
    tipo = st.selectbox("Tipo de sesión", TIPOS, index=TIPOS.index(tipo_prev),
                        key=f"tipo_{actividad_id}")
    rpe = st.slider("RPE de la sesión (1 fácil – 10 máximo)", 0, 10,
                    int(previo.get("rpe") or 0), key=f"rpe_{actividad_id}")
    sens = st.slider("Sensación durante el entreno (1 mal – 5 muy bien)", 0, 5,
                     int(previo.get("sensacion") or 0), key=f"sens_{actividad_id}")
    notas = st.text_area("Notas", value=previo.get("notas") or "", key=f"notas_{actividad_id}")
    if st.button("Guardar mis datos de este entreno", key=f"guardar_{actividad_id}"):
        almacen.guardar_extra_actividad(
            actividad_id, tipo=None if tipo == "Sin definir" else tipo,
            rpe=rpe or None, sensacion=sens or None, notas=notas or None)
        st.success("¡Guardado!")


def _tab_campos(d):
    plano = entrenos.aplanar(d)
    filtro = st.text_input("Buscar un campo", value="", key="filtro_campos")
    tabla = pd.DataFrame({"Campo": list(plano), "Valor": [str(v) if v is not None else "—"
                                                          for v in plano.values()]})
    if filtro:
        tabla = tabla[tabla["Campo"].str.contains(filtro, case=False, regex=False)]
    st.caption(f"{len(plano)} campos recibidos de Intervals.icu para este entreno.")
    st.dataframe(tabla, hide_index=True, use_container_width=True)
