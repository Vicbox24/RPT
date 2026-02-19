import streamlit as st
import pdfplumber
import pandas as pd
import re
import io
import traceback
import json
from pathlib import Path
from PIL import Image
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.oauth2.service_account import Credentials

# ============================================================================
# RUTAS E ICONO
# ============================================================================
BASE_DIR = Path(__file__).resolve().parent
DIR_DISENO = BASE_DIR / "diseño"
ICONO_FILE = DIR_DISENO / "ada-icono (1).png"
HEADER_MAIN_FILE = DIR_DISENO / "ADA-vc-color (1).jpg"

# ============================================================================
# SESSION STATE
# ============================================================================
for key, val in {
    'archivos_procesados': None,
    'comparacion_ejecutada': False,
    'dataframes_procesados': None,
    'info_archivos': None,
    'revision_activa': None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

try:
    icono_pestana = Image.open(ICONO_FILE)
except Exception:
    icono_pestana = "📂"

st.set_page_config(
    page_title="RPT - Gestor de Puestos",
    page_icon=icono_pestana,
    layout="wide",
    initial_sidebar_state="expanded"
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
        st.image(str(HEADER_MAIN_FILE), width='stretch')
except Exception:
    pass

# ============================================================================
# GOOGLE DRIVE - CONEXIÓN
# ============================================================================
CARPETA_RAIZ_NOMBRE = "RPT_Revisiones"

@st.cache_resource
def conectar_drive():
    """Conecta con Google Drive usando las credenciales de Streamlit Secrets."""
    try:
        creds_dict = st.secrets["google_drive"]
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        service = build("drive", "v3", credentials=creds)
        return service
    except Exception as e:
        st.error(f"❌ Error conectando con Google Drive: {e}")
        return None

def obtener_o_crear_carpeta(service, nombre, parent_id=None):
    """Obtiene una carpeta por nombre o la crea si no existe."""
    query = f"name='{nombre}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    archivos = results.get("files", [])
    if archivos:
        return archivos[0]["id"]
    # Crear carpeta
    metadata = {
        "name": nombre,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]
    carpeta = service.files().create(body=metadata, fields="id").execute()
    return carpeta["id"]

def listar_revisiones(service, carpeta_raiz_id):
    """Lista todas las subcarpetas (revisiones) dentro de la carpeta raíz."""
    query = f"'{carpeta_raiz_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, fields="files(id, name, createdTime)", orderBy="createdTime desc").execute()
    return results.get("files", [])

def listar_pdfs_revision(service, carpeta_id):
    """Lista los PDFs dentro de una carpeta de revisión."""
    query = f"'{carpeta_id}' in parents and mimeType='application/pdf' and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    return results.get("files", [])

def subir_pdf_drive(service, nombre_archivo, bytes_pdf, carpeta_id):
    """Sube un PDF a Google Drive en la carpeta indicada."""
    metadata = {"name": nombre_archivo, "parents": [carpeta_id]}
    media = MediaIoBaseUpload(io.BytesIO(bytes_pdf), mimetype="application/pdf")
    service.files().create(body=metadata, media_body=media, fields="id").execute()

def descargar_pdf_drive(service, file_id):
    """Descarga un PDF de Google Drive y devuelve sus bytes."""
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()

def eliminar_carpeta_drive(service, carpeta_id):
    """Elimina una carpeta y su contenido de Google Drive."""
    service.files().delete(fileId=carpeta_id).execute()

# ============================================================================
# FUNCIONES DE EXTRACCIÓN (igual que antes)
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
    if 'PROVISIONAL' in linea.upper(): return 'PROVISIONAL'
    elif 'DEFINITIVO' in linea.upper(): return 'DEFINITIVO'
    return None

def extraer_dni(linea):
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
                                return match.group(1)
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
                            todas_lineas.extend(texto.split('\n'))
                        else:
                            paginas_sin_texto.append(num_pag)
                    except Exception:
                        pass

                if paginas_sin_texto:
                    st.warning(f"⚠️ {len(paginas_sin_texto)} páginas sin texto en {nombre_archivo}")
                st.info(f"✅ {nombre_archivo}: {len(todas_lineas):,} líneas extraídas de {num_paginas} páginas")

            i = 0
            while i < len(todas_lineas):
                linea = todas_lineas[i]
                if es_linea_plaza(linea):
                    codigo = extraer_codigo_puesto(linea)
                    if not codigo:
                        i += 1
                        continue

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
                        'DNI':          dni_ocupante,
                        'Formacion':    formacion_ocupante
                    })
                i += 1

        df_resultado = pd.DataFrame(registros)
        if df_resultado.empty:
            st.error(f"❌ {nombre_archivo}: no se extrajeron plazas.")
            return pd.DataFrame()

        # Gestión provisional/definitivo
        df_ocupadas = df_resultado[df_resultado['Estado_Plaza'] == 'OCUPADA'].copy()
        if not df_ocupadas.empty and 'DNI' in df_ocupadas.columns:
            df_ocupadas['_clave_persona'] = df_ocupadas['DNI'].fillna('') + '|' + df_ocupadas['Ocupante']
            duplicados = df_ocupadas[df_ocupadas.duplicated(subset=['_clave_persona'], keep=False)]
            if not duplicados.empty:
                for persona in duplicados['_clave_persona'].unique():
                    if '|' not in persona or persona.startswith('|'): continue
                    registros_persona = df_ocupadas[df_ocupadas['_clave_persona'] == persona]
                    if 'PROVISIONAL' in registros_persona['Formacion'].values:
                        definitivos = registros_persona[registros_persona['Formacion'] == 'DEFINITIVO']
                        nombre_func = persona.split('|', 1)[1]
                        for codigo in definitivos['Código'].tolist():
                            df_resultado.loc[df_resultado['Código'] == codigo, 'Estado_Plaza'] = 'LIBRE'
                            df_resultado.loc[df_resultado['Código'] == codigo, 'Ocupante'] = f'({nombre_func})'

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
    return [(n, b, f) for n, b, _, f in archivos_con_fecha]

# ============================================================================
# SIDEBAR - REVISIONES GUARDADAS
# ============================================================================
service = conectar_drive()

with st.sidebar:
    st.markdown("## 📁 Revisiones Guardadas")

    if service:
        carpeta_raiz_id = obtener_o_crear_carpeta(service, CARPETA_RAIZ_NOMBRE)
        revisiones = listar_revisiones(service, carpeta_raiz_id)

        if not revisiones:
            st.info("No hay revisiones guardadas aún.")
        else:
            for rev in revisiones:
                col1, col2 = st.columns([3, 1])
                with col1:
                    if st.button(f"📂 {rev['name']}", key=f"rev_{rev['id']}"):
                        # Cargar PDFs de esta revisión
                        with st.spinner(f"Cargando {rev['name']}..."):
                            pdfs = listar_pdfs_revision(service, rev['id'])
                            if len(pdfs) >= 2:
                                archivos_lista = []
                                for pdf in pdfs:
                                    bytes_pdf = descargar_pdf_drive(service, pdf['id'])
                                    archivos_lista.append((pdf['name'], bytes_pdf))
                                st.session_state.archivos_procesados = archivos_lista
                                st.session_state.comparacion_ejecutada = True
                                st.session_state.dataframes_procesados = None
                                st.session_state.info_archivos = None
                                st.session_state.revision_activa = rev['name']
                                st.rerun()
                            else:
                                st.warning("Esta revisión necesita al menos 2 PDFs.")
                with col2:
                    if st.button("🗑️", key=f"del_{rev['id']}", help="Eliminar revisión"):
                        eliminar_carpeta_drive(service, rev['id'])
                        st.success(f"Revisión '{rev['name']}' eliminada.")
                        st.rerun()

    st.markdown("---")
    if st.button("🔄 Nueva Comparación"):
        st.session_state.archivos_procesados = None
        st.session_state.comparacion_ejecutada = False
        st.session_state.dataframes_procesados = None
        st.session_state.info_archivos = None
        st.session_state.revision_activa = None
        st.rerun()

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

    # NOMBRE DE LA REVISIÓN
    st.markdown("### 📝 Nombre de la Revisión")
    nombre_revision = st.text_input(
        "Ponle un nombre a esta revisión",
        placeholder="Ej: Revisión Marzo-Febrero 2026",
        label_visibility="collapsed"
    )

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
            if st.button("🔍 Comparar y Guardar", type="primary", use_container_width=True):

                if not nombre_revision.strip():
                    st.error("❌ Escribe un nombre para la revisión antes de continuar.")
                    st.stop()

                archivos_lista = []
                nombres_vistos = {}

                for archivo in archivos_subidos:
                    try:
                        contenido_bytes = archivo.read()
                        if len(contenido_bytes) == 0:
                            st.warning(f"Archivo vacío: {archivo.name}")
                            continue
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
                        st.warning(f"Error leyendo {archivo.name}: {e}")

                if len(archivos_lista) >= 2:
                    # Guardar en Google Drive
                    if service:
                        with st.spinner("💾 Guardando revisión en Google Drive..."):
                            try:
                                carpeta_raiz_id = obtener_o_crear_carpeta(service, CARPETA_RAIZ_NOMBRE)
                                carpeta_rev_id = obtener_o_crear_carpeta(service, nombre_revision.strip(), carpeta_raiz_id)
                                for nombre_arch, bytes_pdf in archivos_lista:
                                    subir_pdf_drive(service, nombre_arch, bytes_pdf, carpeta_rev_id)
                                st.success(f"✅ Revisión '{nombre_revision}' guardada en Google Drive")
                            except Exception as e:
                                st.warning(f"⚠️ No se pudo guardar en Drive: {e}")

                    st.session_state.archivos_procesados = archivos_lista
                    st.session_state.comparacion_ejecutada = True
                    st.session_state.revision_activa = nombre_revision.strip()
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

    if st.session_state.revision_activa:
        st.title(f"📂 {st.session_state.revision_activa}")
    else:
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

        st.markdown("### 📊 Resumen General")
        total_plazas_base  = len(dataframes_procesados[0])
        total_plazas_final = len(dataframes_procesados[-1])
        diferencia = total_plazas_final - total_plazas_base

        col1, col2, col3 = st.columns(3)
        col1.metric("Plazas Iniciales",   total_plazas_base,  help=f"Archivo: {info_archivos[0]['nombre']}")
        col2.metric("Plazas Finales",     total_plazas_final, delta=diferencia, help=f"Archivo: {info_archivos[-1]['nombre']}")
        col3.metric("Total de Versiones", len(dataframes_procesados))
        st.markdown("---")

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

                df_comp['Situación']         = df_comp.apply(det_estado_comp, axis=1)
                df_comp['Denominación']      = df_comp['Denominación_ACT'].fillna(df_comp['Denominación_ANT'])
                df_comp['Grupo']             = df_comp['Grupo_ACT'].fillna(df_comp['Grupo_ANT'])
                df_comp['Cuerpo']            = df_comp['Cuerpo_ACT'].fillna(df_comp['Cuerpo_ANT'])
                df_comp['Provincia']         = df_comp['Provincia_ACT'].fillna(df_comp['Provincia_ANT'])
                df_comp['Ocupante Anterior'] = df_comp['Ocupante_ANT'].fillna('-')
                df_comp['Ocupante Actual']   = df_comp['Ocupante_ACT'].fillna('-')
                df_comp['Dotación Anterior'] = df_comp['Dotación_ANT'].fillna('-')
                df_comp['Dotación Actual']   = df_comp['Dotación_ACT'].fillna('-')
                df_comp['Dotación']          = df_comp['Dotación_ACT'].fillna(df_comp['Dotación_ANT'])
                df_comp['Estado']            = df_comp['Estado_Plaza_ACT'].fillna(df_comp['Estado_Plaza_ANT'])

                nuevas        = len(df_comp[df_comp['Situación'] == '🆕 NUEVA'])
                eliminadas    = len(df_comp[df_comp['Situación'] == '❌ ELIMINADA'])
                cambios_ocu   = len(df_comp[df_comp['Situación'] == '🔄 CAMBIO OCUPANTE'])
                cambios_dot   = len(df_comp[df_comp['Situación'] == '💰 CAMBIO DOTACIÓN'])
                cambios_ambos = len(df_comp[df_comp['Situación'] == '🔄 CAMBIO OCUPANTE + DOTACIÓN'])

                col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
                col_m1.metric("🆕 Nuevas",         nuevas,     delta=f"+{nuevas}")
                col_m2.metric("❌ Eliminadas",      eliminadas, delta=f"-{eliminadas}")
                col_m3.metric("🔄 Cambio Ocupante", cambios_ocu)
                col_m4.metric("💰 Cambio Dotación", cambios_dot)
                col_m5.metric("🔄+💰 Ambos",        cambios_ambos)
                st.markdown("---")

                st.markdown("#### 🔎 Filtros")
                cf1, cf2, cf3, cf4 = st.columns(4)
                with cf1:
                    comp_filtro_prov = st.multiselect("Provincia", options=sorted(df_comp['Provincia'].dropna().unique()), key=f"comp_prov_{idx}")
                with cf2:
                    comp_filtro_grupo = st.multiselect("Grupo", options=sorted([g for g in df_comp['Grupo'].dropna().unique()]), key=f"comp_grupo_{idx}")
                with cf3:
                    comp_filtro_dot = st.multiselect("Dotación", options=sorted(df_comp['Dotación'].dropna().unique()), key=f"comp_dot_{idx}")
                with cf4:
                    comp_filtro_estado = st.multiselect("Estado Plaza", options=sorted(df_comp['Estado'].dropna().unique()), key=f"comp_estado_{idx}")

                df_comp_filtrado = df_comp.copy()
                if comp_filtro_prov:   df_comp_filtrado = df_comp_filtrado[df_comp_filtrado['Provincia'].isin(comp_filtro_prov)]
                if comp_filtro_grupo:  df_comp_filtrado = df_comp_filtrado[df_comp_filtrado['Grupo'].isin(comp_filtro_grupo)]
                if comp_filtro_dot:    df_comp_filtrado = df_comp_filtrado[df_comp_filtrado['Dotación'].isin(comp_filtro_dot)]
                if comp_filtro_estado: df_comp_filtrado = df_comp_filtrado[df_comp_filtrado['Estado'].isin(comp_filtro_estado)]

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

                MAX_TAB = 20
                nombre_ant_corto = info_archivos[idx]['nombre']
                nombre_act_corto = info_archivos[idx+1]['nombre']
                tab_ant = (f"📄 {nombre_ant_corto[:MAX_TAB]}..." if len(nombre_ant_corto) > MAX_TAB else f"📄 {nombre_ant_corto}")
                tab_act = (f"📄 {nombre_act_corto[:MAX_TAB]}..." if len(nombre_act_corto) > MAX_TAB else f"📄 {nombre_act_corto}")

                (
                    sub_tab_todos, sub_tab_nuevas, sub_tab_eliminadas,
                    sub_tab_cambios, sub_tab_dot, sub_tab_ambos,
                    sub_tab_pdf_ant, sub_tab_pdf_act,
                ) = st.tabs([
                    "🔍 TODOS", "🆕 Nuevas", "❌ Eliminadas",
                    "🔄 Cambio Ocupante", "💰 Cambio Dotación", "🔄+💰 Ambos",
                    tab_ant, tab_act,
                ])

                cols_mostrar = [
                    'Código', 'Denominación', 'Grupo', 'Cuerpo', 'Provincia', 'Situación',
                    'Dotación Anterior', 'Dotación Actual', 'Estado',
                    'Ocupante Anterior', 'Ocupante Actual'
                ]

                def color_rows(val):
                    if val == '❌ ELIMINADA':                    return 'background-color: #ffebee'
                    elif val == '🆕 NUEVA':                      return 'background-color: #e8f5e9'
                    elif val == '🔄 CAMBIO OCUPANTE':            return 'background-color: #fffde7'
                    elif val == '💰 CAMBIO DOTACIÓN':            return 'background-color: #e3f2fd'
                    elif val == '🔄 CAMBIO OCUPANTE + DOTACIÓN': return 'background-color: #f3e5f5'
                    elif val == '✅ SIN CAMBIOS':                return 'background-color: #f1f8f4'
                    return 'background-color: white'

                with sub_tab_todos:
                    st.dataframe(df_comp_filtrado[cols_mostrar].style.map(color_rows, subset=['Situación']), width='stretch', height=500)
                    st.caption(f"Total: {len(df_comp_filtrado)} plazas")

                with sub_tab_nuevas:
                    df_n = df_comp_filtrado[df_comp_filtrado['Situación'] == '🆕 NUEVA']
                    st.dataframe(df_n[cols_mostrar], width='stretch', height=500)
                    st.caption(f"Total: {len(df_n)} plazas nuevas")

                with sub_tab_eliminadas:
                    df_e = df_comp_filtrado[df_comp_filtrado['Situación'] == '❌ ELIMINADA']
                    st.dataframe(df_e[cols_mostrar], width='stretch', height=500)
                    st.caption(f"Total: {len(df_e)} plazas eliminadas")

                with sub_tab_cambios:
                    df_c = df_comp_filtrado[df_comp_filtrado['Situación'] == '🔄 CAMBIO OCUPANTE']
                    st.dataframe(df_c[cols_mostrar], width='stretch', height=500)
                    st.caption(f"Total: {len(df_c)} plazas con cambio de ocupante")

                with sub_tab_dot:
                    df_d = df_comp_filtrado[df_comp_filtrado['Situación'] == '💰 CAMBIO DOTACIÓN']
                    st.dataframe(df_d[cols_mostrar], width='stretch', height=500)
                    st.caption(f"Total: {len(df_d)} plazas con cambio de dotación")

                with sub_tab_ambos:
                    df_ab = df_comp_filtrado[df_comp_filtrado['Situación'] == '🔄 CAMBIO OCUPANTE + DOTACIÓN']
                    st.dataframe(df_ab[cols_mostrar], width='stretch', height=500)
                    st.caption(f"Total: {len(df_ab)} plazas con cambio de ocupante y dotación")

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
                    st.dataframe(df_f[['Código','Denominación','Grupo','Cuerpo','Provincia','Dotación','Estado_Plaza','Ocupante']], width='stretch', height=500)
                    st.caption(f"Mostrando {len(df_f)} de {len(df_old)} plazas")

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
                    st.dataframe(df_f[['Código','Denominación','Grupo','Cuerpo','Provincia','Dotación','Estado_Plaza','Ocupante']], width='stretch', height=500)
                    st.caption(f"Mostrando {len(df_f)} de {len(df_new)} plazas")

        st.markdown("---")
        if st.button("🔄 Cargar Nuevos Archivos", type="secondary"):
            st.session_state.archivos_procesados = None
            st.session_state.comparacion_ejecutada = False
            st.session_state.dataframes_procesados = None
            st.session_state.info_archivos = None
            st.session_state.revision_activa = None
            st.rerun()

    else:
        st.error("⚠️ No se pudieron procesar suficientes archivos para realizar la comparación")
        if st.button("🔄 Volver a cargar archivos"):
            st.session_state.archivos_procesados = None
            st.session_state.comparacion_ejecutada = False
            st.session_state.dataframes_procesados = None
            st.session_state.info_archivos = None
            st.session_state.revision_activa = None
            st.rerun()
