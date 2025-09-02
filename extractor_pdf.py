# extractor_pdf.py
import os
import re
import shutil
import logging
from datetime import datetime
from typing import List, Optional, Tuple

import fitz           # PyMuPDF (render a imágenes si hace falta)
import pdfplumber     # extracción de texto “nativo”
import cv2
import pytesseract
import numpy as np

from database import actualizar_archivo_constancia, parse_archivo_id_from_filename

# ===============================
# Rutas / logs
# ===============================
DIR_IN   = "pendientes"
DIR_OUT  = "procesados"
DIR_ERR  = "errores"

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename=os.path.join("logs", "procesar_pdf.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ===============================
# Tesseract (ajusta si aplica)
# ===============================
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
os.environ["TESSDATA_PREFIX"] = r"C:\Program Files\Tesseract-OCR\tessdata"

# ===============================
# Regex comunes
# ===============================
REGEX_RFC     = re.compile(r"\b[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}\b")
REGEX_CURP    = re.compile(r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\w\b")
REGEX_CP      = re.compile(r"\b\d{5}\b")
REGEX_ESTATUS = re.compile(r"\b(ACTIVO|BAJA|SUSPENDIDO|CANCELADO)\b", re.IGNORECASE)

# Etiquetas persona física (flexibles: con o sin espacio entre palabras)
LBL_NOMBRES = [r"NOMBRE\s*\(S\)"]
LBL_AP_P    = [r"PRIMER\s*APELLIDO", r"APELLIDO\s*PATERNO", r"PRIMERAPELLIDO", r"APELLIDOPATERNO"]
LBL_AP_M    = [r"SEGUNDO\s*APELLIDO", r"APELLIDO\s*MATERNO", r"SEGUNDOAPELLIDO", r"APELLIDOMATERNO"]

# Razón social persona moral (tolerante: con “o” o “/”, con/sin espacios)
REGEX_RAZON_TAGS = [
    r"NOMBRE\s*,?\s*DENOMINACI[ÓO]N\s*(?:/|O)?\s*RAZ[ÓO]N\s*SOCIAL",
    r"DENOMINACI[ÓO]N\s*(?:/|O)?\s*RAZ[ÓO]N\s*SOCIAL",
    r"RAZ[ÓO]N\s*SOCIAL",
]
REGEX_REGIMEN_TAG = r"R[ÉE]GIMEN\s*(?:DE\s*)?CAPITAL"

# ===============================
# Utilidades
# ===============================
def tidy(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = re.sub(r"\s{2,}", " ", s).strip()
    # Mantén acrónimos cortos en mayúsculas, resto en Title
    return " ".join(p if (p.isupper() and len(p) <= 3) else p.title() for p in s.split())

def is_all_caps_block(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    if any(ch.isdigit() for ch in s):
        return False
    letters = [ch for ch in s if ch.isalpha()]
    return len(letters) > 0 and sum(ch.isupper() for ch in letters) / len(letters) > 0.8

def despegado_razon(texto: str) -> str:
    """
    Intenta separar razón social pegada en mayúsculas.
    - Reemplaza bigramas frecuentes (DELA -> DE LA, etc.)
    - Inserta espacios delante de palabras frecuentes si están pegadas.
    """
    if not texto:
        return texto
    t = texto

    # Bigramas comunes
    t = re.sub(r'DELA', 'DE LA', t)
    t = re.sub(r'DELOS', 'DE LOS', t)
    t = re.sub(r'DELAS', 'DE LAS', t)
    t = re.sub(r'DEEL', 'DE EL', t)

    # Palabras frecuentes
    palabras = [
        'SECRETARIA', 'HACIENDA', 'PUBLICA', 'DE', 'LA', 'LOS', 'LAS',
        'SOCIEDAD', 'MEXICANA', 'NEUMOLOGIA', 'Y', 'CIRUGIA', 'TORAX',
        'DISTRIBUIDORA', 'EXPRESS', 'ALANIS'
    ]
    for w in set(palabras):
        t = re.sub(fr'(?<!\s){w}', f' {w}', t)

    t = re.sub(r'\s{2,}', ' ', t).strip()
    return " ".join(p if (p.isupper() and len(p) <= 3) else p.title() for p in t.split())

def ocr_image(img: np.ndarray) -> str:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)[1]
    return pytesseract.image_to_string(gray, lang="spa")

def read_pdf_text(pdf_path: str) -> str:
    """
    1) Intenta extraer texto nativo (pdfplumber)
    2) Si el texto es pobre, renderiza a imagen y aplica OCR (PyMuPDF + Tesseract)
    """
    text_parts: List[str] = []
    # 1) texto nativo
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t.strip():
                    text_parts.append(t)
    except Exception as e:
        logging.warning(f"pdfplumber falló en {pdf_path}: {e}")

    plain = "\n".join(text_parts)
    if len(plain) >= 100:  # suficiente
        return plain

    # 2) OCR por página
    try:
        doc = fitz.open(pdf_path)
        ocr_chunks = []
        for pg in doc:
            pix = pg.get_pixmap(dpi=240)  # resolución mayor para OCR
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            if pix.n == 4:  # RGBA -> BGR
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            else:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            ocr_chunks.append(ocr_image(img))
        doc.close()
        return "\n".join(ocr_chunks)
    except Exception as e:
        logging.error(f"OCR falló en {pdf_path}: {e}")
        return plain  # lo que haya

def split_lines(text: str) -> List[str]:
    return [l.strip() for l in text.splitlines() if l.strip()]

def _clean_val(s: str) -> str:
    s = re.sub(r'^[|•·\-\s]+', '', s or '')
    s = re.sub(r'\s{2,}', ' ', s).strip()
    return s

def value_after_label(lines: List[str],
                      label_patterns: List[str],
                      stop_patterns: Optional[List[str]] = None,
                      max_ahead: int = 40) -> Optional[str]:
    """
    Devuelve el primer valor después de la etiqueta (tolerante a saltos de línea).
    No exige mayúsculas y tolera etiquetas pegadas.
    """
    stop_patterns = stop_patterns or []
    U = [l.upper() for l in lines]
    for i, lu in enumerate(U):
        if any(re.search(p, lu) for p in label_patterns):
            for j in range(1, max_ahead + 1):
                k = i + j
                if k >= len(lines):
                    break
                raw = _clean_val(lines[k])
                up  = raw.upper()
                if ':' in up or any(re.search(p, up) for p in stop_patterns):
                    break
                if raw and not any(ch.isdigit() for ch in raw):
                    return raw
    return None

def grab_field(lines: List[str], label_patterns: List[str], max_lookahead: int = 4) -> Optional[str]:
    """
    Captura 'Etiqueta: Valor' o busca el valor en las siguientes N líneas.
    """
    for i, line in enumerate(lines):
        lu = line.upper()
        if any(re.search(p, lu) for p in label_patterns):
            m = re.search(r":\s*(.+)$", line)
            if m and m.group(1).strip():
                return _clean_val(m.group(1))
            for j in range(1, max_lookahead + 1):
                k = i + j
                if k < len(lines):
                    cand = _clean_val(lines[k])
                    if cand:
                        return cand
    return None

# === Heurística de tríos verticales (Nombre / ApP / ApM) y selección por prefijo RFC ===
NAME_PIECE = re.compile(r"^[A-ZÁÉÍÓÚÑa-záéíóúñ]{2,}(?:\s+[A-ZÁÉÍÓÚÑa-záéíóúñ]{2,})*$")

def _is_name_piece(s: str) -> bool:
    s = _clean_val(s)
    if not s or any(ch.isdigit() for ch in s):
        return False
    return bool(NAME_PIECE.match(s))

def collect_vertical_name_triplets(lines: List[str]) -> List[Tuple[str, str, str]]:
    cands: List[Tuple[str, str, str]] = []
    n = len(lines)
    for i in range(n - 2):
        a = _clean_val(lines[i])
        b = _clean_val(lines[i + 1])
        c = _clean_val(lines[i + 2])
        if _is_name_piece(a) and _is_name_piece(b) and _is_name_piece(c):
            cands.append((tidy(a), tidy(b), tidy(c)))
    return cands

def primera_vocal(p: str) -> str:
    p = p.upper()
    for ch in p[1:]:
        if ch in "AEIOU":
            return ch
    return "X"

def obtener_prefijo_desde_rfc(rfc: Optional[str]) -> str:
    return rfc[:4].upper() if rfc and len(rfc) >= 4 else ""

def mejor_comb_prefijo(cands: List[Tuple[str, str, str]], prefijo: str) -> Optional[Tuple[str, str, str]]:
    if not cands or not prefijo:
        return cands[0] if cands else None
    best, score_best = None, -1
    for n, ap, am in cands:
        pref = (ap[0] + primera_vocal(ap) + am[0] + n[0]).upper()
        score = sum(1 for a, b in zip(pref, prefijo) if a == b)
        if score > score_best:
            score_best, best = score, (n, ap, am)
    return best

def pick_triplet_by_rfc(cands: List[Tuple[str, str, str]], rfc: Optional[str]) -> Optional[Tuple[str, str, str]]:
    if not cands:
        return None
    pref = obtener_prefijo_desde_rfc(rfc)
    return mejor_comb_prefijo(cands, pref) if pref else cands[0]

def extraer_fecha_emision(lines: List[str]) -> Optional[str]:
    meses = {
        'ENERO':'01','FEBRERO':'02','MARZO':'03','ABRIL':'04','MAYO':'05','JUNIO':'06',
        'JULIO':'07','AGOSTO':'08','SEPTIEMBRE':'09','SETIEMBRE':'09','OCTUBRE':'10','NOVIEMBRE':'11','DICIEMBRE':'12'
    }
    texto = " ".join(lines)
    # A 21 DE MARZO DE 2024
    m = re.search(r'\bA\s+(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚ]+)\s+DE\s+(\d{4})\b', texto, re.IGNORECASE)
    if m:
        d = m.group(1).zfill(2); mo = meses.get(m.group(2).upper(), '01'); y = m.group(3)
        return f"{d}/{mo}/{y}"
    # 21 DE MARZO DE 2024
    m = re.search(r'\b(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚ]+)\s+DE\s+(\d{4})\b', texto, re.IGNORECASE)
    if m:
        d = m.group(1).zfill(2); mo = meses.get(m.group(2).upper(), '01'); y = m.group(3)
        return f"{d}/{mo}/{y}"
    # 24/06/2025 o 2025-06-24
    m = re.search(r'\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b', texto)
    if m:
        d = m.group(1).zfill(2); mo = m.group(2).zfill(2); y = m.group(3)
        return f"{d}/{mo}/{y}"
    m = re.search(r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b', texto)
    if m:
        y = m.group(1); mo = m.group(2).zfill(2); d = m.group(3).zfill(2)
        return f"{d}/{mo}/{y}"
    return None

# ===============================
# Extracción principal
# ===============================
def extract_from_pdf(path: str) -> dict:
    raw = read_pdf_text(path)
    lines = split_lines(raw)

    ctx = {
        "archivo": os.path.basename(path),
        "rfc": None, "curp": None,
        "nombre": None, "apellido_paterno": None, "apellido_materno": None,
        "estatus_padron": None, "codigo_postal": None,
        "fecha_emision": None, "tipo_contribuyente": None,
        "razon_social": None,
        "_raw": raw
    }

    # RFC/CURP/CP/Estatus
    for ln in lines:
        if not ctx["rfc"]:
            m = REGEX_RFC.search(ln);    ctx["rfc"] = m.group(0) if m else None or ctx["rfc"]
        if not ctx["curp"]:
            m = REGEX_CURP.search(ln);   ctx["curp"] = m.group(0) if m else None or ctx["curp"]
        if not ctx["codigo_postal"]:
            m = REGEX_CP.search(ln);     ctx["codigo_postal"] = m.group(0) if m else None or ctx["codigo_postal"]
        if not ctx["estatus_padron"]:
            m = REGEX_ESTATUS.search(ln)
            if m: ctx["estatus_padron"] = m.group(1).upper()

    # Heurística de tipo (prioriza CURP => FÍSICA)
    blob = " ".join(lines).upper()
    if ctx["curp"]:
        ctx["tipo_contribuyente"] = "FISICA"
    elif any(re.search(p, blob) for p in [*REGEX_RAZON_TAGS, REGEX_REGIMEN_TAG]):
        ctx["tipo_contribuyente"] = "MORAL"
    elif any(k in blob for k in ["NOMBRE (S)", "PRIMER APELLIDO", "SEGUNDO APELLIDO"]):
        ctx["tipo_contribuyente"] = "FISICA"
    else:
        ctx["tipo_contribuyente"] = "MORAL"

    # Fecha emisión
    ctx["fecha_emision"] = extraer_fecha_emision(lines)

    # MORAL: razón social (3 estrategias)
    if ctx["tipo_contribuyente"] == "MORAL":
        razon = None

        # (1) Campo explícito "Denominación/Razón Social"
        razon = grab_field(lines, REGEX_RAZON_TAGS, max_lookahead=6)

        # (2) Encabezado previo a "Lugar y Fecha de Emisión"
        if not razon:
            for i, ln in enumerate(lines):
                if "LUGAR Y FECHA DE EMISI" in ln.upper():
                    header_parts = []
                    for k in range(max(0, i-3), i):
                        if is_all_caps_block(lines[k]):
                            header_parts.append(_clean_val(lines[k]))
                    if header_parts:
                        razon = " ".join(header_parts).strip()
                    break

        # (3) Si está pegada, intentar despegado
        if razon and razon.isupper() and " " not in razon:
            razon = despegado_razon(razon)

        ctx["razon_social"] = tidy(razon)

    # FISICA: nombre y apellidos
    stop = [r"FECHA\s*INICIO", r"ESTATUS\s*EN\s*EL\s*PADR[ÓO]N",
            r"NOMBRE\s*COMERCIAL", r"DATOS\s*DEL\s*DOMICILIO",
            r"C[ÓO]DIGO\s*POSTAL", r"CONTACTO", r"P[ÁA]GINA", r"RFC", r"CURP"]

    if ctx["tipo_contribuyente"] == "FISICA":
        nombre_lbl = value_after_label(lines, LBL_NOMBRES, stop_patterns=stop, max_ahead=40)
        ap_p_lbl   = value_after_label(lines, LBL_AP_P,   stop_patterns=stop, max_ahead=40)
        ap_m_lbl   = value_after_label(lines, LBL_AP_M,   stop_patterns=stop, max_ahead=40)

        # Si falta alguno, busca tríos verticales
        if not (nombre_lbl and ap_p_lbl and ap_m_lbl):
            triplets = collect_vertical_name_triplets(lines)
            best = pick_triplet_by_rfc(triplets, ctx.get("rfc"))
            if best:
                if not nombre_lbl: nombre_lbl = best[0]
                if not ap_p_lbl:   ap_p_lbl   = best[1]
                if not ap_m_lbl:   ap_m_lbl   = best[2]

        # Fallback global por regex
        if not nombre_lbl:
            m = re.search(r"NOMBRE\s*\(S\)\s*:\s*([A-ZÁÉÍÓÚÑ ]+)", raw, re.IGNORECASE)
            nombre_lbl = _clean_val(m.group(1)) if m else None
        if not ap_p_lbl:
            m = re.search(r"(?:PRIMER\s*APELLIDO|APELLIDO\s*PATERNO)\s*:\s*([A-ZÁÉÍÓÚÑ ]+)", raw, re.IGNORECASE)
            ap_p_lbl = _clean_val(m.group(1)) if m else None
        if not ap_m_lbl:
            m = re.search(r"(?:SEGUNDO\s*APELLIDO|APELLIDO\s*MATERNO)\s*:\s*([A-ZÁÉÍÓÚÑ ]+)", raw, re.IGNORECASE)
            ap_m_lbl = _clean_val(m.group(1)) if m else None

        ctx["nombre"]           = tidy(nombre_lbl)
        ctx["apellido_paterno"] = tidy(ap_p_lbl)
        ctx["apellido_materno"] = tidy(ap_m_lbl)

    return ctx

# ===============================
# Proceso por archivo
# ===============================
def procesar_pdf(path: str) -> bool:
    fname = os.path.basename(path)
    logging.info(f"Inicia procesamiento de {fname}")
    try:
        data = extract_from_pdf(path)

        # Normalizar fecha para SQL
        try:
            if data.get("fecha_emision"):
                data["fecha_emision"] = datetime.strptime(data["fecha_emision"], "%d/%m/%Y").date()
            else:
                data["fecha_emision"] = None
        except Exception:
            data["fecha_emision"] = None

        archivo_id = parse_archivo_id_from_filename(fname)
        if not archivo_id:
            logging.error(f"No se pudo derivar ArchivoID desde el nombre: {fname}")
            shutil.move(path, os.path.join(DIR_ERR, fname))
            return False

        payload_sql = {
            "RFC": data.get("rfc"),
            "CURP": data.get("curp"),
            "TipoContribuyente": data.get("tipo_contribuyente"),
            "RazonSocial": data.get("razon_social"),
            "NombresPersona": data.get("nombre"),
            "ApellidoPaterno": data.get("apellido_paterno"),
            "ApellidoMaterno": data.get("apellido_materno"),
            "EstatusPadron": data.get("estatus_padron"),
            "CodigoPostal": data.get("codigo_postal"),
            "FechaEmision": data.get("fecha_emision"),
        }

        ok = actualizar_archivo_constancia(archivo_id, payload_sql)
        if not ok:
            logging.warning(f"No se afectó ninguna fila para ArchivoID={archivo_id}")
            shutil.move(path, os.path.join(DIR_ERR, fname))
            return False

        # mover a procesados y dejar una traza del texto
        new_path = os.path.join(DIR_OUT, fname)
        try:
            shutil.move(path, new_path)
        except Exception:
            try:
                os.remove(new_path); shutil.move(path, new_path)
            except Exception as e:
                logging.warning(f"No se pudo mover a procesados ({fname}): {e}")

        try:
            with open(os.path.splitext(new_path)[0] + "_ocr.txt", "w", encoding="utf-8") as f:
                f.write(data.get("_raw", ""))
        except Exception as e:
            logging.warning(f"No se pudo escribir traza OCR de {fname}: {e}")

        logging.info(f"Procesado correctamente {fname} | ArchivoID {archivo_id}")
        return True

    except Exception as e:
        logging.exception(f"Error crítico en {fname}: {e}")
        try:
            shutil.move(path, os.path.join(DIR_ERR, fname))
        except Exception:
            pass
        return False

# --- Alias opcional por si tu main viejo lo importa así ---
def procesar_archivo(path: str) -> bool:
    return procesar_pdf(path)
