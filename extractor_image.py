# extractor_image.py
import os, re, shutil, time, logging
from glob import glob
from typing import List, Tuple, Optional

import pytesseract
from PIL import Image, ImageFilter
<<<<<<< Updated upstream

# 🔹 Conexión usando config.py
import mysql.connector
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_PORT

def conectar():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        port=DB_PORT
    )

def existe_rfc(rfc: Optional[str]) -> bool:
    if not rfc:
        return False
    conexion = conectar()
    cursor = conexion.cursor()
    cursor.execute("SELECT 1 FROM constancias WHERE rfc = %s LIMIT 1", (rfc,))
    existe = cursor.fetchone() is not None
    cursor.close()
    conexion.close()
    return existe

def guardar_datos(datos):
    conexion = conectar()
    cursor = conexion.cursor()
    sql = """
        INSERT INTO constancias (
            tipo_contribuyente, rfc, curp, fecha_emision, razon_social,
            regimen_capital, nombre_comercial,
            nombre, apellido_paterno, apellido_materno,
            estatus_padron, codigo_postal,
            archivo_origen, fecha_procesado
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    valores = (
        datos['tipo_contribuyente'],
        datos['rfc'],
        datos.get('curp'),
        datos['fecha_emision'],
        datos.get('razon_social'),
        datos.get('regimen_capital'),
        datos.get('nombre_comercial'),
        datos.get('nombre'),
        datos.get('apellido_paterno'),
        datos.get('apellido_materno'),
        datos['estatus_padron'],
        datos['codigo_postal'],
        datos.get('archivo_origen'),
        datos.get('fecha_procesado')
    )
    cursor.execute(sql, valores)
    conexion.commit()
    cursor.close()
    conexion.close()
=======
from datetime import datetime

import cv2

# 🔹 Usaremos las utilidades para actualizar ARCHIVOS
from database import actualizar_archivo_constancia, parse_archivo_id_from_filename
>>>>>>> Stashed changes

# ===============================
# Carpetas
# ===============================
DIR_IN   = "pendientes"
DIR_OUT  = "procesados"
DIR_ERR  = "errores"

# ===============================
# Logs
# ===============================
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename=os.path.join("logs", "procesar_imagenes.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ===============================
# Configuración Tesseract
# ===============================
LANG = "spa"
# Ajusta si tu Tesseract está en otra ruta:
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
os.environ["TESSDATA_PREFIX"] = r"C:\Program Files\Tesseract-OCR\tessdata"

# ===============================
# Regex
# ===============================
REGEX_RFC     = re.compile(r"\b[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}\b")
REGEX_CURP    = re.compile(r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\w\b")
REGEX_FECHA   = re.compile(r"\b\d{1,2}\s+DE\s+[A-ZÁÉÍÓÚ]+\s+DE\s+\d{4}\b", re.IGNORECASE)
REGEX_CP      = re.compile(r"\b\d{5}\b")
REGEX_ESTATUS = re.compile(r"\b(ACTIVO|BAJA|SUSPENDIDO|CANCELADO)\b", re.IGNORECASE)
REGEX_TOKEN   = re.compile(r"^[A-ZÑÁÉÍÓÚ]{3,20}$")

# MORAL (razón social / régimen / nombre comercial)
REGEX_RAZON   = re.compile(r"(?:DENOMINACI[ÓO]N(?:\s+O)?\s+RAZ[ÓO]N\s+SOCIAL|RAZ[ÓO]N\s+SOCIAL|NOMBRE,\s*DENOMINACI[ÓO]N\s*O\s*RAZ[ÓO]N\s*SOCIAL)\s*:\s*([A-Z0-9 .,&\-ÁÉÍÓÚÑ/]+)")
REGEX_REGCAP  = re.compile(r"REG[IÍ]MEN(?:\s+DE)?\s+CAPITAL\s*:\s*([A-Z0-9 .,&\-ÁÉÍÓÚÑ/]+)")
REGEX_NCOM    = re.compile(r"NOMBRE\s+COMERCIAL\s*:\s*([A-Z0-9 .,&\-ÁÉÍÓÚÑ/]+)")

# FISICA (etiquetas)
REGEX_NOMBRES = re.compile(r"NOMBRE\s*\(S\)\s*:\s*([A-ZÁÉÍÓÚÑ ]+)", re.IGNORECASE)
REGEX_AP_P    = re.compile(r"PRIMER\s+APELLIDO\s*:\s*([A-ZÁÉÍÓÚÑ ]+)", re.IGNORECASE)
REGEX_AP_M    = re.compile(r"SEGUNDO\s+APELLIDO\s*:\s*([A-ZÁÉÍÓÚÑ ]+)", re.IGNORECASE)

REGEX_FECHA_A = re.compile(r"\bA\s+(\d{1,2}\s+DE\s+[A-ZÁÉÍÓÚ]+\s+DE\s+\d{4})\b", re.IGNORECASE)

# ===============================
# Utilidades de nombres / prefijos
# ===============================
def primera_vocal(p: str) -> str:
    for c in p[1:]:
        if c in "AEIOU":
            return c
    return "X"

def generar_prefijo_curp(ap_p: str, ap_m: str, nombre: str) -> str:
    try:
        return (ap_p[0] + primera_vocal(ap_p) + ap_m[0] + nombre[0]).upper()
    except Exception:
        return ""

def obtener_prefijo_desde_rfc(rfc: Optional[str]) -> str:
    return rfc[:4].upper() if rfc and len(rfc) >= 4 else ""

def mejor_comb_prefijo(candidatos: List[List[str]], prefijo_objetivo: str) -> Optional[Tuple[str, str, str]]:
    if not prefijo_objetivo:
        return None
    mejor_score = -1
    mejor = None
    for grupo in candidatos:
        if len(grupo) != 3:
            continue
        n, ap, am = grupo
        prefijo = generar_prefijo_curp(ap, am, n)
        if prefijo == prefijo_objetivo:
            return (n, ap, am)
        score = sum(1 for a, b in zip(prefijo, prefijo_objetivo) if a == b)
        if score > mejor_score:
            mejor_score = score
            mejor = (n, ap, am)
    return mejor

# ===============================
# Helpers comunes
# ===============================
def grab_field(lines, label_patterns, max_lookahead=2):
    U = [l.upper() for l in lines]
    for i, lu in enumerate(U):
        for pat in label_patterns:
            if re.search(pat, lu):
                raw_line = lines[i]
                m = re.search(r":\s*(.+)$", raw_line)
                if m and m.group(1).strip():
                    val = m.group(1).strip()
                else:
                    val = None
                    for j in range(1, max_lookahead + 1):
                        if i + j < len(lines):
                            cand = lines[i + j].strip()
                            if cand:
                                val = cand
                                break
                if val:
                    val = re.sub(r"[|•·]+", " ", val)
                    val = re.sub(r"\s{2,}", " ", val).strip()
                    return val.upper()
    return None

def value_after_label(lines: List[str],
                      label_patterns: List[str],
                      stop_patterns: Optional[List[str]] = None,
                      content_regex: Optional[re.Pattern] = None,
                      max_ahead: int = 40) -> Optional[str]:
    """
    Encuentra una etiqueta (ej. 'NOMBRE(S):') y devuelve el primer valor
    útil que aparezca en las siguientes líneas (soporta '| OCTAVIO', etc.).
    Se detiene si detecta otra etiqueta/sección.
    """
    stop_patterns = stop_patterns or []
    U = [l.upper() for l in lines]
    for i, lu in enumerate(U):
        if any(re.search(p, lu) for p in label_patterns):
            for j in range(1, max_ahead + 1):
                k = i + j
                if k >= len(lines):
                    break
                raw = lines[k].strip()
                up  = raw.upper()

                # si aparece otra etiqueta/encabezado, corta
                if ':' in up or any(re.search(p, up) for p in stop_patterns):
                    break

                cand = re.sub(r'^[|•·]+\s*', '', raw)
                cand = re.sub(r'\s{2,}', ' ', cand).strip()
                if not cand:
                    continue
                if content_regex is None or content_regex.search(cand):
                    return cand
    return None

# === Helpers para detectar tríos verticales y elegir por prefijo RFC ===
NAME_PIECE = re.compile(r"^[A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,})*$")

def _clean_val(s: str) -> str:
    s = re.sub(r'^[|•·\-\s]+', '', s or '')        # quita tuberías y bullets
    s = re.sub(r'\s{2,}', ' ', s).strip()
    return s

def _is_name_piece(s: str) -> bool:
    s = _clean_val(s).upper()
    if not s:
        return False
    if any(ch.isdigit() for ch in s):
        return False
    # permite nombres compuestos pero solo letras y espacios
    return bool(NAME_PIECE.match(s))

def collect_vertical_name_triplets(lines: List[str]) -> List[Tuple[str, str, str]]:
    """
    Busca cualquier trío vertical de líneas que luzcan como:
        <Nombre(s)>
        <Apellido Paterno>
        <Apellido Materno>
    en mayúsculas y sin dígitos. Devuelve lista de candidatos (Nombre, ApP, ApM).
    """
    cands: List[Tuple[str, str, str]] = []
    n = len(lines)
    for i in range(n - 2):
        a = _clean_val(lines[i])
        b = _clean_val(lines[i + 1])
        c = _clean_val(lines[i + 2])
        if _is_name_piece(a) and _is_name_piece(b) and _is_name_piece(c):
            # Normaliza a Title Case
            cands.append((a.title(), b.title(), c.title()))
    return cands

def pick_best_by_rfc_prefix(cands: List[Tuple[str, str, str]], rfc: Optional[str]) -> Optional[Tuple[str, str, str]]:
    """
    Usa el prefijo de RFC (primeros 4 de FÍSICA) para puntuar candidatos con mejor_comb_prefijo.
    Si no hay RFC, devuelve el primer candidato.
    """
    pref = obtener_prefijo_desde_rfc(rfc)
    if not cands:
        return None
    if pref:
        best = mejor_comb_prefijo([list(x) for x in cands], prefijo_objetivo=pref)
        if best:
            return best
    # Sin RFC o sin match: regresa el primero (heurística segura)
    return cands[0]

def detectar_por_claves_fisica(lineas: List[str]) -> Optional[Tuple[str, str, str]]:
    # Conserva el valor completo; limpia espacios extra
    nombre = ap_p = ap_m = None
    for line in lineas:
        l = line.replace("|", " ")
        if nombre is None:
            m = REGEX_NOMBRES.search(l)
            if m: nombre = re.sub(r'\s{2,}', ' ', m.group(1)).strip().title()
        if ap_p is None:
            m = REGEX_AP_P.search(l)
            if m: ap_p = re.sub(r'\s{2,}', ' ', m.group(1)).strip().title()
        if ap_m is None:
            m = REGEX_AP_M.search(l)
            if m: ap_m = re.sub(r'\s{2,}', ' ', m.group(1)).strip().title()
    if nombre or ap_p or ap_m:
        return (nombre, ap_p, ap_m)
    return None

def detectar_nombre_horizontal(lineas: List[str]) -> Optional[List[str]]:
    for line in lineas:
        palabras = [p for p in line.replace("|", " ").split() if p.isalpha()]
        if len(palabras) == 3 and all(p.isupper() for p in palabras):
            return palabras
    return None

def detectar_tipo_entidad(lineas: List[str]) -> str:
    texto = " ".join(lineas).upper()
    if ("RAZÓN SOCIAL" in texto or "RAZON SOCIAL" in texto
        or "DENOMINACIÓN O RAZÓN SOCIAL" in texto or "DENOMINACION O RAZON SOCIAL" in texto
        or "RÉGIMEN CAPITAL" in texto or "REGIMEN CAPITAL" in texto):
        return "MORAL"
    if ("NOMBRE (S)" in texto or "PRIMER APELLIDO" in texto or "SEGUNDO APELLIDO" in texto):
        return "FISICA"
    if detectar_nombre_horizontal(lineas):
        return "FISICA"
    return "MORAL"

def extraer_fecha_emision(lineas: List[str]) -> str:
    """
    Devuelve la fecha normalizada dd/mm/yyyy si la encuentra; 'No detectado' si no.
    Soporta:
      - "A 21 DE MARZO DE 2024" (misma línea o partido en 2)
      - "24 DE JUNIO DE 2025" (con o sin texto extra)
      - "24/06/2025" y "2025-06-24"
    """
    meses = {
        'ENERO':'01','FEBRERO':'02','MARZO':'03','ABRIL':'04','MAYO':'05','JUNIO':'06',
        'JULIO':'07','AGOSTO':'08','SEPTIEMBRE':'09','SETIEMBRE':'09','OCTUBRE':'10','NOVIEMBRE':'11','DICIEMBRE':'12'
    }

    # "A 21 DE MARZO DE 2024" (misma línea)
    for l in lineas:
        m = re.search(r'\bA\s+(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚ]+)\s+DE\s+(\d{4})\b', l, re.IGNORECASE)
        if m:
            d = m.group(1).zfill(2); mo = meses.get(m.group(2).upper(), '01'); y = m.group(3)
            return f"{d}/{mo}/{y}"

    # Partido en 2 líneas
    for i in range(len(lineas)-1):
        m1 = re.search(r'\bA\s+(\d{1,2})\s+DE\b', lineas[i], re.IGNORECASE)
        m2 = re.search(r'\b([A-ZÁÉÍÓÚ]+)\s+DE\s+(\d{4})\b', lineas[i+1], re.IGNORECASE)
        if m1 and m2:
            d = m1.group(1).zfill(2); mo = meses.get(m2.group(1).upper(), '01'); y = m2.group(2)
            return f"{d}/{mo}/{y}"

    # "24 DE JUNIO DE 2025"
    texto = " ".join(lineas)
    m = re.search(r'\b(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚ]+)\s+DE\s+(\d{4})\b', texto, re.IGNORECASE)
    if m:
        d = m.group(1).zfill(2); mo = meses.get(m.group(2).upper(), '01'); y = m.group(3)
        return f"{d}/{mo}/{y}"

    # 24/06/2025
    m = re.search(r'\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b', texto)
    if m:
        d = m.group(1).zfill(2); mo = m.group(2).zfill(2); y = m.group(3)
        return f"{d}/{mo}/{y}"

    # 2025-06-24
    m = re.search(r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b', texto)
    if m:
        y = m.group(1); mo = m.group(2).zfill(2); d = m.group(3).zfill(2)
        return f"{d}/{mo}/{y}"

    return "No detectado"

# ===============================
# OCR + extracción común (desde imagen)
# ===============================
def extract_from_image(path: str) -> dict:
    # Abrir con PIL para filtros
    img_pil = Image.open(path)
    img_pil = img_pil.convert("L")
    img_pil = img_pil.filter(ImageFilter.UnsharpMask(radius=2, percent=150))
    img_pil = img_pil.resize((img_pil.width * 2, img_pil.height * 2))

    # OCR
    ocr_text = pytesseract.image_to_string(img_pil, lang=LANG)
    lineas = [line.strip() for line in ocr_text.splitlines() if line.strip()]

    ctx = {
        "archivo": os.path.basename(path),
        "rfc": None,
        "curp": None,
        "nombre": None,
        "apellido_paterno": None,
        "apellido_materno": None,
        "fecha_emision": None,
        "fecha_inicio": None,
        "estatus_padron": None,
        "codigo_postal": None,
        "modo": "",
        "tipo_contribuyente": None,
        "razon_social": None,
        "regimen_capital": None,
        "nombre_comercial": None,
        "_ocr_text": ocr_text
    }

    # Scans básicos
    fechas_inline = []
    for linea in lineas:
        if not ctx["rfc"]:
            m = REGEX_RFC.search(linea)
            if m: ctx["rfc"] = m.group()
        if not ctx["curp"]:
            m = REGEX_CURP.search(linea)
            if m: ctx["curp"] = m.group()

        m = REGEX_FECHA.search(linea)
        if m:
            fechas_inline.append(m.group())

        if ctx["codigo_postal"] is None:
            m = REGEX_CP.search(linea)
            if m: ctx["codigo_postal"] = m.group()

        if ctx["estatus_padron"] is None:
            m = REGEX_ESTATUS.search(linea)
            if m: ctx["estatus_padron"] = m.group().upper()

    ctx["fecha_emision"] = extraer_fecha_emision(lineas)
    if len(fechas_inline) > 1:
        ctx["fecha_inicio"] = fechas_inline[1]

    tipo = detectar_tipo_entidad(lineas)
    ctx["tipo_contribuyente"] = tipo

    if tipo == "MORAL":
        # Razón Social, etc.
        razon = grab_field(lineas, [r"DENOMINACI[ÓO]N\s*(?:O)?\s*RAZ[ÓO]N\s*SOCIAL", r"RAZ[ÓO]N\s+SOCIAL", r"NOMBRE,\s*DENOMINACI[ÓO]N\s*O\s*RAZ[ÓO]N\s*SOCIAL"], max_lookahead=2)
        regcap = grab_field(lineas, [r"R[ÉE]GIMEN\s*(?:DE\s*)?CAPITAL"], max_lookahead=2)
        ncom   = grab_field(lineas, [r"NOMBRE\s+COMERCIAL"], max_lookahead=2)
        def tidy(x):
            if not x: return None
            return " ".join(p if (p.isupper() and len(p) <= 3) else p.title() for p in x.split())
        ctx["razon_social"]     = tidy(razon) if razon else None
        ctx["regimen_capital"]  = tidy(regcap) if regcap else None
        ctx["nombre_comercial"] = tidy(ncom) if ncom else None
    else:
        # FÍSICA:
        # 1) intenta por etiqueta con lookahead; 2) si falta, detecta tríos verticales en todo el OCR;
        # 3) elige el mejor por prefijo del RFC; 4) último fallback: regex globales.
        stop = [r"FECHA\s+INICIO", r"ESTATUS\s+EN\s+EL\s+PADR[ÓO]N",
                r"NOMBRE\s+COMERCIAL", r"DATOS\s+DEL\s+DOMICILIO",
                r"C[ÓO]DIGO\s+POSTAL", r"CONTACTO", r"P[ÁA]GINA", r"RFC", r"CURP"]
        rx_txt = re.compile(r"^[A-ZÁÉÍÓÚÑ ]{2,}$")

        # 1) Por etiqueta (valor puede estar varias líneas abajo)
        nombre_lbl = value_after_label(lineas, [r"NOMBRE\s*\(S\)"],
                                       stop_patterns=stop, content_regex=rx_txt, max_ahead=40)
        ap_p_lbl   = value_after_label(lineas, [r"PRIMER\s+APELLIDO", r"APELLIDO\s+PATERNO"],
                                       stop_patterns=stop, content_regex=rx_txt, max_ahead=40)
        ap_m_lbl   = value_after_label(lineas, [r"SEGUNDO\s+APELLIDO", r"APELLIDO\s+MATERNO"],
                                       stop_patterns=stop, content_regex=rx_txt, max_ahead=40)

        # 2) Si falta alguno, buscar tríos verticales en cualquier parte del documento
        need_vertical = not (nombre_lbl and ap_p_lbl and ap_m_lbl)
        best_triplet = None
        if need_vertical:
            triplets = collect_vertical_name_triplets(lineas)
            best_triplet = pick_best_by_rfc_prefix(triplets, ctx.get("rfc"))

        # 3) Fallback global por regex simples si aún falta algo
        if not nombre_lbl:
            if best_triplet: nombre_lbl = best_triplet[0]
            if not nombre_lbl:
                m = REGEX_NOMBRES.search(ocr_text); nombre_lbl = m.group(1).strip() if m else None
        if not ap_p_lbl:
            if best_triplet: ap_p_lbl = best_triplet[1]
            if not ap_p_lbl:
                m = REGEX_AP_P.search(ocr_text);    ap_p_lbl   = m.group(1).strip() if m else None
        if not ap_m_lbl:
            if best_triplet: ap_m_lbl = best_triplet[2]
            if not ap_m_lbl:
                m = REGEX_AP_M.search(ocr_text);    ap_m_lbl   = m.group(1).strip() if m else None

        def tidy(s): return re.sub(r'\s{2,}', ' ', s).strip().title() if s else None
        ctx["nombre"]           = tidy(nombre_lbl)
        ctx["apellido_paterno"] = tidy(ap_p_lbl)
        ctx["apellido_materno"] = tidy(ap_m_lbl)

    return ctx

# ===============================
# Storage helpers (solo traza local)
# ===============================
def convert_to_webp(img_path: str, quality: int = 80) -> str:
    base, ext = os.path.splitext(img_path)
    if ext.lower() == ".webp":
        return img_path
    try:
        im = Image.open(img_path)
        if im.mode in ("RGBA", "P"):
            im = im.convert("RGBA")
        else:
            im = im.convert("RGB")
        webp_path = base + ".webp"
        im.save(webp_path, "WEBP", quality=quality, method=6)
        os.remove(img_path)
        return webp_path
    except Exception as e:
        print(f"   ⚠️ No se pudo convertir a WebP ({img_path}): {e}")
        logging.warning(f"No se pudo convertir a WebP ({img_path}): {e}")
        return img_path

def purge_processed(retention_days: int = 7, base_dir: str = DIR_OUT):
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for root, _, files in os.walk(base_dir):
        for name in files:
            path = os.path.join(root, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except Exception:
                pass
    print(f"🧹 Purgados {removed} archivo(s) de '{base_dir}' (> {retention_days} días).")

# ===============================
# Main
# ===============================
def main():
    os.makedirs(DIR_IN, exist_ok=True)
    os.makedirs(DIR_OUT, exist_ok=True)
    os.makedirs(DIR_ERR, exist_ok=True)

    imgs = []
    for pat in ("*.png", "*.jpg", "*.jpeg", "*.tif", "*.tiff", "*.webp"):
        imgs.extend(glob(os.path.join(DIR_IN, pat)))

    if not imgs:
        print(f"❌ No hay imágenes en '{DIR_IN}'")
        logging.info("No hay imágenes para procesar.")
        purge_processed(retention_days=7, base_dir=DIR_OUT)
        return

    for path in imgs:
        fname = os.path.basename(path)
        print(f"↪ Procesando: {fname} ...")
        logging.info(f"Inicia procesamiento imagen: {fname}")

        try:
            data = extract_from_image(path)

<<<<<<< Updated upstream
            # Validaciones mínimas
            if not data.get("rfc"):
                print(f"   ⚠️ No se detectó RFC en: {fname}")
                logging.warning(f"No se detectó RFC en {fname}")
                shutil.move(path, os.path.join(DIR_ERR, fname))
                continue

            # Duplicado por RFC
            if existe_rfc(data["rfc"]):
                print(f"   ⚠️ RFC duplicado, se mueve a errores: {data['rfc']}")
                logging.warning(f"Duplicado detectado para RFC {data['rfc']} ({fname}), no se guarda.")
=======
            # Normalizar fecha a date (SQL Server)
            try:
                if data.get("fecha_emision") and data["fecha_emision"] != "No detectado":
                    data['fecha_emision'] = datetime.strptime(data['fecha_emision'], "%d/%m/%Y").date()
                else:
                    data['fecha_emision'] = None
            except Exception:
                data['fecha_emision'] = None

            # === Derivar ArchivoID desde el nombre del archivo (p.ej., "2310339.png" -> 2310339)
            archivo_id = parse_archivo_id_from_filename(fname)
            if not archivo_id:
                print(f"   ❌ No se pudo derivar ArchivoID desde: {fname}")
                logging.error(f"No se pudo derivar ArchivoID desde: {fname}")
>>>>>>> Stashed changes
                shutil.move(path, os.path.join(DIR_ERR, fname))
                continue

            # === Mapear a columnas de ARCHIVOS.dbo.Archivo
            payload_sql = {
                "RFC": data.get('rfc'),
                "CURP": data.get('curp'),
                "TipoContribuyente": data.get('tipo_contribuyente'),
                "RazonSocial": data.get('razon_social'),
                "NombresPersona": data.get('nombre'),
                "ApellidoPaterno": data.get('apellido_paterno'),
                "ApellidoMaterno": data.get('apellido_materno'),
                "EstatusPadron": data.get('estatus_padron'),
                "CodigoPostal": data.get('codigo_postal'),
                "FechaEmision": data.get('fecha_emision'),
            }

            # === UPDATE en ARCHIVOS (solo columnas no None + Procesado=1)
            ok = actualizar_archivo_constancia(archivo_id, payload_sql)
            if not ok:
                print(f"   ⚠️ No se afectó ninguna fila para ArchivoID={archivo_id}")
                logging.warning(f"No se actualizó ninguna fila para ArchivoID={archivo_id}")
                shutil.move(path, os.path.join(DIR_ERR, fname))
                continue

            # === Mover a procesados y guardar OCR de traza
            new_path = os.path.join(DIR_OUT, fname)
            try:
                shutil.move(path, new_path)
            except Exception:
                try:
                    os.remove(new_path)
                    shutil.move(path, new_path)
                except Exception as e:
                    logging.warning(f"No se pudo mover a procesados ({fname}): {e}")

            # Traza OCR
            debug_txt = os.path.splitext(new_path)[0] + "_ocr.txt"
            try:
                with open(debug_txt, "w", encoding="utf-8") as f:
                    f.write(data.get("_ocr_text", ""))
            except Exception as e:
                logging.warning(f"No se pudo escribir OCR de {fname}: {e}")

            print(f"   ✅ OK → {data.get('tipo_contribuyente','?')} | RFC {data.get('rfc','?')} | ArchivoID {archivo_id}")
            logging.info(f"Procesado correctamente {fname} | ArchivoID {archivo_id}")

        except Exception as e:
            try:
                shutil.move(path, os.path.join(DIR_ERR, fname))
            except Exception:
                pass
            print(f"   ❌ Error crítico con {fname}: {e}")
            logging.error(f"Error crítico procesando {fname}: {e}")

    purge_processed(retention_days=7, base_dir=DIR_OUT)
    print("🏁 Listo.")

if __name__ == "__main__":
    main()
