import streamlit as st
import pdfplumber
import pandas as pd
import re
import io
import traceback
from pathlib import Path
from PIL import Image
from datetime import datetime


# ============================================================================
# RUTAS E ICONO
# ============================================================================
BASE_DIR = Path(__file__).resolve().parent
DIR_DISENO = BASE_DIR / "diseño"
ICONO_FILE = DIR_DISENO / "ada-icono (1).png"
HEADER_MAIN_FILE = DIR_DISENO / "ADA-vc-color (1).jpg"

# Session state
if 'archivos_procesados' not in st.session_state:
    st.session_state.archivos_procesados = None
if 'comparacion_ejecutada' not in st.session_state:
    st.session_state.comparacion_ejecutada = False
if 'dataframes_procesados' not in st.session_state:
    st.session_state.dataframes_procesados = None
if 'info_archivos' not in st.session_state:
    st.session_state.info_archivos = None

try:
    icono_pestana = Image.open(ICONO_FILE)
except Exception:
    icono_pestana = "📂"

st.set_page_config(
    page_title="RPT - Gestor de Puestos",
    page_icon=icono_pestana,
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ============================================================================
# CSS
# ============================================================================
st.markdown("""
    <style>
    :root {
        --verde-junta: #0b6e3c;
        --verde-hover: #158f4a;
        --blanco: #ffffff;
        --texto-oscuro: #1f2937;
    }
    .stApp { background-color: var(--blanco); color: var(--texto-oscuro); }
    header[data-testid="stHeader"] {
        background-color: var(--blanco);
        border-bottom: 4px solid var(--verde-junta);
        padding: 0.5rem;
    }
    header::after { display: none !important; }
    header img { max-height: 60px !important; object-fit: contain; }
    section[data-testid="stSidebar"] {
        background-color: var(--verde-junta);
        padding-top: 1rem;
    }
    section[data-testid="stSidebar"] * {
        color: #ffffff !important;
        font-size: 15px;
    }
    [data-testid="collapsedControl"] {
        background-color: var(--blanco) !important;
        border-radius: 4px;
    }
    [data-testid="collapsedControl"] svg { fill: var(--verde-junta) !important; }
    .main { padding: 2rem; }
    .stButton > button {
        background-color: var(--verde-junta);
        color: var(--blanco);
        border-radius: 6px;
        border: none;
        padding: 0.5rem 1rem;
        font-weight: 600;
        width: 100%;
    }
    .stButton > button:hover { background-color: var(--verde-hover); }
    input, textarea { border-radius: 6px !important; }
    footer { visibility: hidden; }
    </style>
""", unsafe_allow_html=True)

# --- Banner ---
try:
    if HEADER_MAIN_FILE.exists():
        st.image(str(HEADER_MAIN_FILE), use_container_width=True)
except Exception:
    pass

# ============================================================================
# FUNCIONES DE EXTRACCIÓN
# ============================================================================

def es_linea_plaza(linea):
    if ',' in linea and re.search(r'\d{8}[A-Z]\d+[A-Z].*,', linea): return False
    if re.match(r'^\s*\d?\s*\d{6,8}[A-ZÁÉÍÓÚÑ]', linea):
        if not re.match(r'^\s*\d{6,8}[A-Z]\d+[A-Z]+\d+', linea): return True
    return False

def es_linea_persona(linea):
    if re.match(r'^\s*\d{8}[A-Z]\d+[A-Z]+\d+[A-ZÁÉÍÓÚÑ\s]+,\s*[A-ZÁÉÍÓÚÑ]', linea): return True
    if re.match(r'^\s*\d{8}[A-Z]\d+L\d+[A-ZÁÉÍÓÚÑ\s]+,\s*[A-ZÁÉÍÓÚÑ]', linea): return True
    return False

def extraer_codigo_puesto(linea):
    match = re.search(r'(\d{6,8})', linea)
    return match.group(1) if match else None

def extraer_denominacion(linea):
    match_codigo = re.search(r'\d{6,8}', linea)
    if not match_codigo: return None
    resto = linea[match_codigo.end():]
    match = re.match(r'\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s\.\/\(\)ºª\-]+?)(?:\.{2,}|\s+[A-E]\d|\s+\d+\s+\d+)', resto)
    if match:
        denom = re.sub(r'\.+$', '', match.group(1).strip()).strip()
        return denom if len(denom) > 2 else None
    return None

def extraer_grupo(linea):
    match = re.search(r'\s+([A-E]\d(?:-[A-E]\d)?)\s+P-[A-E]\d', linea)
    if match: return match.group(1)
    match = re.search(r'\s+([A-E]\d(?:-[A-E]\d)?)P-[A-E]\d', linea)
    if match: return match.group(1)
    match = re.search(r'\s+([IVX]+)\s+[A-Z]', linea)
    if match: return match.group(1)
    return None

def extraer_cuerpo(linea):
    match = re.search(r'(P-[A-E]\d+)[\s\w]', linea)
    if match: return match.group(1)
    match = re.search(r'[IVX]+\s+([A-ZÁÉÍÓÚÑ\s\.]+?)\s+\d{2}\s+', linea)
    if match:
        c = ' '.join(match.group(1).strip().split())
        return c if len(c) > 3 else None
    return None

def extraer_nombre_persona(linea):
    match = re.search(r'\d{8}[A-Z]\d+[A-Z]+\d+([A-ZÁÉÍÓÚÑ\s,\.]+?)(?:\s+[A-E]\d|\s+FUNC\.|LABORAL|[A-E]\d+\s)', linea)
    if match:
        nombre = ' '.join(match.group(1).strip().split())
        if len(nombre) > 5 and ',' in nombre: return nombre
    return None

def extraer_formacion(linea):
    """Extrae DEFINITIVO o PROVISIONAL de la línea de persona."""
    if 'PROVISIONAL' in linea.upper():
        return 'PROVISIONAL'
    elif 'DEFINITIVO' in linea.upper():
        return 'DEFINITIVO'
    return None

def extraer_dni(linea):
    """Extrae el DNI/NIE del funcionario (formato: 12345678A al inicio del código)."""
    match = re.search(r'(\d{8}[A-Z])', linea)
    return match.group(1) if match else None

def extraer_provincia(linea, lineas_adyacentes):
    patron = r'\b(ALMER[IÍ]A|C[AÁ]DIZ|C[OÓ]RDOBA|GRANADA|HUELVA|JA[EÉ]N|M[AÁ]LAGA|SEVILLA|MADRID|SS\.?CC\.?|SERVICIOS CENTRALES)\b'
    for texto in [linea] + lineas_adyacentes:
        match = re.search(patron, texto, re.IGNORECASE)
        if match: return match.group(1).upper().replace('SSCC', 'SS.CC.')
    return "NO ESPECIFICADA"

def extraer_dotacion(linea):
    if "NO DOTADA" in linea.upper(): return "NO DOTADA"
    match = re.search(r'\.+\s+(\d+)\s+(\d+)\s', linea)
    if match: return "NO DOTADA" if match.group(2) == '0' else "DOTADA"
    partes = linea.split()
    if len(partes) > 2 and (partes[-1] == 'N' or partes[-2] == 'N'): return "NO DOTADA"
    return "DOTADA"


def extraer_fecha_pdf(archivo_bytes, nombre_archivo):
    try:
        with pdfplumber.open(io.BytesIO(archivo_bytes)) as pdf:
            if pdf.pages:
                texto = pdf.pages[0].extract_text()
                if texto:
                    for linea in texto.split('\n')[:10]:
                        if 'Fecha' in linea or 'fecha' in linea:
                            match = re.search(r'(\d{2}/\d{2}/\d{4})', linea)
                            if match:
                                fecha = match.group(1)
                                return fecha
    except Exception:
        pass
    return None


def procesar_pdf(archivo_bytes, nombre_archivo):
    registros = []

    try:
        buffer = io.BytesIO(archivo_bytes)
        with pdfplumber.open(buffer) as pdf:
            num_paginas = len(pdf.pages)

            todas_lineas = []
            paginas_sin_texto = []

            with st.spinner(f'📄 Procesando {nombre_archivo} ({num_paginas} páginas)...'):
                for num_pag, pagina in enumerate(pdf.pages, 1):
                    try:
                        texto = pagina.extract_text()
                        if texto:
                            lineas = texto.split('\n')
                            todas_lineas.extend(lineas)
                        else:
                            paginas_sin_texto.append(num_pag)
                    except Exception as e:
                        tb = traceback.format_exc()

                if paginas_sin_texto:
                    st.warning(f"⚠️ {len(paginas_sin_texto)} páginas sin texto en {nombre_archivo} (págs: {paginas_sin_texto[:10]})")

                st.info(f"✅ {nombre_archivo}: {len(todas_lineas):,} líneas extraídas de {num_paginas} páginas")

            # Parsear líneas
            plazas_detectadas = 0
            plazas_sin_codigo = 0

            i = 0
            while i < len(todas_lineas):
                linea = todas_lineas[i]
                if es_linea_plaza(linea):
                    codigo = extraer_codigo_puesto(linea)
                    if not codigo:
                        plazas_sin_codigo += 1
                        i += 1
                        continue

                    plazas_detectadas += 1
                    nombre_ocupante = None
                    dni_ocupante = None
                    formacion_ocupante = None
                    lineas_adyacentes = []

                    for j in range(1, 6):
                        if (i + j) < len(todas_lineas):
                            sig = todas_lineas[i + j]
                            lineas_adyacentes.append(sig)
                            if es_linea_persona(sig):
                                nombre_ocupante = extraer_nombre_persona(sig)
                                dni_ocupante = extraer_dni(sig)
                                formacion_ocupante = extraer_formacion(sig)
                                if not nombre_ocupante:
                                    pass
                                break
                            if es_linea_plaza(sig): break

                    registros.append({
                        'Código':       codigo,
                        'Denominación': extraer_denominacion(linea),
                        'Grupo':        extraer_grupo(linea),
                        'Cuerpo':       extraer_cuerpo(linea),
                        'Provincia':    extraer_provincia(linea, lineas_adyacentes),
                        'Dotación':     extraer_dotacion(linea),
                        'Ocupante':     nombre_ocupante if nombre_ocupante else 'VACANTE',
                        'Estado_Plaza': 'OCUPADA' if nombre_ocupante else 'LIBRE',
                        'DNI':          dni_ocupante,  # campo interno
                        'Formacion':    formacion_ocupante  # campo interno
                    })
                i += 1


        df_resultado = pd.DataFrame(registros)

        if df_resultado.empty:
            st.error(f"❌ {nombre_archivo}: no se extrajeron plazas.")
            return pd.DataFrame()

        # ─────────────────────────────────────────────────────────────────────────
        # PERSONAS CON PLAZA PROVISIONAL Y DEFINITIVA SIMULTÁNEA
        # → Plaza PROVISIONAL: OCUPADA con el nombre del funcionario
        # → Plaza DEFINITIVO:  LIBRE (el funcionario está en la provisional)
        #                        pero se conserva el nombre entre paréntesis
        #                        para saber quién la tenía asignada.
        # ─────────────────────────────────────────────────────────────────────────
        df_ocupadas = df_resultado[df_resultado['Estado_Plaza'] == 'OCUPADA'].copy()

        if not df_ocupadas.empty and 'DNI' in df_ocupadas.columns:
            df_ocupadas['_clave_persona'] = df_ocupadas['DNI'].fillna('') + '|' + df_ocupadas['Ocupante']
            duplicados = df_ocupadas[df_ocupadas.duplicated(subset=['_clave_persona'], keep=False)]

            if not duplicados.empty:
                personas_duplicadas = duplicados['_clave_persona'].unique()
                codigos_liberados = []

                for persona in personas_duplicadas:
                    if '|' not in persona or persona.startswith('|'):
                        continue

                    registros_persona = df_ocupadas[df_ocupadas['_clave_persona'] == persona]

                    # Solo actuar si tiene al menos una plaza PROVISIONAL
                    if 'PROVISIONAL' in registros_persona['Formacion'].values:
                        definitivos = registros_persona[registros_persona['Formacion'] == 'DEFINITIVO']
                        nombre_func = persona.split('|', 1)[1]

                        for codigo in definitivos['Código'].tolist():
                            # Marcar como LIBRE (el funcionario está en su provisional)
                            df_resultado.loc[df_resultado['Código'] == codigo, 'Estado_Plaza'] = 'LIBRE'
                            # Conservar el nombre entre paréntesis como referencia
                            df_resultado.loc[df_resultado['Código'] == codigo, 'Ocupante'] = f'({nombre_func})'
                            codigos_liberados.append(codigo)

                if codigos_liberados:
                    st.info(f"ℹ️ {nombre_archivo}: {len(codigos_liberados)} plaza(s) DEFINITIVA(S) marcadas como LIBRE porque el ocupante está en plaza PROVISIONAL. El nombre aparece entre paréntesis como referencia.")
        
        antes = len(df_resultado)
        df_resultado = df_resultado.drop_duplicates(subset=['Código'])

        st.success(f"✅ {nombre_archivo}: {len(df_resultado):,} plazas únicas procesadas")
        return df_resultado

    except Exception as e:
        tb = traceback.format_exc()
        st.error(f"❌ Error procesando {nombre_archivo}: {e}")
        with st.expander("🔍 Ver detalles técnicos"):
            st.code(tb)
        return pd.DataFrame()


def ordenar_archivos_por_fecha(archivos_lista):
    archivos_con_fecha = []
    for nombre, archivo_bytes in archivos_lista:
        fecha_str = extraer_fecha_pdf(archivo_bytes, nombre)
        if fecha_str:
            try:
                fecha_obj = datetime.strptime(fecha_str, '%d/%m/%Y')
                archivos_con_fecha.append((nombre, archivo_bytes, fecha_obj, fecha_str))
            except ValueError:
                archivos_con_fecha.append((nombre, archivo_bytes, datetime.min, fecha_str))
        else:
            archivos_con_fecha.append((nombre, archivo_bytes, datetime.min, "Sin fecha"))

    archivos_con_fecha.sort(key=lambda x: x[2])
    orden = [(n, b, f) for n, b, _, f in archivos_con_fecha]
    return orden


# ============================================================================
# PANTALLA DE CARGA
# ============================================================================
if not st.session_state.comparacion_ejecutada:

    st.markdown("""
        <div style="text-align:center; margin: 2rem 0">
            <div style="font-size:2.5rem; font-weight:700; color:#1f2937">👥 Comparador Múltiple de Efectivos</div>
            <div style="font-size:1.1rem; color:#6b7280; margin-top:0.5rem">Compara todos los PDFs que subas simultáneamente</div>
            <div style="font-size:0.95rem; color:#6b7280; font-weight:500">Sube 2 o más archivos · Incluye Nombres, Grupo y Cuerpo</div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📁 Cargar Archivos PDF")
    st.info("💡 **Tip:** Los archivos se ordenarán automáticamente por fecha para mostrar la evolución cronológica")

    archivos_subidos = st.file_uploader(
        "Arrastra aquí tus archivos PDF (puedes seleccionar varios a la vez)",
        type=['pdf'],
        accept_multiple_files=True,
        key='uploader_multi',
        label_visibility="collapsed"
    )

    if archivos_subidos and len(archivos_subidos) >= 2:
        st.success(f"✅ **{len(archivos_subidos)} archivos cargados**")
        st.markdown("### 📋 Archivos que se compararán:")
        for i, archivo in enumerate(archivos_subidos, 1):
            st.markdown(f"{i}. 📄 **{archivo.name}** ({archivo.size / 1024:.1f} KB)")
        st.markdown("---")

        col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1])
        with col_btn2:
            if st.button("🔍 Comparar Todos los Archivos", type="primary", use_container_width=True):

                # Lista de tuplas (nombre_unico, bytes) para soportar nombres duplicados
                archivos_lista = []
                errores_lectura = []
                nombres_vistos = {}

                for archivo in archivos_subidos:
                    try:
                        contenido_bytes = archivo.read()
                        if len(contenido_bytes) == 0:
                            errores_lectura.append(f"Archivo vacío: {archivo.name}")
                        else:
                            # Si el nombre ya existe, añadir sufijo _2, _3, etc.
                            nombre_base = archivo.name
                            if nombre_base in nombres_vistos:
                                nombres_vistos[nombre_base] += 1
                                ext_idx = nombre_base.rfind('.')
                                if ext_idx > 0:
                                    nombre_unico = nombre_base[:ext_idx] + f"_{nombres_vistos[nombre_base]}" + nombre_base[ext_idx:]
                                else:
                                    nombre_unico = nombre_base + f"_{nombres_vistos[nombre_base]}"
                            else:
                                nombres_vistos[nombre_base] = 1
                                nombre_unico = nombre_base
                            archivos_lista.append((nombre_unico, contenido_bytes))
                    except Exception as e:
                        errores_lectura.append(f"Error leyendo {archivo.name}: {e}")

                for err in errores_lectura:
                    st.warning(err)

                if len(archivos_lista) >= 2:
                    st.session_state.archivos_procesados = archivos_lista
                    st.session_state.comparacion_ejecutada = True
                    st.rerun()
                else:
                    st.error(f"❌ Solo {len(archivos_lista)} archivo(s) válido(s). Se necesitan al menos 2.")

    elif archivos_subidos and len(archivos_subidos) == 1:
        st.warning("⚠️ Necesitas subir al menos 2 archivos para hacer una comparación")
    else:
        st.info("👆 Carga 2 o más archivos PDF para comenzar")


# ============================================================================
# PANTALLA DE RESULTADOS
# ============================================================================
if st.session_state.comparacion_ejecutada and st.session_state.archivos_procesados:

    st.title("RPT: Comparación Múltiple de Archivos")
    st.markdown("---")

    if st.session_state.dataframes_procesados is None:

        with st.spinner('🔄 Procesando y ordenando archivos cronológicamente...'):
            archivos_ordenados = ordenar_archivos_por_fecha(st.session_state.archivos_procesados)
            dataframes_procesados = []
            info_archivos = []

            st.markdown("### 📊 Progreso de Procesamiento")

            for i, (nombre, archivo_bytes, fecha) in enumerate(archivos_ordenados):
                st.markdown(f"**Procesando archivo {i+1}/{len(archivos_ordenados)}:** {nombre}")

                df = procesar_pdf(archivo_bytes, nombre)

                if not df.empty:
                    dataframes_procesados.append(df)
                    info_archivos.append({
                        'nombre':       nombre,
                        'fecha':        fecha,
                        'total_plazas': len(df),
                        'dotadas':      len(df[df['Dotación'] == 'DOTADA']),
                        'no_dotadas':   len(df[df['Dotación'] == 'NO DOTADA']),
                        'ocupadas':     len(df[df['Estado_Plaza'] == 'OCUPADA']),
                        'libres':       len(df[df['Estado_Plaza'] == 'LIBRE'])
                    })
                else:
                    st.error(f"⚠️ No se pudieron extraer datos de {nombre}")

            st.markdown("---")

        st.session_state.dataframes_procesados = dataframes_procesados
        st.session_state.info_archivos = info_archivos

    else:
        dataframes_procesados = st.session_state.dataframes_procesados
        info_archivos = st.session_state.info_archivos

    if len(dataframes_procesados) >= 2:

        # Resumen general
        st.markdown("### 📊 Resumen General")
        total_plazas_base  = len(dataframes_procesados[0])
        total_plazas_final = len(dataframes_procesados[-1])
        diferencia = total_plazas_final - total_plazas_base

        col1, col2, col3 = st.columns(3)
        col1.metric("Plazas Iniciales",   total_plazas_base,  help=f"Archivo: {info_archivos[0]['nombre']}")
        col2.metric("Plazas Finales",     total_plazas_final, delta=diferencia, help=f"Archivo: {info_archivos[-1]['nombre']}")
        col3.metric("Total de Versiones", len(dataframes_procesados))
        st.markdown("---")

        # Comparaciones entre versiones
        st.markdown("## 🔀 Comparaciones Detalladas Entre Versiones")

        nombres_comparaciones = []
        for i in range(len(info_archivos) - 1):
            n1 = info_archivos[i]['nombre'][:15] + ("..." if len(info_archivos[i]['nombre']) > 15 else "")
            n2 = info_archivos[i+1]['nombre'][:15] + ("..." if len(info_archivos[i+1]['nombre']) > 15 else "")
            nombres_comparaciones.append(f"{n1} → {n2}")

        tabs_comparacion = st.tabs(nombres_comparaciones)

        for idx, tab in enumerate(tabs_comparacion):
            with tab:
                df_old = dataframes_procesados[idx]
                df_new = dataframes_procesados[idx + 1]

                col_comp1, col_comp2 = st.columns(2)
                with col_comp1:
                    st.info(f"**📋 Versión Anterior**\n\n{info_archivos[idx]['nombre']}\n\n📅 {info_archivos[idx]['fecha']}")
                with col_comp2:
                    st.success(f"**📋 Versión Nueva**\n\n{info_archivos[idx+1]['nombre']}\n\n📅 {info_archivos[idx+1]['fecha']}")

                df_comp = pd.merge(df_old, df_new, on='Código', how='outer', suffixes=('_ANT','_ACT'), indicator=True)

                def det_estado_comp(row):
                    if row['_merge'] == 'left_only':  return '❌ ELIMINADA'
                    if row['_merge'] == 'right_only': return '🆕 NUEVA'
                    dot_ant = str(row.get('Dotación_ANT', ''))
                    dot_act = str(row.get('Dotación_ACT', ''))
                    ocu_ant = str(row.get('Ocupante_ANT', ''))
                    ocu_act = str(row.get('Ocupante_ACT', ''))
                    cambio_dot = dot_ant != dot_act and dot_ant != 'nan' and dot_act != 'nan'
                    cambio_ocu = ocu_ant != ocu_act
                    if cambio_dot and cambio_ocu: return '🔄 CAMBIO OCUPANTE + DOTACIÓN'
                    if cambio_dot:  return '💰 CAMBIO DOTACIÓN'
                    if cambio_ocu:  return '🔄 CAMBIO OCUPANTE'
                    return '✅ SIN CAMBIOS'

                df_comp['Situación']          = df_comp.apply(det_estado_comp, axis=1)
                df_comp['Denominación']       = df_comp['Denominación_ACT'].fillna(df_comp['Denominación_ANT'])
                df_comp['Grupo']              = df_comp['Grupo_ACT'].fillna(df_comp['Grupo_ANT'])
                df_comp['Cuerpo']             = df_comp['Cuerpo_ACT'].fillna(df_comp['Cuerpo_ANT'])
                df_comp['Provincia']          = df_comp['Provincia_ACT'].fillna(df_comp['Provincia_ANT'])
                df_comp['Ocupante Anterior']  = df_comp['Ocupante_ANT'].fillna('-')
                df_comp['Ocupante Actual']    = df_comp['Ocupante_ACT'].fillna('-')
                df_comp['Dotación Anterior']  = df_comp['Dotación_ANT'].fillna('-')
                df_comp['Dotación Actual']    = df_comp['Dotación_ACT'].fillna('-')
                df_comp['Dotación'] = df_comp['Dotación_ACT'].fillna(df_comp['Dotación_ANT'])
                df_comp['Estado']   = df_comp['Estado_Plaza_ACT'].fillna(df_comp['Estado_Plaza_ANT'])

                nuevas        = len(df_comp[df_comp['Situación'] == '🆕 NUEVA'])
                eliminadas    = len(df_comp[df_comp['Situación'] == '❌ ELIMINADA'])
                cambios_ocu   = len(df_comp[df_comp['Situación'] == '🔄 CAMBIO OCUPANTE'])
                cambios_dot   = len(df_comp[df_comp['Situación'] == '💰 CAMBIO DOTACIÓN'])
                cambios_ambos = len(df_comp[df_comp['Situación'] == '🔄 CAMBIO OCUPANTE + DOTACIÓN'])

                col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
                col_m1.metric("🆕 Nuevas",         nuevas,        delta=f"+{nuevas}")
                col_m2.metric("❌ Eliminadas",      eliminadas,    delta=f"-{eliminadas}")
                col_m3.metric("🔄 Cambio Ocupante", cambios_ocu)
                col_m4.metric("💰 Cambio Dotación", cambios_dot)
                col_m5.metric("🔄+💰 Ambos",        cambios_ambos)
                st.markdown("---")

                # ── Filtros de la comparación ─────────────────────────────
                st.markdown("#### 🔎 Filtros")
                cf1, cf2, cf3, cf4 = st.columns(4)

                with cf1:
                    opciones_prov = sorted(df_comp['Provincia'].dropna().unique())
                    comp_filtro_prov = st.multiselect(
                        "Provincia",
                        options=opciones_prov,
                        key=f"comp_prov_{idx}"
                    )
                with cf2:
                    opciones_grupo = sorted([g for g in df_comp['Grupo'].dropna().unique()])
                    comp_filtro_grupo = st.multiselect(
                        "Grupo",
                        options=opciones_grupo,
                        key=f"comp_grupo_{idx}"
                    )
                with cf3:
                    comp_filtro_dot = st.multiselect(
                        "Dotación",
                        options=sorted(df_comp['Dotación'].dropna().unique()),
                        key=f"comp_dot_{idx}"
                    )
                with cf4:
                    comp_filtro_estado = st.multiselect(
                        "Estado Plaza",
                        options=sorted(df_comp['Estado'].dropna().unique()),
                        key=f"comp_estado_{idx}"
                    )

                # Aplicar filtros al df_comp
                df_comp_filtrado = df_comp.copy()
                if comp_filtro_prov:
                    df_comp_filtrado = df_comp_filtrado[df_comp_filtrado['Provincia'].isin(comp_filtro_prov)]
                if comp_filtro_grupo:
                    df_comp_filtrado = df_comp_filtrado[df_comp_filtrado['Grupo'].isin(comp_filtro_grupo)]
                if comp_filtro_dot:
                    df_comp_filtrado = df_comp_filtrado[df_comp_filtrado['Dotación'].isin(comp_filtro_dot)]
                if comp_filtro_estado:
                    df_comp_filtrado = df_comp_filtrado[df_comp_filtrado['Estado'].isin(comp_filtro_estado)]

                # Recalcular métricas con filtro aplicado
                nuevas_f      = len(df_comp_filtrado[df_comp_filtrado['Situación'] == '🆕 NUEVA'])
                eliminadas_f  = len(df_comp_filtrado[df_comp_filtrado['Situación'] == '❌ ELIMINADA'])
                cambios_ocu_f = len(df_comp_filtrado[df_comp_filtrado['Situación'] == '🔄 CAMBIO OCUPANTE'])
                cambios_dot_f = len(df_comp_filtrado[df_comp_filtrado['Situación'] == '💰 CAMBIO DOTACIÓN'])
                cambios_amb_f = len(df_comp_filtrado[df_comp_filtrado['Situación'] == '🔄 CAMBIO OCUPANTE + DOTACIÓN'])

                if any([comp_filtro_prov, comp_filtro_grupo, comp_filtro_dot, comp_filtro_estado]):
                    st.caption(f"🔎 Filtro activo — mostrando {len(df_comp_filtrado)} de {len(df_comp)} plazas "
                               f"| +{nuevas_f} nuevas | -{eliminadas_f} eliminadas "
                               f"| {cambios_ocu_f} cambio ocupante | {cambios_dot_f} cambio dotación "
                               f"| {cambios_amb_f} ambos")

                st.markdown("---")

                # ── Nombre corto para las pestañas de los PDFs ───────────────
                nombre_ant_corto = info_archivos[idx]['nombre']
                nombre_act_corto = info_archivos[idx+1]['nombre']
                # Recortar si es muy largo para que quepan bien en la tab
                MAX_TAB = 20
                tab_ant = (f"📄 {nombre_ant_corto[:MAX_TAB]}..." if len(nombre_ant_corto) > MAX_TAB else f"📄 {nombre_ant_corto}")
                tab_act = (f"📄 {nombre_act_corto[:MAX_TAB]}..." if len(nombre_act_corto) > MAX_TAB else f"📄 {nombre_act_corto}")

                # ── 6 pestañas unificadas ─────────────────────────────────────
                # Las 4 de comparación + las 2 tablas individuales de cada PDF
                (
                    sub_tab_todos,
                    sub_tab_nuevas,
                    sub_tab_eliminadas,
                    sub_tab_cambios,
                    sub_tab_dot,
                    sub_tab_ambos,
                    sub_tab_pdf_ant,
                    sub_tab_pdf_act,
                ) = st.tabs([
                    "🔍 TODOS",
                    "🆕 Nuevas",
                    "❌ Eliminadas",
                    "🔄 Cambio Ocupante",
                    "💰 Cambio Dotación",
                    "🔄+💰 Ambos",
                    tab_ant,
                    tab_act,
                ])

                cols_mostrar = [
                    'Código', 'Denominación', 'Grupo', 'Cuerpo', 'Provincia', 'Situación',
                    'Dotación Anterior', 'Dotación Actual', 'Estado',
                    'Ocupante Anterior', 'Ocupante Actual'
                ]

                def color_rows(val):
                    if val == '❌ ELIMINADA':                      return 'background-color: #ffebee'
                    elif val == '🆕 NUEVA':                        return 'background-color: #e8f5e9'
                    elif val == '🔄 CAMBIO OCUPANTE':              return 'background-color: #fffde7'
                    elif val == '💰 CAMBIO DOTACIÓN':              return 'background-color: #e3f2fd'
                    elif val == '🔄 CAMBIO OCUPANTE + DOTACIÓN':   return 'background-color: #f3e5f5'
                    elif val == '✅ SIN CAMBIOS':                  return 'background-color: #f1f8f4'
                    return 'background-color: white'

                with sub_tab_todos:
                    st.dataframe(
                        df_comp_filtrado[cols_mostrar].style.map(color_rows, subset=['Situación']),
                        use_container_width=True, height=500
                    )
                    st.caption(f"Total: {len(df_comp_filtrado)} plazas")

                with sub_tab_nuevas:
                    df_n = df_comp_filtrado[df_comp_filtrado['Situación'] == '🆕 NUEVA']
                    st.dataframe(df_n[cols_mostrar], use_container_width=True, height=500)
                    st.caption(f"Total: {len(df_n)} plazas nuevas")

                with sub_tab_eliminadas:
                    df_e = df_comp_filtrado[df_comp_filtrado['Situación'] == '❌ ELIMINADA']
                    st.dataframe(df_e[cols_mostrar], use_container_width=True, height=500)
                    st.caption(f"Total: {len(df_e)} plazas eliminadas")

                with sub_tab_cambios:
                    df_c = df_comp_filtrado[df_comp_filtrado['Situación'] == '🔄 CAMBIO OCUPANTE']
                    st.dataframe(df_c[cols_mostrar], use_container_width=True, height=500)
                    st.caption(f"Total: {len(df_c)} plazas con cambio de ocupante")

                with sub_tab_dot:
                    df_d = df_comp_filtrado[df_comp_filtrado['Situación'] == '💰 CAMBIO DOTACIÓN']
                    st.dataframe(df_d[cols_mostrar], use_container_width=True, height=500)
                    st.caption(f"Total: {len(df_d)} plazas con cambio de dotación")

                with sub_tab_ambos:
                    df_ab = df_comp_filtrado[df_comp_filtrado['Situación'] == '🔄 CAMBIO OCUPANTE + DOTACIÓN']
                    st.dataframe(df_ab[cols_mostrar], use_container_width=True, height=500)
                    st.caption(f"Total: {len(df_ab)} plazas con cambio de ocupante y dotación")

                # ── Tab PDF ANTERIOR (tabla individual) ───────────────────────
                with sub_tab_pdf_ant:
                    st.markdown(f"#### {info_archivos[idx]['nombre']}")
                    st.caption(f"📅 Fecha: {info_archivos[idx]['fecha']}")

                    col_a, col_b, col_c, col_d = st.columns(4)
                    col_a.metric("Total Plazas", info_archivos[idx]['total_plazas'])
                    col_b.metric("Ocupadas",     info_archivos[idx]['ocupadas'])
                    col_c.metric("Libres",       info_archivos[idx]['libres'])
                    col_d.metric("Dotadas",      info_archivos[idx]['dotadas'])

                    st.markdown("---")

                    cf1, cf2, cf3, cf4 = st.columns(4)
                    with cf1:
                        f_prov = st.multiselect("Provincia", options=sorted(df_old['Provincia'].unique()), key=f"pdf1_prov_{idx}")
                    with cf2:
                        f_grupo = st.multiselect("Grupo", options=sorted([g for g in df_old['Grupo'].unique() if pd.notna(g)]), key=f"pdf1_grupo_{idx}")
                    with cf3:
                        f_dot = st.multiselect("Dotación", options=df_old['Dotación'].unique(), key=f"pdf1_dot_{idx}")
                    with cf4:
                        f_est = st.multiselect("Estado", options=df_old['Estado_Plaza'].unique(), key=f"pdf1_est_{idx}")

                    df_f = df_old.copy()
                    if f_prov:  df_f = df_f[df_f['Provincia'].isin(f_prov)]
                    if f_grupo: df_f = df_f[df_f['Grupo'].isin(f_grupo)]
                    if f_dot:   df_f = df_f[df_f['Dotación'].isin(f_dot)]
                    if f_est:   df_f = df_f[df_f['Estado_Plaza'].isin(f_est)]

                    st.dataframe(
                        df_f[['Código','Denominación','Grupo','Cuerpo','Provincia','Dotación','Estado_Plaza','Ocupante']],
                        use_container_width=True, height=500
                    )
                    st.caption(f"Mostrando {len(df_f)} de {len(df_old)} plazas")

                # ── Tab PDF ACTUAL (tabla individual) ─────────────────────────
                with sub_tab_pdf_act:
                    st.markdown(f"#### {info_archivos[idx+1]['nombre']}")
                    st.caption(f"📅 Fecha: {info_archivos[idx+1]['fecha']}")

                    col_a, col_b, col_c, col_d = st.columns(4)
                    col_a.metric("Total Plazas", info_archivos[idx+1]['total_plazas'])
                    col_b.metric("Ocupadas",     info_archivos[idx+1]['ocupadas'])
                    col_c.metric("Libres",       info_archivos[idx+1]['libres'])
                    col_d.metric("Dotadas",      info_archivos[idx+1]['dotadas'])

                    st.markdown("---")

                    cf1, cf2, cf3, cf4 = st.columns(4)
                    with cf1:
                        f_prov = st.multiselect("Provincia", options=sorted(df_new['Provincia'].unique()), key=f"pdf2_prov_{idx}")
                    with cf2:
                        f_grupo = st.multiselect("Grupo", options=sorted([g for g in df_new['Grupo'].unique() if pd.notna(g)]), key=f"pdf2_grupo_{idx}")
                    with cf3:
                        f_dot = st.multiselect("Dotación", options=df_new['Dotación'].unique(), key=f"pdf2_dot_{idx}")
                    with cf4:
                        f_est = st.multiselect("Estado", options=df_new['Estado_Plaza'].unique(), key=f"pdf2_est_{idx}")

                    df_f = df_new.copy()
                    if f_prov:  df_f = df_f[df_f['Provincia'].isin(f_prov)]
                    if f_grupo: df_f = df_f[df_f['Grupo'].isin(f_grupo)]
                    if f_dot:   df_f = df_f[df_f['Dotación'].isin(f_dot)]
                    if f_est:   df_f = df_f[df_f['Estado_Plaza'].isin(f_est)]

                    st.dataframe(
                        df_f[['Código','Denominación','Grupo','Cuerpo','Provincia','Dotación','Estado_Plaza','Ocupante']],
                        use_container_width=True, height=500
                    )
                    st.caption(f"Mostrando {len(df_f)} de {len(df_new)} plazas")

        st.markdown("---")
        if st.button("🔄 Cargar Nuevos Archivos", type="secondary"):
            st.session_state.archivos_procesados = None
            st.session_state.comparacion_ejecutada = False
            st.session_state.dataframes_procesados = None
            st.session_state.info_archivos = None
            st.rerun()

    else:
        st.error("⚠️ No se pudieron procesar suficientes archivos para realizar la comparación")
        st.info("💡 Se necesitan al menos 2 archivos válidos. Revisa el 🪵 Panel de Logs en la barra lateral izquierda.")
        if st.button("🔄 Volver a cargar archivos"):
            st.session_state.archivos_procesados = None
            st.session_state.comparacion_ejecutada = False
            st.session_state.dataframes_procesados = None
            st.session_state.info_archivos = None
            st.rerun()
