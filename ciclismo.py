"""Panel Inteligente de Autorregulación & Rendimiento Ciclista."""

from datetime import date, timedelta
import os

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import almacen
import fisiologia as fis
import vista_entrenos

CARPETA = os.path.dirname(os.path.abspath(__file__))
CSV_VIEJO = os.path.join(CARPETA, "historial_entrenamiento.csv")
COLUMNAS = ["hrv", "rhr", "sueno", "ctl", "atl", "tsb", "eftp"]

st.set_page_config(page_title="App Autorregulada - Luciano", layout="wide")

st.title("⚡ Panel Inteligente de Autorregulación & Rendimiento Ciclista")
st.markdown("---")


# --------------------------------------------------------------------------
# Datos
# --------------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def cargar_wellness(athlete_id, api_key):
    """Descarga 90 días de wellness en una sola llamada (cacheada 10 min)."""
    hoy = date.today()
    url = f"https://intervals.icu/api/v1/athlete/{athlete_id}/wellness"
    params = {
        "oldest": (hoy - timedelta(days=90)).isoformat(),
        "newest": hoy.isoformat(),
    }
    try:
        r = requests.get(url, auth=("API_KEY", api_key),
                         params=params, timeout=10)
    except requests.RequestException as e:
        return pd.DataFrame(), f"Error de conexión ({e.__class__.__name__})."
    if r.status_code != 200:
        return pd.DataFrame(), f"Intervals.icu respondió con código {r.status_code}."
    return fis.limpiar_wellness(r.json()), None


def ultimo_valor(serie, minimo, maximo):
    """Último dato disponible, o el mínimo permitido si no hay datos."""
    s = serie.dropna()
    valor = float(s.iloc[-1]) if len(s) else float(minimo)
    return min(max(valor, float(minimo)), float(maximo))


# Migración única del CSV antiguo a la base de datos
if os.path.exists(CSV_VIEJO):
    try:
        n_importados = almacen.importar_csv(CSV_VIEJO)
        os.replace(CSV_VIEJO, CSV_VIEJO + ".migrado")
        st.sidebar.success(
            f"Importé {n_importados} check-ins del CSV antiguo a la base de datos.")
    except Exception as e:  # no frenar la app por la migración
        st.sidebar.warning(
            f"No pude migrar el CSV antiguo ({e.__class__.__name__}).")

# --------------------------------------------------------------------------
# Barra lateral: conexión y registro matutino
# --------------------------------------------------------------------------
st.sidebar.header("🔗 Conexión Intervals.icu")
intervals_id = st.sidebar.text_input(
    "Athlete ID", value=os.environ.get("INTERVALS_ID", ""))
intervals_api_key = st.sidebar.text_input(
    "API Key", value=os.environ.get("INTERVALS_API_KEY", ""), type="password"
)

if intervals_id and intervals_api_key:
    df_api, error_api = cargar_wellness(intervals_id, intervals_api_key)
    if error_api:
        st.sidebar.warning(f"{error_api} Usando tu historia guardada.")
    elif df_api.empty:
        st.sidebar.warning(
            "Intervals.icu no devolvió registros. Usando tu historia guardada.")
    else:
        almacen.guardar_wellness(df_api)
        st.sidebar.success("¡Sincronizado con Intervals.icu!")

dias = almacen.leer_dias()
df_base = dias.reindex(columns=COLUMNAS)
hoy_ts = pd.Timestamp(date.today())
guardado_hoy = dias.loc[hoy_ts] if hoy_ts in dias.index else None


def previo(columna, defecto):
    """Valor ya guardado hoy para esa columna, o el valor por defecto."""
    if guardado_hoy is None:
        return defecto
    valor = guardado_hoy.get(columna)
    return defecto if pd.isna(valor) else type(defecto)(valor)


st.sidebar.header("📊 Registro Matutino")
vfc_hoy = st.sidebar.number_input(
    "VFC Nocturna (ms)", min_value=10.0, max_value=150.0,
    value=ultimo_valor(df_base["hrv"], 10, 150), step=1.0,
)
rhr_hoy = st.sidebar.number_input(
    "FC Reposo (bpm)", min_value=30.0, max_value=90.0,
    value=ultimo_valor(df_base["rhr"], 30, 90), step=1.0,
)
sueno_hoy = st.sidebar.number_input(
    "Horas de Sueño", min_value=1.0, max_value=15.0,
    value=round(ultimo_valor(df_base["sueno"], 1, 15) * 2) / 2, step=0.5,
)

st.sidebar.markdown("---")
st.sidebar.header("🧭 Cómo te sientes")
st.sidebar.caption("Déjalo en 0 si hoy no quieres registrarlo.")
sensacion = st.sidebar.slider(
    "Sensación general (1 mal – 5 muy bien)", 0, 5, previo("sensacion", 0))
piernas = st.sidebar.slider(
    "Piernas (1 pesadas – 5 livianas)", 0, 5, previo("piernas", 0))
animo = st.sidebar.slider(
    "Ánimo y motivación (1 bajo – 5 alto)", 0, 5, previo("animo", 0))
dolor = st.sidebar.slider(
    "Dolor muscular (1 nada – 5 mucho)", 0, 5, previo("dolor", 0))
rpe = st.sidebar.slider(
    "RPE de la sesión (1 fácil – 10 máximo)", 0, 10, previo("rpe", 0))
notas = st.sidebar.text_area("Notas", value=previo("notas", ""))

st.sidebar.markdown("---")
st.sidebar.header("⚡ Umbral de potencia")
ftp_manual = st.sidebar.number_input(
    "FTP manual (W)", min_value=0, max_value=600, value=0, step=5,
    help="Déjalo en 0 para usar el FTP estimado desde tus datos.",
)

# --------------------------------------------------------------------------
# Cálculos: todo sale de tus datos
# --------------------------------------------------------------------------
df_eval = df_base.copy()
df_eval.loc[hoy_ts, ["hrv", "rhr", "sueno"]] = [vfc_hoy, rhr_hoy, sueno_hoy]
df_eval = df_eval.sort_index().astype(float)

semaforo = fis.evaluar_readiness(df_eval)
forma = fis.describir_forma(df_eval)
ftp_est = fis.estimar_ftp(df_eval)
ftp = ftp_manual or ftp_est["ftp"]
zonas = fis.zonas_potencia(ftp) if ftp else []


def zona(prefijo):
    return next((z for z in zonas if z["zona"].startswith(prefijo)), None)


def rango_w(z):
    return f"{z['min_w']}–{z['max_w']} W" if z else "tus zonas de Z2"


def prescribir(estado):
    z1, z2, z4 = zona("Z1"), zona("Z2"), zona("Z4")
    if estado == "VERDE":
        return (f"Sesión clave: umbral (Z4: {rango_w(z4)}) o trabajo de torque. "
                f"Calienta en Z2 ({rango_w(z2)}).")
    if estado == "AMARILLO":
        return f"Rodaje Z2 controlado ({rango_w(z2)}), sin picos de intensidad."
    if estado == "ROJO":
        tope = f"hasta {z1['max_w']} W" if z1 else "muy suave"
        return f"Descanso o recuperación muy suave (Z1, {tope})."
    return "Completa tus check-ins diarios para construir tu línea base."


estado = semaforo["estado"]
prescripcion = prescribir(estado)

# --------------------------------------------------------------------------
# Métricas
# --------------------------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)
with col1:
    base = semaforo.get("hrv_base_ms")
    st.metric(
        label="VFC Nocturna",
        value=f"{vfc_hoy:g} ms",
        delta=f"{vfc_hoy - base:+.1f} ms vs tu base" if base else None,
    )
with col2:
    base = semaforo.get("rhr_base")
    st.metric(
        label="FC Reposo",
        value=f"{rhr_hoy:g} bpm",
        delta=f"{rhr_hoy - base:+.1f} bpm vs tu base" if base else None,
        delta_color="inverse",
    )
with col3:
    tipico = semaforo.get("sueno_tipico")
    st.metric(
        label="Horas de Sueño",
        value=f"{sueno_hoy:g} h",
        delta=f"{sueno_hoy - tipico:+.1f} h vs tu mediana" if tipico else None,
    )
with col4:
    tsb = forma.get("tsb")
    st.metric(
        label="Estado de Forma (TSB)",
        value=f"{tsb:+.0f}" if tsb is not None else "—",
        delta=(f"Fitness {forma['tendencia_fitness']}"
               if forma.get("tendencia_fitness") else None),
        delta_color="off",
    )
if forma.get("texto"):
    st.caption(forma["texto"])

# --------------------------------------------------------------------------
# Semáforo
# --------------------------------------------------------------------------
st.markdown("### 🚦 Evaluación Fisiológica y Prescripción")

motivos = "\n".join(f"- {m}" for m in semaforo["motivos"])
detalle = f"**Análisis:**\n{motivos}\n\n**Prescripción:** {prescripcion}"

if estado == "VERDE":
    st.success(f"**ESTADO: VERDE (Sistema Óptimo)**\n\n{detalle}")
elif estado == "AMARILLO":
    st.warning(f"**ESTADO: AMARILLO (Fatiga en Transición)**\n\n{detalle}")
elif estado == "ROJO":
    st.error(f"**ESTADO: ROJO (Protección Sistémica)**\n\n{detalle}")
else:
    st.info(f"**SIN DATOS SUFICIENTES**\n\n{detalle}")

if semaforo.get("dias_base"):
    st.caption(
        f"Tu línea base se calcula con {semaforo['dias_base']} días de datos propios.")

# --------------------------------------------------------------------------
# FTP y zonas
# --------------------------------------------------------------------------
st.markdown("---")
st.markdown("### ⚡ FTP y Zonas de Potencia (calculadas desde tus datos)")

if ftp:
    origen = "manual" if ftp_manual else ftp_est["fuente"]
    c1, c2 = st.columns([1, 2])
    with c1:
        st.metric("FTP en uso", f"{ftp} W")
        st.caption(f"Fuente: {origen}")
        if not ftp_manual and ftp_est["aviso"]:
            st.warning(ftp_est["aviso"])
    with c2:
        tabla = pd.DataFrame(zonas).rename(
            columns={"zona": "Zona", "min_w": "Desde (W)", "max_w": "Hasta (W)"})
        st.dataframe(tabla, hide_index=True, use_container_width=True)
else:
    st.info("Sin datos de potencia para estimar tu FTP. Conéctate a Intervals.icu "
            "o ingresa un FTP manual en la barra lateral.")

# --------------------------------------------------------------------------
# Guardado del check-in (una sola fila por fecha, en la base de datos)
# --------------------------------------------------------------------------
if st.sidebar.button("Guardar Registro Matutino"):
    almacen.guardar_checkin(date.today().isoformat(), {
        "hrv": vfc_hoy,
        "rhr": rhr_hoy,
        "sueno": sueno_hoy,
        "estado": estado,
        "prescripcion": prescripcion,
        "sensacion": sensacion or None,
        "piernas": piernas or None,
        "animo": animo or None,
        "dolor": dolor or None,
        "rpe": rpe or None,
        "notas": notas or None,
    })
    st.sidebar.success(
        "¡Registro guardado! (si ya existía el de hoy, se actualizó)")
    dias = almacen.leer_dias()

# --------------------------------------------------------------------------
# Tendencias, historial y calibración
# --------------------------------------------------------------------------
if not dias.empty:
    st.markdown("---")
    st.markdown("### 📈 Tendencias, Historial y Calibración")
    tab1, tab2, tab3 = st.tabs(
        ["VFC & Reposo", "Historial", "Calibración del semáforo"])

    with tab1:
        st.markdown("**Evolución VFC Nocturna y FC en Reposo**")
        evolucion = dias[["hrv", "rhr"]].dropna(how="all")
        if evolucion.empty:
            st.info("Todavía no hay datos de VFC y FC en reposo.")
        else:
            st.line_chart(evolucion.rename(
                columns={"hrv": "VFC", "rhr": "RHR"}))

    with tab2:
        st.markdown("**Tu historia diaria (una fila por fecha)**")
        vista = dias.sort_index(ascending=False).reset_index()
        vista["fecha"] = vista["fecha"].dt.strftime("%Y-%m-%d")
        st.dataframe(vista, hide_index=True, use_container_width=True)
        st.caption("Si estás conectado a Intervals.icu, los datos de wellness de un día "
                   "borrado se vuelven a descargar; solo se pierden tus sensaciones y notas.")
        fecha_borrar = st.selectbox("Borrar un día", list(vista["fecha"]))
        if st.button("🗑️ Borrar día seleccionado"):
            almacen.borrar_dia(fecha_borrar)
            st.rerun()

    with tab3:
        st.markdown("**¿El semáforo coincide con cómo te sientes?**")
        cal = fis.calibracion(dias)
        if cal.empty:
            st.info("Guarda tus check-ins con sensaciones durante unas semanas y aquí "
                    "verás si los días verdes, amarillos y rojos coinciden con cómo te sentiste.")
        else:
            st.dataframe(
                cal.rename(columns={"dias": "Días", "sensacion": "Sensación",
                                    "piernas": "Piernas", "animo": "Ánimo",
                                    "dolor": "Dolor", "rpe": "RPE"}),
                use_container_width=True,
            )
            st.caption("Sensación, piernas y ánimo: más alto es mejor. Dolor: más bajo es mejor. "
                       "Si los días rojos no se sienten peor que los verdes, el semáforo "
                       "necesita ajuste. Con menos de 10 días por color, tómalo como orientativo.")


# --------------------------------------------------------------------------
# Gráfico de carga: CTL, ATL y TSB
# --------------------------------------------------------------------------
def mostrar_grafico_ctl_atl(datos):
    carga = datos[["ctl", "atl", "tsb"]].dropna(how="all").tail(30)
    if carga.empty:
        st.info("No hay datos históricos suficientes para mostrar el gráfico de carga.")
        return

    fig = go.Figure()
    series = [
        ("ctl", "Fitness (CTL)", "blue",
         "<i>Tu entrenamiento a largo plazo (42 días). Base aeróbica acumulada.</i>"),
        ("atl", "Fatiga (ATL)", "orange",
         "<i>El cansancio de tus últimos 7 días. Sube rápido tras sesiones duras.</i>"),
        ("tsb", "Forma (TSB)", "green",
         "<i>Fitness menos Fatiga. Positivo = fresco. Negativo = asimilando carga.</i>"),
    ]
    for col, nombre, color, ayuda in series:
        fig.add_trace(go.Scatter(
            x=carga.index, y=carga[col], mode="lines", name=nombre,
            line=dict(color=color, width=2),
            hovertemplate=f"<b>{nombre}: %{{y:.1f}}</b><br>{ayuda}<extra></extra>",
        ))
    fig.update_layout(
        title="Evolución de Carga de Entrenamiento (30 Días)",
        xaxis_title="Fecha", yaxis_title="Valor", template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom",
                    y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)


st.markdown("---")
st.subheader("📊 Análisis de Carga de Entrenamiento")

if dias[["ctl", "atl"]].notna().any().any():
    mostrar_grafico_ctl_atl(dias)
else:
    st.info("💡 Conecta Intervals.icu en la barra lateral para ver las curvas de "
            "Fitness, Fatiga y Forma.")

vista_entrenos.seccion_entrenamientos(intervals_id, intervals_api_key, ftp)
