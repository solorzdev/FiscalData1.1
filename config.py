# Configuración para conexiones

# === Remoto ARCHIVOS (SQL Server) ===
ARCHIVOS_SERVER   = '201.156.35.6'     # cambia si aplica
ARCHIVOS_DATABASE = 'ARCHIVOS'
ARCHIVOS_USER     = 'usrar08837a'                  # <== coloca el usuario
ARCHIVOS_PASSWORD = 'uU62$gstcCd129$'                  # <== coloca la contraseña
ARCHIVOS_DRIVER   = 'ODBC Driver 17 for SQL Server'  # asegúrate de tenerlo instalado

# Aliases para compatibilidad
DB_HOST = ARCHIVOS_SERVER
DB_USER = ARCHIVOS_USER
DB_PASSWORD = ARCHIVOS_PASSWORD
DB_NAME = ARCHIVOS_DATABASE
DB_PORT = 1433  # Puerto de SQL Server por defecto
