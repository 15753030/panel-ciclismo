"""Panel Inteligente de Autorregulación & Rendimiento Ciclista."""

import os
from datetime import datetime, timedelta
import pandas as pd
import requests  # <--- AGREGA ESTA LÍNEA AQUÍ
import streamlit as st

st.set_page_config(page_title="App Autorregulada - Luciano", layout="wide")

st.title("⚡ Panel Inteligente de Autorregulación & Rendimiento Ciclista")
st.markdown("---")

# --- Configuración y Sincronización Intervals.icu & Registro Matutino ---
st.sidebar.header("🔗 Conexión Intervals.icu")
intervals_id = st.sidebar.text_input("Athlete ID", value="")
intervals_api_key = st.sidebar.text_input(
    "API Key", value="", type="password"
)

# Valores por defecto iniciales
vfc_input_default = 58.0
rhr_input_default = 46.0
sueno_input_default = 8.0
tsb_actual = 7.0

# Intentamos traer datos automáticos de la API si están las credenciales
if intervals_id and intervals_api_key:
    try:
        # Primero intentamos con el día de hoy
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        url = f"https://intervals.icu/api/v1/athlete/{intervals_id}/wellness/{fecha_hoy}"
        response = requests.get(url, auth=("API_KEY", intervals_api_key), timeout=5)
        
        # Si hoy da 404 (no existe registro creado aún), caemos en ayer
        if response.status_code == 404:
            fecha_ayer = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            url = f"https://intervals.icu/api/v1/athlete/{intervals_id}/wellness/{fecha_ayer}"
            response = requests.get(url, auth=("API_KEY", intervals_api_key), timeout=5)

        if response.status_code == 200:
            data_wellness = response.json()
            if data_wellness:
                if "hrv" in data_wellness and data_wellness["hrv"] is not None:
                    vfc_input_default = float(data_wellness["hrv"])
                if "restingHR" in data_wellness and data_wellness["restingHR"] is not None:
                    rhr_input_default = float(data_wellness["restingHR"])
                if "ctl" in data_wellness and "atl" in data_wellness:
                    ctl = data_wellness.get("ctl", 0) or 0
                    atl = data_wellness.get("atl", 0) or 0
                    tsb_actual = ctl - atl
            st.sidebar.success("¡Sincronizado con Intervals.icu!")
        else:
            st.sidebar.warning(f"Sin registro activo (Código {response.status_code}). Usando manual.")
    except Exception:
        st.sidebar.warning("Usando valores manuales (error de conexión).")

st.sidebar.header("📊 Registro Matutino")
vfc_hoy = st.sidebar.number_input(
    "VFC Nocturna (ms)", min_value=10.0, max_value=150.0, value=vfc_input_default, step=1.0
)
rhr_hoy = st.sidebar.number_input(
    "FC Reposo (bpm)", min_value=30.0, max_value=90.0, value=rhr_input_default, step=1.0
)
sueno_hoy = st.sidebar.number_input(
    "Horas de Sueño", min_value=1.0, max_value=15.0, value=sueno_input_default, step=0.5
)

# --- Control de Zonas de Potencia Dinámicas ---
st.sidebar.markdown("---")
st.sidebar.header("⚡ Configuración de Umbrales")
ftp_usuario = st.sidebar.number_input("FTP Base (W)", value=290, step=5)
st.sidebar.warning("Usando valores manuales (sin conexión activa).")

VFC_BASE_MEDIA = 58.0
RHR_BASE_MEDIA = 46.0

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric(
        label="VFC Nocturna",
        value=f"{vfc_hoy} ms",
        delta=f"{vfc_hoy - VFC_BASE_MEDIA:+.1f} ms vs base",
    )
with col2:
    st.metric(
        label="FC Reposo",
        value=f"{rhr_hoy} bpm",
        delta=f"{rhr_hoy - RHR_BASE_MEDIA:+.1f} bpm",
        delta_color="inverse",
    )
with col3:
    st.metric(label="Horas de Sueño", value=f"{sueno_hoy} h", delta="+1.0 h")
with col4:
    st.metric(
        label="Estado de Forma (TSB)",
        value="+7 (Fresco)",
        delta="Asimilando carga",
    )

st.markdown(
    "### 🚦 Evaluación Fisiológica Inteligente y Prescripción Dinámica"
)


def evaluar_entrenamiento_inteligente(vfc, rhr, vfc_base):
    """Evalúa el estado fisiológico y retorna la prescripción del día."""
    if rhr < 42:
        return (
            "VERDE",
            "¡Excelente eficiencia parasimpática! FC en reposo < 42 bpm.",
            "Sesión Clave Óptima: Torque (5x8 min @265-296W) o Umbral.",
        )
    if vfc < 45 or rhr > 48:
        return (
            "ROJO",
            f"Supresión parasimpática (VFC {vfc} ms) o pulso elevado (RHR {rhr} bpm).",
            "Descanso Total (Recuperación total sin bicicleta).",
        )
    if (45 <= vfc <= 50) or (45 <= rhr <= 48) or (vfc < vfc_base - 8):
        return (
            "AMARILLO",
            f"Asimilación / Estrés leve (VFC {vfc} ms / RHR {rhr} bpm).",
            "Rodaje Z2 controlado (180-215W) sin picos de lactato.",
        )
    return (
        "VERDE",
        f"Sistema nervioso en rango óptimo (VFC {vfc} ms / RHR {rhr} bpm).",
        "Activación / Sesión Clave: Rodaje Pre-Fondo 1.5h Z2 o Umbral.",
    )


estado, motivo, prescripcion = evaluar_entrenamiento_inteligente(
    vfc_hoy, rhr_hoy, VFC_BASE_MEDIA
)

if estado == "VERDE":
    mensaje = (
        f"**ESTADO: VERDE (Sistema Óptimo)**\n\n"
        f"**Análisis:** {motivo}\n\n"
        f"**Prescripción:** {prescripcion}"
    )
    st.success(mensaje)
elif estado == "AMARILLO":
    mensaje = (
        f"**ESTADO: AMARILLO (Fatiga en Transición)**\n\n"
        f"**Análisis:** {motivo}\n\n"
        f"**Prescripción:** {prescripcion}"
    )
    st.warning(mensaje)
else:
    mensaje = (
        f"**ESTADO: ROJO (Protección Sistémica)**\n\n"
        f"**Análisis:** {motivo}\n\n"
        f"**Prescripción:** {prescripcion}"
    )
    st.error(mensaje)

# Bloque de registro histórico diario en la barra lateral
archivo_historico = "historial_entrenamiento.csv"

if st.sidebar.button("Guardar Registro Matutino"):
    nuevo_registro = pd.DataFrame(
        [{
            "Fecha": pd.Timestamp.now().strftime("%Y-%m-%d"),
            "VFC": vfc_hoy,
            "RHR": rhr_hoy,
            "Sueño": sueno_hoy,
            "Estado": estado,
            "Prescripción": prescripcion,
        }]
    )

    if os.path.exists(archivo_historico):
        nuevo_registro.to_csv(
            archivo_historico, mode="a", header=False, index=False
        )
    else:
        nuevo_registro.to_csv(
            archivo_historico, mode="w", header=True, index=False
        )

    st.sidebar.success("¡Registro guardado con éxito en el historial!")

# Módulo de tendencias e historial visual
if os.path.exists(archivo_historico):
    st.markdown("---")
    st.markdown("### 📈 Tendencias y Evolución Fisiológica")

    df_hist = pd.read_csv(archivo_historico)

    if not df_hist.empty and len(df_hist) > 0:
        tab1, tab2 = st.tabs(["VFC & Reposo", "Historial de Registros"])

        with tab1:
            st.markdown("**Evolución VFC Nocturna y FC en Reposo**")
            st.line_chart(df_hist.set_index("Fecha")[["VFC", "RHR"]])

        with tab2:
            st.markdown("**Registro Completo de Check-ins**")
            st.dataframe(df_hist, use_container_width=True)
    else:
        st.info("Guarda registros diarios para habilitar los gráficos.")

fechas = [item.get("id") for item in historico_data]
    ctl = [item.get("ctl", 0) or 0 for item in historico_data]
    atl = [item.get("atl", 0) or 0 for item in historico_data]
    tsb = [item.get("tsb", 0) or 0 for item in historico_data]

    fig = go.Figure()

    # Curva de Fitness (CTL)
    fig.add_trace(go.Scatter(x=fechas, y=ctl, mode='lines',
                  name='Fitness (CTL)', line=dict(color='blue', width=2)))
    # Curva de Fatiga (ATL)
    fig.add_trace(go.Scatter(x=fechas, y=atl, mode='lines',
                  name='Fatiga (ATL)', line=dict(color='orange', width=2)))
    # Curva de Estado de Forma (TSB)
    fig.add_trace(go.Scatter(x=fechas, y=tsb, mode='lines',
                  name='Forma (TSB)', line=dict(color='green', width=2)))

    fig.update_layout(
        title="Evolución de Carga de Entrenamiento (30 Días)",
        xaxis_title="Fecha",
        yaxis_title="Valor",
        template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom",
                    y=1.02, xanchor="right", x=1)
    )

    st.plotly_chart(fig, use_container_width=True)

        
