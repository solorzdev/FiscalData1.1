# extractor_pdf.py
import fitz
import pytesseract
import cv2
import pdfplumber
import re
import os
import shutil
import logging
<<<<<<< Updated upstream
from wordsegment import load, segment
from database import guardar_datos, existe_rfc
=======
from datetime import datetime
from wordsegment import load, segment

# 🔹 Usamos el módulo database que expone conexión a ARCHIVOS y helpers
from database import actualizar_archivo_constancia, parse_archivo_id_from_filename
>>>>>>> Stashed changes

# === Configuración de logs ===
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    filename=os.path.join('logs', 'procesar_pdf.log'),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# === Carpetas de salida ===
RUTA_PROCESADOS = 'procesados'
RUTA_ERRORES = 'errores'
os.makedirs(RUTA_PROCESADOS, exist_ok=True)
os.makedirs(RUTA_ERRORES, exist_ok=True)

# Inicializar el modelo de segmentación para separar mayúsculas pegadas
load()

# === Separación OCR inteligente (mayúsculas pegadas) ===
def separar_palabras_mayusculas(texto: str) -> str:
    if not texto or ' ' in texto:
        return texto
    palabras = segment(texto.lower())
    return ' '.join(p.upper() for p in palabras)

# === Extraer texto de PDF (con OCR fallback) ===
def extraer_texto_pdf(ruta_pdf: str) -> str:
    # 1) Intento con extracción directa
    texto = ''
    try:
        with pdfplumber.open(ruta_pdf) as pdf:
            for pagina in pdf.pages:
                pagina_texto = pagina.extract_text()
                if pagina_texto:
                    texto += pagina_texto + '\n'
        if texto.strip():
            return texto
    except Exception as e:
        logging.warning(f"pdfplumber fallo en {ruta_pdf}: {e}")

    # 2) Fallback: rasterizar y pasar por OCR
    texto = ''
    doc = None
    try:
        doc = fitz.open(ruta_pdf)
        for pagina in doc:
            pix = pagina.get_pixmap(matrix=fitz.Matrix(2, 2))  # upscaling 2x
            output = 'pagina_temp.png'
            pix.save(output)

            imagen = cv2.imread(output)
            imagen = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
            imagen = cv2.threshold(imagen, 150, 255, cv2.THRESH_BINARY)[1]
            texto += pytesseract.image_to_string(imagen, lang='spa')
            try:
                os.remove(output)
            except Exception:
                pass
    finally:
        try:
            if doc: doc.close()
        except Exception:
            pass

    return texto

# === Extraer texto desde imagen ===
def extraer_texto_imagen(ruta_imagen: str) -> str:
    imagen = cv2.imread(ruta_imagen)
    imagen = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
    imagen = cv2.threshold(imagen, 150, 255, cv2.THRESH_BINARY)[1]
    texto = pytesseract.image_to_string(imagen, lang='spa')
    return texto

# === Obtener valor después de una etiqueta directa ===
def extraer_valor_simple(texto: str, etiqueta: str):
    idx = texto.find(etiqueta)
    if idx == -1:
        return None
    ini = idx + len(etiqueta)
    fin = texto.find('\n', ini)
    if fin == -1:
        fin = len(texto)
    return texto[ini:fin].strip()

# === Regex para campos flexibles ===
def extraer_campo_regex(texto: str, etiqueta_regex: str):
    patron = re.compile(rf'{etiqueta_regex}\s*(.*)', re.IGNORECASE)
    match = patron.search(texto)
    if match:
        valor = match.group(1).strip()
        fin = valor.find('\n')
        if fin != -1:
            valor = valor[:fin].strip()
        return valor
    return None

def extraer_fecha_emision(texto: str):
    """
    Tolera:
      - A 21 DE MARZO DE 2024   (misma línea o partido en dos)
      - 24 DE JUNIO DE 2025     (con o sin 'a las hh:mm horas')
    Devuelve dd/mm/yyyy o None.
    """
    lineas = texto.splitlines()
    meses = {
        'ENERO': '01','FEBRERO': '02','MARZO': '03','ABRIL': '04','MAYO': '05','JUNIO': '06',
        'JULIO': '07','AGOSTO': '08','SEPTIEMBRE': '09','OCTUBRE': '10','NOVIEMBRE': '11','DICIEMBRE': '12'
    }

    # Caso 2 líneas (A 21 DE) + (MARZO DE 2024)
    for i in range(len(lineas) - 1):
        l1 = lineas[i].strip()
        m_dia = re.search(r'A\s+(\d{1,2})\s+DE$', l1, re.IGNORECASE)
        if m_dia:
            dia = m_dia.group(1).zfill(2)
            for j in range(1, 4):
                if i + j < len(lineas):
                    l2 = lineas[i + j].strip()
                    m_mas = re.match(r'^([A-ZÑÁÉÍÓÚ]+)\s+DE\s+(\d{4})', l2, re.IGNORECASE)
                    if m_mas:
                        mes = meses.get(m_mas.group(1).upper(), '01')
                        anio = m_mas.group(2)
                        return f"{dia}/{mes}/{anio}"

    # Caso inline: "A 21 DE MARZO DE 2024"
    for l in lineas:
        m = re.search(r'A\s+(\d{1,2})\s+DE\s+([A-ZÑÁÉÍÓÚ]+)\s+DE\s+(\d{4})', l, re.IGNORECASE)
        if m:
            dia = m.group(1).zfill(2); mes = meses.get(m.group(2).upper(), '01'); anio = m.group(3)
            return f"{dia}/{mes}/{anio}"

    # Nuevo: "24 de junio de 2025" (+ texto extra)
    texto_unido = texto.replace('\n', ' ')
    m2 = re.search(r'(\d{1,2})\s+de\s+([A-ZÑÁÉÍÓÚ]+)\s+de\s+(\d{4})', texto_unido, re.IGNORECASE)
    if m2:
        dia = m2.group(1).zfill(2); mes = meses.get(m2.group(2).upper(), '01'); anio = m2.group(3)
        return f"{dia}/{mes}/{anio}"

    return None


def extraer_codigo_postal(texto: str):
    # En muchas constancias aparece tal cual "CódigoPostal:"
    idx = texto.find('CódigoPostal:')
    if idx == -1:
        return None
    ini = idx + len('CódigoPostal:')
    fin = ini + 5
    valor = texto[ini:fin]
    return valor.strip()

def extraer_datos(texto: str):
    datos = {}
    datos['rfc'] = extraer_valor_simple(texto, 'RFC: ')
    datos['fecha_emision'] = extraer_fecha_emision(texto)

    # MORAL si aparece Razón Social / Denominación
    razon_social = extraer_valor_simple(texto, 'Denominación/RazónSocial:')
    if razon_social:
        datos['tipo_contribuyente'] = 'MORAL'
        datos['razon_social'] = razon_social
        datos['regimen_capital'] = extraer_valor_simple(texto, 'RégimenCapital:')
        datos['nombre_comercial'] = extraer_valor_simple(texto, 'NombreComercial:')
        if datos['nombre_comercial'] == '':
            datos['nombre_comercial'] = None
        datos['nombre'] = None
        datos['apellido_paterno'] = None
        datos['apellido_materno'] = None
        datos['curp'] = None
    else:
        # FISICA por defecto
        datos['tipo_contribuyente'] = 'FISICA'
        datos['razon_social'] = None
        datos['regimen_capital'] = None
        datos['nombre_comercial'] = None
        datos['nombre'] = extraer_campo_regex(texto, r'Nombre\s*\(s\)\s*:')
        if datos['nombre'] and ' ' not in datos['nombre']:
            # Heurística para NOMBRE(S) pegados
            datos['nombre'] = ' '.join(n.upper() for n in segment(datos['nombre'].lower()))
        datos['curp'] = extraer_valor_simple(texto, 'CURP:')
        datos['apellido_paterno'] = extraer_valor_simple(texto, 'PrimerApellido:')
        datos['apellido_materno'] = extraer_valor_simple(texto, 'SegundoApellido:')

    datos['estatus_padron'] = extraer_valor_simple(texto, 'Estatusenelpadrón:')
    datos['codigo_postal'] = extraer_codigo_postal(texto)

    # Validación mínima
    if datos['rfc'] is None or datos['fecha_emision'] is None:
        return None

    # Limpieza de campos susceptibles a ir pegados
    for campo in ['razon_social', 'regimen_capital', 'nombre_comercial', 'nombre']:
        if datos.get(campo):
            datos[campo] = separar_palabras_mayusculas(datos[campo])

    return datos

def procesar_archivo(ruta_archivo: str):
    archivo = os.path.basename(ruta_archivo)
    nombre_sin_ext, ext = os.path.splitext(archivo)

    print(f"↪ Procesando: {archivo} ...")
    logging.info(f"Iniciando procesamiento de {archivo}")

    try:
        # 1) OCR / extracción de texto
        extension = ext.lower()
        if extension == '.pdf':
            texto = extraer_texto_pdf(ruta_archivo)
        elif extension in ('.png', '.jpg', '.jpeg', '.tif', '.tiff'):
            texto = extraer_texto_imagen(ruta_archivo)
        else:
            logging.warning(f"Extensión no soportada: {archivo}")
            shutil.move(ruta_archivo, os.path.join(RUTA_ERRORES, archivo))
            return None

        # 2) Parseo de campos
        datos = extraer_datos(texto)
<<<<<<< Updated upstream
        if datos:
            datos['archivo_origen'] = archivo
            datos['fecha_procesado'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # 📌 Verificación de RFC duplicado
            if existe_rfc(datos['rfc']):
                print(f"   ⚠️ RFC duplicado, se mueve a errores: {datos['rfc']}")
                logging.warning(f"Duplicado detectado para RFC {datos['rfc']}, no se guarda.")
                shutil.move(ruta_archivo, os.path.join(RUTA_ERRORES, archivo))
                return None

            # Guardado normal
            guardar_datos(datos)
            destino_pdf = os.path.join(RUTA_PROCESADOS, archivo)
            shutil.move(ruta_archivo, destino_pdf)

            # Guardar texto extraído
            ruta_txt = os.path.join(RUTA_PROCESADOS, f"{nombre_sin_ext}_ocr.txt")
            with open(ruta_txt, 'w', encoding='utf-8') as f:
                f.write(texto)

            print(f"   ✅ OK → {datos.get('tipo_contribuyente','?').upper()} | RFC {datos.get('rfc','?')} | {destino_pdf}")
            logging.info(f"Procesado correctamente: {archivo}")
        else:
=======
        if not datos:
>>>>>>> Stashed changes
            print(f"   ⚠️ No se extrajeron datos de: {archivo}")
            logging.warning(f"No se extrajeron datos de: {archivo}")
            shutil.move(ruta_archivo, os.path.join(RUTA_ERRORES, archivo))
            return None

        # 3) Normalizaciones finales
        datos['archivo_origen'] = archivo  # solo trazabilidad local
        # Fecha en tipo date para SQL Server
        try:
            datos['fecha_emision'] = datetime.strptime(datos['fecha_emision'], "%d/%m/%Y").date()
        except Exception:
            datos['fecha_emision'] = None

        # 4) Derivar ArchivoID desde el nombre del archivo (p.ej., "2310339.pdf" -> 2310339)
        archivo_id = parse_archivo_id_from_filename(archivo)
        if not archivo_id:
            logging.error(f"No se pudo derivar ArchivoID desde el nombre: {archivo}")
            shutil.move(ruta_archivo, os.path.join(RUTA_ERRORES, archivo))
            return None

        # 5) Mapear a columnas exactas de ARCHIVOS.dbo.Archivo (solo las que definiste)
        payload_sql = {
            "RFC": datos.get('rfc'),
            "CURP": datos.get('curp'),
            "TipoContribuyente": datos.get('tipo_contribuyente'),
            "RazonSocial": datos.get('razon_social'),
            "NombresPersona": datos.get('nombre'),
            "ApellidoPaterno": datos.get('apellido_paterno'),
            "ApellidoMaterno": datos.get('apellido_materno'),
            "EstatusPadron": datos.get('estatus_padron'),
            "CodigoPostal": datos.get('codigo_postal'),
            "FechaEmision": datos.get('fecha_emision'),
        }

        # 6) UPDATE en ARCHIVOS por ArchivoID (solo columnas no None + Procesado=1, FechaProcesado=GETDATE())
        ok = actualizar_archivo_constancia(archivo_id, payload_sql)
        if not ok:
            logging.warning(f"No se actualizó ninguna fila para ArchivoID={archivo_id}")
            shutil.move(ruta_archivo, os.path.join(RUTA_ERRORES, archivo))
            return None

        # 7) Mover a procesados y guardar OCR de traza
        destino_pdf = os.path.join(RUTA_PROCESADOS, archivo)
        try:
            shutil.move(ruta_archivo, destino_pdf)
        except Exception:
            # Si ya existía, lo sobrescribimos
            try:
                os.remove(destino_pdf)
                shutil.move(ruta_archivo, destino_pdf)
            except Exception as e:
                logging.warning(f"No se pudo mover a procesados ({archivo}): {e}")

        ruta_txt = os.path.join(RUTA_PROCESADOS, f"{nombre_sin_ext}_ocr.txt")
        try:
            with open(ruta_txt, 'w', encoding='utf-8') as f:
                f.write(texto)
        except Exception as e:
            logging.warning(f"No se pudo escribir OCR de {archivo}: {e}")

        print(f"   ✅ OK → {datos.get('tipo_contribuyente','?').upper()} | RFC {datos.get('rfc','?')} | ArchivoID {archivo_id}")
        logging.info(f"Procesado y actualizado ARCHIVOS para ArchivoID={archivo_id}")

    except Exception as e:
        try:
            shutil.move(ruta_archivo, os.path.join(RUTA_ERRORES, archivo))
        except Exception:
            pass
        print(f"   ❌ Error crítico con {archivo}: {e}")
        logging.error(f"Error crítico en {archivo}: {e}")

    return None
