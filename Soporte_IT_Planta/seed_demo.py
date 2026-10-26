"""Agrega registros ficticios para explorar el panel. Ejecutar una sola vez."""
from app import db_session, now_text

SAMPLES = [
    ("Estación sin conexión a red", "La estación no puede acceder al sistema de producción. Verificar enlace físico y conectividad.", "Ana López", "Producción", "PC-PROD-014", "Red", "Crítica", "En progreso", "Mesa de ayuda"),
    ("Impresora de etiquetas no responde", "La impresora en embarques aparece desconectada después del cambio de turno.", "Luis Pérez", "Embarques", "PRN-EMB-003", "Hardware", "Alta", "Abierto", ""),
    ("Solicitud de instalación de software", "Se requiere instalar una herramienta autorizada en una estación de calidad.", "María Torres", "Calidad", "PC-CAL-008", "Software", "Media", "En espera", "Soporte IT"),
]

with db_session() as conn:
    for title, description, requester, area, workstation, category, priority, status, assigned_to in SAMPLES:
        stamp = now_text()
        cursor = conn.execute(
            """INSERT INTO tickets (title, description, requester, area, workstation, category, priority, status, assigned_to, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, description, requester, area, workstation, category, priority, status, assigned_to, stamp, stamp),
        )
        conn.execute(
            "INSERT INTO ticket_history (ticket_id, action, detail, changed_at) VALUES (?, ?, ?, ?)",
            (cursor.lastrowid, "Creación de ejemplo", "Registro ficticio agregado para demostrar la aplicación.", stamp),
        )
print("Se agregaron 3 tickets ficticios. Ejecuta este script solo una vez para evitar duplicados.")
