import re
from typing import Dict, Any, Optional
import pyodbc
from config import (
    ARCHIVOS_SERVER, ARCHIVOS_DATABASE, ARCHIVOS_USER, ARCHIVOS_PASSWORD, ARCHIVOS_DRIVER
)

# =========================
# Conexión SQL Server (ARCHIVOS)
# =========================
def connect_archivos():
    cs = (
        f"DRIVER={{{ARCHIVOS_DRIVER}}};"
        f"SERVER={ARCHIVOS_SERVER};"
        f"DATABASE={ARCHIVOS_DATABASE};"
        f"UID={ARCHIVOS_USER};PWD={ARCHIVOS_PASSWORD};"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(cs, autocommit=False)

# =========================
# Utilidades
# =========================
def parse_archivo_id_from_filename(filename: str) -> Optional[int]:
    """
    Busca el primer bloque numérico >=5 dígitos en el nombre de archivo.
    1014_231039.pdf -> 231039
    """
    import os
    base = os.path.basename(filename)
    m = re.search(r'(\d{5,})', base)
    try:
        return int(m.group(1)) if m else None
    except Exception:
        return None

# =========================
# UPDATE dinámico sobre ARCHIVOS.dbo.Archivo (módulo 1014)
# =========================
def actualizar_archivo_constancia(archivo_id: int, payload: Dict[str, Any]) -> bool:
    """
    Actualiza columnas de la fila Archivo(ArchivoID = archivo_id) con los pares (col, val)
    de 'payload' (solo columnas válidas y valores no None). Además:
       - Procesado = 1
       - FechaProcesado = GETDATE()
       - FechaMod = GETDATE()
    Devuelve True si afectó 1 fila.
    """
    if not archivo_id:
        return False

    columnas_validas = [
        "RFC", "CURP", "TipoContribuyente", "RazonSocial",
        "NombresPersona", "ApellidoPaterno", "ApellidoMaterno",
        "EstatusPadron", "CodigoPostal", "FechaEmision",
    ]

    sets, params = [], []
    for col in columnas_validas:
        if col in payload and payload[col] is not None:
            sets.append(f"{col} = ?")
            params.append(payload[col])

    if not sets:
        # Nada que actualizar: considerado OK para no reintentar en bucle
        return True

    sets.append("Procesado = 1")
    sets.append("FechaProcesado = GETDATE()")
    sets.append("FechaMod = GETDATE()")

    sql = f"""
        UPDATE ARCHIVOS.dbo.Archivo
           SET {", ".join(sets)}
         WHERE ArchivoID = ?;
    """
    params.append(archivo_id)

    cn = connect_archivos()
    try:
        cur = cn.cursor()
        cur.execute(sql, params)
        rows = cur.rowcount
        cn.commit()
        return rows == 1
    except Exception:
        try:
            cn.rollback()
        except:
            pass
        raise
    finally:
        try:
            cn.close()
        except:
            pass
