"""Aplicación demostrativa de tickets de soporte IT para una planta.

Proyecto personal de portafolio. No está diseñado para producción: no incluye
autenticación ni debe exponerse a una red pública.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("SOPORTE_IT_DB", DATA_DIR / "soporte_it.db"))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "clave-local-solo-para-demo")

CATEGORIES = ["Hardware", "Software", "Red", "Accesos", "Impresora", "Otro"]
PRIORITIES = ["Baja", "Media", "Alta", "Crítica"]
STATUSES = ["Abierto", "En progreso", "En espera", "Resuelto", "Cerrado"]
AREAS = ["Producción", "Almacén", "Calidad", "Oficinas", "Embarques", "IT"]


def get_connection() -> sqlite3.Connection:
    """Abre una conexión SQLite con resultados accesibles por nombre de columna."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def db_session():
    """Gestiona transacciones y cierra siempre la conexión SQLite."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Crea las tablas si todavía no existen."""
    with db_session() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                requester TEXT NOT NULL,
                area TEXT NOT NULL,
                workstation TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Abierto',
                assigned_to TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ticket_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                detail TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
            CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority);
            CREATE INDEX IF NOT EXISTS idx_tickets_created_at ON tickets(created_at);
            """
        )


def now_text() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


@app.template_filter("priority_class")
def priority_class(priority: str) -> str:
    return {"Baja": "low", "Media": "medium", "Alta": "high", "Crítica": "critical"}.get(priority, "medium")


@app.route("/")
def dashboard():
    status_filter = request.args.get("status", "").strip()
    search = request.args.get("q", "").strip()
    clauses: list[str] = []
    params: list[str] = []

    if status_filter in STATUSES:
        clauses.append("status = ?")
        params.append(status_filter)
    if search:
        like = f"%{search}%"
        clauses.append("(title LIKE ? OR requester LIKE ? OR workstation LIKE ? OR area LIKE ?)")
        params.extend([like, like, like, like])

    where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
    with db_session() as conn:
        tickets = conn.execute(
            f"SELECT * FROM tickets{where_sql} ORDER BY "
            "CASE priority WHEN 'Crítica' THEN 1 WHEN 'Alta' THEN 2 WHEN 'Media' THEN 3 ELSE 4 END, "
            "created_at DESC LIMIT 200",
            params,
        ).fetchall()
        stats = {
            "total": conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0],
            "open": conn.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Abierto'").fetchone()[0],
            "progress": conn.execute("SELECT COUNT(*) FROM tickets WHERE status = 'En progreso'").fetchone()[0],
            "critical": conn.execute("SELECT COUNT(*) FROM tickets WHERE priority = 'Crítica' AND status NOT IN ('Resuelto','Cerrado')").fetchone()[0],
        }
    return render_template(
        "index.html", tickets=tickets, stats=stats, statuses=STATUSES,
        selected_status=status_filter, search=search,
    )


@app.route("/tickets/nuevo", methods=["GET", "POST"])
def new_ticket():
    if request.method == "POST":
        data = {key: request.form.get(key, "").strip() for key in (
            "title", "description", "requester", "area", "workstation", "category", "priority", "assigned_to"
        )}
        errors = []
        for field, label in (("title", "título"), ("description", "descripción"), ("requester", "nombre de quien reporta")):
            if not data[field]:
                errors.append(f"El campo {label} es obligatorio.")
        if data["area"] not in AREAS:
            errors.append("Selecciona un área válida.")
        if data["category"] not in CATEGORIES:
            errors.append("Selecciona una categoría válida.")
        if data["priority"] not in PRIORITIES:
            errors.append("Selecciona una prioridad válida.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("new_ticket.html", data=data, areas=AREAS, categories=CATEGORIES, priorities=PRIORITIES)

        stamp = now_text()
        with db_session() as conn:
            cursor = conn.execute(
                """INSERT INTO tickets
                   (title, description, requester, area, workstation, category, priority, status, assigned_to, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'Abierto', ?, ?, ?)""",
                (data["title"], data["description"], data["requester"], data["area"], data["workstation"],
                 data["category"], data["priority"], data["assigned_to"], stamp, stamp),
            )
            ticket_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO ticket_history (ticket_id, action, detail, changed_at) VALUES (?, ?, ?, ?)",
                (ticket_id, "Creación", "Ticket registrado con estado Abierto.", stamp),
            )
        flash(f"Ticket #{ticket_id} creado correctamente.", "success")
        return redirect(url_for("ticket_detail", ticket_id=ticket_id))

    return render_template("new_ticket.html", data={}, areas=AREAS, categories=CATEGORIES, priorities=PRIORITIES)


@app.route("/tickets/<int:ticket_id>", methods=["GET", "POST"])
def ticket_detail(ticket_id: int):
    with db_session() as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if ticket is None:
        abort(404)

    if request.method == "POST":
        new_status = request.form.get("status", "").strip()
        assigned_to = request.form.get("assigned_to", "").strip()
        note = request.form.get("note", "").strip()
        if new_status not in STATUSES:
            flash("Selecciona un estado válido.", "error")
            return redirect(url_for("ticket_detail", ticket_id=ticket_id))

        stamp = now_text()
        with db_session() as conn:
            conn.execute(
                "UPDATE tickets SET status = ?, assigned_to = ?, updated_at = ? WHERE id = ?",
                (new_status, assigned_to, stamp, ticket_id),
            )
            detail = f"Estado: {ticket['status']} → {new_status}. Responsable: {assigned_to or 'Sin asignar'}."
            if note:
                detail += f" Nota: {note}"
            conn.execute(
                "INSERT INTO ticket_history (ticket_id, action, detail, changed_at) VALUES (?, ?, ?, ?)",
                (ticket_id, "Actualización", detail, stamp),
            )
        flash("Ticket actualizado.", "success")
        return redirect(url_for("ticket_detail", ticket_id=ticket_id))

    with db_session() as conn:
        history = conn.execute(
            "SELECT * FROM ticket_history WHERE ticket_id = ? ORDER BY id DESC", (ticket_id,)
        ).fetchall()
    return render_template("ticket_detail.html", ticket=ticket, history=history, statuses=STATUSES)


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


init_db()

if __name__ == "__main__":
    print("Soporte IT Planta ejecutándose en http://127.0.0.1:5000")
    print("Demo local: no exponer a Internet ni introducir información real/sensible.")
    app.run(debug=True)
