#!/usr/bin/env python3
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import ast
import json
import re
import sqlite3
import smtplib
import ssl
import threading
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
import subprocess
import uuid
from collections import Counter
from email.parser import BytesParser
from email.policy import default as email_policy

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
BIBLE_RVR = ROOT / "biblia" / "rvr1960"
BIBLE_LBLA = ROOT / "biblia" / "lbla"
BIBLE_VERSIONS = {
    "rvr1960": {"nombre":"Reina-Valera 1960", "abreviatura":"RVR1960"},
    "lbla": {"nombre":"La Biblia de las Américas", "abreviatura":"LBLA"}
}
DB = ROOT / "data" / "estudio.db"
EMAIL_CONFIG = ROOT / "data" / "correo_gmail.json"
DOCUMENTS = ROOT / "data" / "documentos"
RECORDINGS = ROOT / "data" / "grabaciones"
PORT = 8765
DOCUMENTS.mkdir(parents=True, exist_ok=True)
RECORDINGS.mkdir(parents=True, exist_ok=True)

BOOKS = [
 ("genesis","Génesis"),("exodo","Éxodo"),("levitico","Levítico"),("numeros","Números"),("deuteronomio","Deuteronomio"),
 ("josue","Josué"),("jueces","Jueces"),("rut","Rut"),("1_samuel","1 Samuel"),("2_samuel","2 Samuel"),
 ("1_reyes","1 Reyes"),("2_reyes","2 Reyes"),("1_cronicas","1 Crónicas"),("2_cronicas","2 Crónicas"),
 ("esdras","Esdras"),("nehemias","Nehemías"),("ester","Ester"),("job","Job"),("salmos","Salmos"),
 ("proverbios","Proverbios"),("eclesiastes","Eclesiastés"),("cantares","Cantares"),("isaias","Isaías"),
 ("jeremias","Jeremías"),("lamentaciones","Lamentaciones"),("ezequiel","Ezequiel"),("daniel","Daniel"),
 ("oseas","Oseas"),("joel","Joel"),("amos","Amós"),("abdias","Abdías"),("jonas","Jonás"),("miqueas","Miqueas"),
 ("nahum","Nahúm"),("habacuc","Habacuc"),("sofonias","Sofonías"),("hageo","Hageo"),("zacarias","Zacarías"),
 ("malaquias","Malaquías"),("mateo","Mateo"),("marcos","Marcos"),("lucas","Lucas"),("juan","Juan"),
 ("hechos","Hechos"),("romanos","Romanos"),("1_corintios","1 Corintios"),("2_corintios","2 Corintios"),
 ("galatas","Gálatas"),("efesios","Efesios"),("filipenses","Filipenses"),("colosenses","Colosenses"),
 ("1_tesalonicenses","1 Tesalonicenses"),("2_tesalonicenses","2 Tesalonicenses"),("1_timoteo","1 Timoteo"),
 ("2_timoteo","2 Timoteo"),("tito","Tito"),("filemon","Filemón"),("hebreos","Hebreos"),("santiago","Santiago"),
 ("1_pedro","1 Pedro"),("2_pedro","2 Pedro"),("1_juan","1 Juan"),("2_juan","2 Juan"),("3_juan","3 Juan"),
 ("judas","Judas"),("apocalipsis","Apocalipsis")]
BOOK_NAMES = dict(BOOKS)
_cache = {}

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS mensajes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL DEFAULT 'Mensaje sin título',
            texto_base TEXT NOT NULL DEFAULT '',
            tipo TEXT NOT NULL DEFAULT 'Borrador',
            contenido TEXT NOT NULL DEFAULT '',
            actualizado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")



# MODO_PREDICACION_V1
def init_presentations_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS presentaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mensaje_id INTEGER,
            titulo TEXT NOT NULL DEFAULT 'Nueva predicación',
            texto_base TEXT NOT NULL DEFAULT '',
            idea_central TEXT NOT NULL DEFAULT '',
            introduccion TEXT NOT NULL DEFAULT '',
            puntos TEXT NOT NULL DEFAULT '[]',
            versiculos TEXT NOT NULL DEFAULT '',
            aplicacion TEXT NOT NULL DEFAULT '',
            conclusion TEXT NOT NULL DEFAULT '',
            notas_privadas TEXT NOT NULL DEFAULT '',
            actualizado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")

def presentation_dict(row):
    value = dict(row)
    try: value["puntos"] = json.loads(value.get("puntos") or "[]")
    except Exception: value["puntos"] = []
    return value

def presentation_values(data):
    points = data.get("puntos", [])
    if not isinstance(points, list): points = []
    points = [str(point).strip()[:10000] for point in points if str(point).strip()][:30]
    return (
        str(data.get("titulo") or "Nueva predicación").strip()[:300],
        str(data.get("texto_base", ""))[:1000],
        str(data.get("idea_central", ""))[:5000],
        str(data.get("introduccion", ""))[:20000],
        json.dumps(points, ensure_ascii=False),
        str(data.get("versiculos", ""))[:10000],
        str(data.get("aplicacion", ""))[:20000],
        str(data.get("conclusion", ""))[:20000],
        str(data.get("notas_privadas", ""))[:30000]
    )


# RESALTADOR_BIBLICO_V1
HIGHLIGHT_COLORS = {"yellow", "green", "blue", "pink", "purple"}

def init_highlights_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS resaltados_biblicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL,
            libro TEXT NOT NULL,
            capitulo INTEGER NOT NULL,
            versiculo INTEGER NOT NULL,
            inicio INTEGER NOT NULL,
            fin INTEGER NOT NULL,
            texto TEXT NOT NULL,
            color TEXT NOT NULL DEFAULT 'yellow',
            nota TEXT NOT NULL DEFAULT '',
            creado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actualizado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE INDEX IF NOT EXISTS idx_resaltados_pasaje
            ON resaltados_biblicos(version,libro,capitulo,versiculo)""")

def validate_highlight(data):
    version = str(data.get("version", ""))
    book = str(data.get("libro", ""))
    chapter = int(data.get("capitulo", 0))
    verse = int(data.get("versiculo", 0))
    start = int(data.get("inicio", -1))
    end = int(data.get("fin", -1))
    color = str(data.get("color", "yellow"))
    if version not in BIBLE_VERSIONS: raise ValueError("Versión bíblica desconocida")
    if book not in BOOK_NAMES: raise ValueError("Libro desconocido")
    chapters = load_book(book, version)
    if chapter < 1 or chapter > len(chapters): raise ValueError("Capítulo inválido")
    verses = chapters[chapter - 1]
    if verse < 1 or verse > len(verses): raise ValueError("Versículo inválido")
    full_text = str(verses[verse - 1])
    if start < 0 or end <= start or end > len(full_text): raise ValueError("Selección inválida")
    if color not in HIGHLIGHT_COLORS: raise ValueError("Color inválido")
    selected = full_text[start:end]
    if not selected.strip(): raise ValueError("Selecciona un texto")
    return version, book, chapter, verse, start, end, selected, color

def init_reminders_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS recordatorios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            contenido TEXT NOT NULL DEFAULT '',
            hora TEXT NOT NULL,
            dias TEXT NOT NULL DEFAULT 'todos',
            activo INTEGER NOT NULL DEFAULT 1,
            ultimo_aviso TEXT NOT NULL DEFAULT '',
            creado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")


def init_email_reminders_db():
    with db() as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(recordatorios)")}
        for name, definition in (
            ("enviar_correo", "INTEGER NOT NULL DEFAULT 0"),
            ("correo_destino", "TEXT NOT NULL DEFAULT ''"),
            ("ultimo_envio_correo", "TEXT NOT NULL DEFAULT ''"),
            ("estado_correo", "TEXT NOT NULL DEFAULT ''")
        ):
            if name not in columns:
                con.execute(f"ALTER TABLE recordatorios ADD COLUMN {name} {definition}")

def load_email_config(include_password=False):
    if not EMAIL_CONFIG.is_file(): return {}
    try: value = json.loads(EMAIL_CONFIG.read_text(encoding="utf-8"))
    except Exception: return {}
    if not include_password: value.pop("app_password", None)
    return value

def save_email_config(data):
    sender = str(data.get("sender", "")).strip()
    recipient = str(data.get("recipient", "")).strip()
    password = str(data.get("app_password", "")).replace(" ", "").strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", sender): raise ValueError("Correo Gmail no válido")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", recipient): raise ValueError("Correo destinatario no válido")
    previous = load_email_config(True)
    if not password: password = previous.get("app_password", "")
    if not password: raise ValueError("Escribe la contraseña de aplicación de Gmail")
    value = {"provider":"gmail","sender":sender,"recipient":recipient,"app_password":password}
    EMAIL_CONFIG.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    EMAIL_CONFIG.chmod(0o600)
    return {"provider":"gmail","sender":sender,"recipient":recipient,"configured":True}

def send_gmail(subject, body, recipient=""):
    config = load_email_config(True)
    sender = config.get("sender", ""); password = config.get("app_password", "")
    destination = str(recipient or config.get("recipient", "")).strip()
    if not sender or not password or not destination: raise ValueError("Configura primero tu cuenta Gmail")
    message = EmailMessage()
    message["From"] = sender; message["To"] = destination; message["Subject"] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=25) as smtp:
        smtp.login(sender, password)
        smtp.send_message(message)
    return destination

def email_rule_applies(rule, now):
    weekday = now.weekday()
    if rule == "laborales": return weekday < 5
    if rule == "fin_semana": return weekday >= 5
    return True

def email_reminder_worker():
    while True:
        try:
            now = datetime.now(); current_time = now.strftime("%H:%M"); today = now.strftime("%Y-%m-%d")
            with db() as con:
                rows = con.execute("SELECT * FROM recordatorios WHERE activo=1 AND enviar_correo=1 AND hora=?", (current_time,)).fetchall()
            for row in rows:
                reminder = dict(row)
                if reminder.get("ultimo_envio_correo") == today or not email_rule_applies(reminder.get("dias"), now): continue
                try:
                    destination = send_gmail(
                        "Recordatorio bíblico: " + reminder.get("titulo", ""),
                        reminder_email_body(reminder),
                        reminder.get("correo_destino", "")
                    )
                    status = "Enviado a " + destination
                    with db() as con:
                        con.execute("UPDATE recordatorios SET ultimo_envio_correo=?,estado_correo=? WHERE id=?", (today,status,reminder["id"]))
                        if reminder.get("dias") == "una_vez": con.execute("UPDATE recordatorios SET activo=0 WHERE id=?", (reminder["id"],))
                except Exception as exc:
                    with db() as con: con.execute("UPDATE recordatorios SET estado_correo=? WHERE id=?", ("Error: "+str(exc)[:300],reminder["id"]))
        except Exception as exc:
            print("Error en recordatorios por correo:", exc)
        time.sleep(30)

def start_email_reminder_worker():
    threading.Thread(target=email_reminder_worker, name="recordatorios-correo", daemon=True).start()


def init_dashboard_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS uso_programa (
            fecha TEXT PRIMARY KEY,
            aperturas INTEGER NOT NULL DEFAULT 1,
            primera_apertura TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ultima_apertura TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS lecturas_consultadas (
            fecha TEXT NOT NULL,
            version TEXT NOT NULL,
            libro TEXT NOT NULL,
            capitulo INTEGER NOT NULL,
            consultado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(fecha,version,libro,capitulo)
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS estados_animo (
            fecha TEXT PRIMARY KEY,
            estado TEXT NOT NULL,
            nota TEXT NOT NULL DEFAULT '',
            actualizado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")

def local_today():
    return datetime.now().strftime("%Y-%m-%d")

def valid_day(value):
    try: return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception: return None

def usage_streak(dates):
    parsed = sorted({valid_day(x) for x in dates if valid_day(x)}, reverse=True)
    if not parsed: return 0
    today = datetime.now().date()
    if (today - parsed[0]).days > 1: return 0
    streak = 1
    for previous,current in zip(parsed, parsed[1:]):
        if (previous-current).days == 1: streak += 1
        else: break
    return streak

def dashboard_data():
    today = local_today()
    with db() as con:
        usage_dates = [row[0] for row in con.execute("SELECT fecha FROM uso_programa ORDER BY fecha DESC")]
        usage_days = con.execute("SELECT COUNT(*) FROM uso_programa").fetchone()[0]
        openings = con.execute("SELECT COALESCE(SUM(aperturas),0) FROM uso_programa").fetchone()[0]
        readings_total = con.execute("SELECT COUNT(*) FROM lecturas_consultadas").fetchone()[0]
        readings_today = con.execute("SELECT COUNT(*) FROM lecturas_consultadas WHERE fecha=?",(today,)).fetchone()[0]
        messages = con.execute("SELECT COUNT(*) FROM mensajes").fetchone()[0]
        reminders = con.execute("SELECT COUNT(*) FROM recordatorios WHERE activo=1").fetchone()[0]
        moods = [dict(row) for row in con.execute("SELECT fecha,estado,nota FROM estados_animo ORDER BY fecha DESC LIMIT 7")]
        mood_today = con.execute("SELECT fecha,estado,nota FROM estados_animo WHERE fecha=?",(today,)).fetchone()
    documents = sum(1 for path in DOCUMENTS.glob("*.json")) if 'DOCUMENTS' in globals() else 0
    recordings = sum(1 for path in RECORDINGS.glob("*.json")) if 'RECORDINGS' in globals() else 0
    return {"fecha":today,"dias_uso":usage_days,"aperturas":openings,"racha":usage_streak(usage_dates),
            "lecturas_total":readings_total,"lecturas_hoy":readings_today,"mensajes":messages,
            "recordatorios":reminders,"documentos":documents,"grabaciones":recordings,
            "estado_hoy":dict(mood_today) if mood_today else None,"historial_animo":moods}


# CONCENTRACION_REPORTES_V1
AUTOMATION_DEFAULTS = {
    "late_enabled": True, "late_hour": "20:30", "late_days": 1,
    "weekly_enabled": False, "weekly_day": 6, "weekly_hour": "20:30",
    "monthly_enabled": True, "monthly_day": 1, "monthly_hour": "09:00",
    "recipient": ""
}
REPORT_VERSES = [
    ("Salmos 119:105", "salmos", 119, 105),
    ("Josué 1:8", "josue", 1, 8),
    ("2 Timoteo 3:16", "2_timoteo", 3, 16),
    ("Salmos 1:2", "salmos", 1, 2),
    ("Proverbios 3:5", "proverbios", 3, 5),
    ("Jeremías 33:3", "jeremias", 33, 3),
    ("Filipenses 4:13", "filipenses", 4, 13)
]

def init_automation_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS estados_plan (
            modo TEXT PRIMARY KEY, inicio TEXT NOT NULL DEFAULT '', dia_actual INTEGER NOT NULL DEFAULT 1,
            completadas INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0, dias_atraso INTEGER NOT NULL DEFAULT 0,
            hoy_completadas INTEGER NOT NULL DEFAULT 0, hoy_total INTEGER NOT NULL DEFAULT 0,
            ultimo_dia_completado INTEGER NOT NULL DEFAULT 0, reflexiones INTEGER NOT NULL DEFAULT 0,
            datos TEXT NOT NULL DEFAULT '{}', actualizado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS sesiones_concentracion (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, proposito TEXT NOT NULL DEFAULT '',
            notas TEXT NOT NULL DEFAULT '', minutos_planeados INTEGER NOT NULL DEFAULT 25,
            segundos_realizados INTEGER NOT NULL DEFAULT 0, completada INTEGER NOT NULL DEFAULT 0,
            creado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS configuracion_automatizaciones (
            id INTEGER PRIMARY KEY CHECK(id=1), datos TEXT NOT NULL DEFAULT '{}',
            actualizado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS envios_automaticos (
            tipo TEXT NOT NULL, periodo TEXT NOT NULL, estado TEXT NOT NULL DEFAULT '',
            enviado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(tipo,periodo)
        )""")

def automation_settings():
    with db() as con:
        row = con.execute("SELECT datos FROM configuracion_automatizaciones WHERE id=1").fetchone()
    value = dict(AUTOMATION_DEFAULTS)
    if row:
        try: value.update(json.loads(row[0] or "{}"))
        except Exception: pass
    return value

def save_automation_settings(data):
    value = dict(AUTOMATION_DEFAULTS)
    current = automation_settings(); value.update(current)
    for key in ("late_enabled", "weekly_enabled", "monthly_enabled"):
        if key in data: value[key] = bool(data[key])
    for key in ("late_hour", "weekly_hour", "monthly_hour"):
        if key in data:
            candidate = str(data[key])
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", candidate): raise ValueError("Hora no válida")
            value[key] = candidate
    for key, low, high in (("late_days",1,30),("weekly_day",0,6),("monthly_day",1,28)):
        if key in data:
            number = int(data[key])
            if number < low or number > high: raise ValueError("Valor de programación no válido")
            value[key] = number
    if "recipient" in data:
        recipient = str(data.get("recipient", "")).strip()[:320]
        if recipient and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", recipient): raise ValueError("Correo destinatario no válido")
        value["recipient"] = recipient
    with db() as con:
        con.execute("""INSERT INTO configuracion_automatizaciones(id,datos,actualizado) VALUES(1,?,datetime('now','localtime'))
            ON CONFLICT(id) DO UPDATE SET datos=excluded.datos,actualizado=datetime('now','localtime')""",
            (json.dumps(value, ensure_ascii=False),))
    return value

def report_verse(seed=None):
    position = (seed if seed is not None else datetime.now().toordinal()) % len(REPORT_VERSES)
    label, book, chapter, verse = REPORT_VERSES[position]
    try: text = load_book(book, "rvr1960")[chapter-1][verse-1]
    except Exception: text = "Lámpara es a mis pies tu palabra, y lumbrera a mi camino."
    return {"referencia": label, "texto": text}

def reminder_email_body(reminder):
    verse = report_verse()
    content = reminder.get("contenido") or "Tienes un recordatorio en Mi Estudio Bíblico."
    return f"{content}\n\nTexto bíblico\n“{verse['texto']}”\n{verse['referencia']} · RVR1960\n\n— Mi Estudio Bíblico"

def plan_rows():
    with db() as con: rows = con.execute("SELECT * FROM estados_plan ORDER BY actualizado DESC").fetchall()
    return [dict(row) for row in rows]

def period_stats(start, end):
    start_text, end_text = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    with db() as con:
        days = con.execute("SELECT COUNT(*) FROM uso_programa WHERE fecha BETWEEN ? AND ?",(start_text,end_text)).fetchone()[0]
        openings = con.execute("SELECT COALESCE(SUM(aperturas),0) FROM uso_programa WHERE fecha BETWEEN ? AND ?",(start_text,end_text)).fetchone()[0]
        readings = con.execute("SELECT COUNT(*) FROM lecturas_consultadas WHERE fecha BETWEEN ? AND ?",(start_text,end_text)).fetchone()[0]
        messages = con.execute("SELECT COUNT(*) FROM mensajes WHERE date(actualizado) BETWEEN ? AND ?",(start_text,end_text)).fetchone()[0]
        focus = con.execute("SELECT COUNT(*),COALESCE(SUM(segundos_realizados),0) FROM sesiones_concentracion WHERE date(creado) BETWEEN ? AND ?",(start_text,end_text)).fetchone()
        usage_dates = [r[0] for r in con.execute("SELECT fecha FROM uso_programa ORDER BY fecha DESC")]
    plans = plan_rows(); reflections = max([p.get("reflexiones",0) for p in plans] or [0])
    return {"dias_uso":days,"aperturas":openings,"lecturas":readings,"mensajes":messages,
            "sesiones":focus[0],"minutos_concentracion":round(focus[1]/60),"racha":usage_streak(usage_dates),
            "reflexiones":reflections,"planes":plans}

def build_report(kind="monthly", now=None):
    now = now or datetime.now()
    if kind == "weekly":
        start = (now - timedelta(days=6)).date(); title = "Resumen semanal"
    else:
        first = now.date().replace(day=1)
        previous = first - timedelta(days=1)
        start = previous.replace(day=1); now = datetime.combine(previous, datetime.min.time()); title = "Informe mensual"
    end = now.date(); stats = period_stats(start,end); verse = report_verse(end.toordinal())
    plan_text = []
    for plan in stats["planes"]:
        pct = round(100*plan["completadas"]/plan["total"]) if plan["total"] else 0
        name = "Biblia cronológica" if plan["modo"] == "cronologico" else "Nuevo y Antiguo Testamento"
        plan_text.append(f"• {name}: {plan['completadas']} de {plan['total']} lecturas ({pct} %)")
    body = f"""{title} de Mi Estudio Bíblico
Período: {start.strftime('%d-%m-%Y')} al {end.strftime('%d-%m-%Y')}

Tu avance
• Días de uso: {stats['dias_uso']}
• Aperturas del programa: {stats['aperturas']}
• Capítulos consultados: {stats['lecturas']}
• Mensajes preparados o actualizados: {stats['mensajes']}
• Reflexiones guardadas en el plan: {stats['reflexiones']}
• Sesiones de concentración: {stats['sesiones']} ({stats['minutos_concentracion']} minutos)
• Constancia actual: {stats['racha']} día(s)
{chr(10).join(plan_text) if plan_text else '• El progreso del plan se sincronizará al abrirlo.'}

Texto bíblico
“{verse['texto']}”
{verse['referencia']} · RVR1960

Sigue avanzando con calma y constancia.

— Mi Estudio Bíblico"""
    return {"titulo":title,"periodo_inicio":str(start),"periodo_fin":str(end),"estadisticas":stats,"versiculo":verse,"texto":body}

def build_late_message(plan):
    verse = report_verse()
    pending = max(0, int(plan.get("dias_atraso",0)))
    name = "Biblia cronológica" if plan.get("modo") == "cronologico" else "Nuevo y Antiguo Testamento"
    body = f"""Hola Miguel:

Tu plan {name} lleva aproximadamente {pending} día(s) pendiente(s). No te desanimes: puedes retomarlo hoy, aunque sea con una sola lectura.

“{verse['texto']}”
{verse['referencia']} · RVR1960

— Mi Estudio Bíblico"""
    return body

def already_sent(kind, period):
    with db() as con: return con.execute("SELECT 1 FROM envios_automaticos WHERE tipo=? AND periodo=?",(kind,period)).fetchone() is not None

def record_delivery(kind, period, state):
    with db() as con:
        con.execute("INSERT OR REPLACE INTO envios_automaticos(tipo,periodo,estado,enviado) VALUES(?,?,?,datetime('now','localtime'))",(kind,period,state[:500]))

def automatic_mail_worker():
    while True:
        try:
            now = datetime.now(); settings = automation_settings(); clock = now.strftime("%H:%M")
            configured = bool(load_email_config(True).get("app_password"))
            recipient = settings.get("recipient", "")
            if configured and settings.get("late_enabled") and clock == settings.get("late_hour"):
                for plan in plan_rows():
                    lag = int(plan.get("dias_atraso",0))
                    period = now.strftime("%Y-%m-%d") + ":" + plan["modo"]
                    if lag >= int(settings.get("late_days",1)) and not already_sent("atraso",period):
                        try:
                            send_gmail("Un mensaje para retomar tu lectura", build_late_message(plan), recipient)
                            record_delivery("atraso",period,"Enviado")
                        except Exception as exc: print("Error en aviso de atraso:",exc)
            weekly_period = now.strftime("%G-W%V")
            if configured and settings.get("weekly_enabled") and now.weekday() == int(settings.get("weekly_day",6)) and clock == settings.get("weekly_hour") and not already_sent("semanal",weekly_period):
                try:
                    report=build_report("weekly",now); send_gmail("Mi Estudio Bíblico — Resumen semanal",report["texto"],recipient); record_delivery("semanal",weekly_period,"Enviado")
                except Exception as exc: print("Error en informe semanal:",exc)
            monthly_period = now.strftime("%Y-%m")
            if configured and settings.get("monthly_enabled") and now.day == int(settings.get("monthly_day",1)) and clock == settings.get("monthly_hour") and not already_sent("mensual",monthly_period):
                try:
                    report=build_report("monthly",now); send_gmail("Mi Estudio Bíblico — Informe mensual",report["texto"],recipient); record_delivery("mensual",monthly_period,"Enviado")
                except Exception as exc: print("Error en informe mensual:",exc)
        except Exception as exc: print("Error en automatizaciones:",exc)
        time.sleep(30)

def start_automatic_mail_worker():
    threading.Thread(target=automatic_mail_worker,name="informes-automaticos",daemon=True).start()


def load_book(book, version="rvr1960"):
    if version not in BIBLE_VERSIONS: raise ValueError("Versión bíblica desconocida")
    if book not in BOOK_NAMES: raise ValueError("Libro desconocido")
    cache_key = (version, book)
    if cache_key in _cache: return _cache[cache_key]
    if version == "lbla":
        value = json.loads((BIBLE_LBLA / f"{book}.json").read_text(encoding="utf-8"))
    else:
        raw = (BIBLE_RVR / f"{book}.js").read_text(encoding="utf-8").strip()
        raw = re.sub(r'^(?:export\s+default|module\.exports\s*=)\s*', '', raw)
        raw = raw[:-1] if raw.endswith(';') else raw
        value = ast.literal_eval(raw)
    _cache[cache_key] = value
    return value


STOPWORDS = {"para","como","pero","porque","cuando","donde","desde","hasta","entre","sobre","ante","bajo","cabe","contra","durante","mediante","segun","sin","tras","que","del","las","los","una","uno","unos","unas","con","por","más","mas","sus","esta","este","estos","estas","esa","ese","eso","son","sea","ser","fue","han","hay","muy","todo","toda","todos","todas","cada","también","tambien","mismo","misma","puede","pueden","nos","nuestro","nuestra","Dios","dios","señor","Señor","él","ella","ellos","ellas","al","el","la","y","o","u","e","a","de","en","es","se","su","lo","le","ya","si","no"}
BOOK_PATTERN = r"(?:Génesis|Genesis|Éxodo|Exodo|Levítico|Levitico|Números|Numeros|Deuteronomio|Josué|Josue|Jueces|Rut|[12]\s*Samuel|[12]\s*Reyes|[12]\s*Crónicas|[12]\s*Cronicas|Esdras|Nehemías|Nehemias|Ester|Job|Salmos?|Proverbios|Eclesiastés|Eclesiastes|Cantares|Isaías|Isaias|Jeremías|Jeremias|Lamentaciones|Ezequiel|Daniel|Oseas|Joel|Amós|Amos|Abdías|Abdias|Jonás|Jonas|Miqueas|Nahúm|Nahum|Habacuc|Sofonías|Sofonias|Hageo|Zacarías|Zacarias|Malaquías|Malaquias|Mateo|Marcos|Lucas|Juan|Hechos|Romanos|[12]\s*Corintios|Gálatas|Galatas|Efesios|Filipenses|Colosenses|[12]\s*Tesalonicenses|[12]\s*Timoteo|Tito|Filemón|Filemon|Hebreos|Santiago|[12]\s*Pedro|[123]\s*Juan|Judas|Apocalipsis)"

def clean_text(text):
    text = text.replace("\x00", " ").replace("\r", "\n")
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def analyze_document(text):
    clean = clean_text(text)
    tokens = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{4,}", clean)
    normalized = [w.casefold() for w in tokens if w.casefold() not in {x.casefold() for x in STOPWORDS}]
    counts = Counter(normalized)
    keywords = [{"palabra": word, "frecuencia": count} for word,count in counts.most_common(12)]
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", clean) if 45 <= len(s.strip()) <= 500]
    scored = []
    for position,sentence in enumerate(sentences[:300]):
        words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{4,}", sentence.casefold())
        score = sum(counts.get(w, 0) for w in words) / max(len(words), 1)
        score *= max(0.7, 1.15 - position / 500)
        scored.append((score, position, sentence))
    chosen = sorted(sorted(scored, reverse=True)[:5], key=lambda x:x[1])
    summary_parts = [x[2] for x in chosen]
    summary = " ".join(summary_parts) if summary_parts else clean[:1200]
    refs = []
    seen = set()
    for match in re.finditer(BOOK_PATTERN + r"\s+(\d{1,3})\s*[:.,]\s*(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?", clean, re.IGNORECASE):
        ref = re.sub(r"\s+", " ", match.group(0)).strip().replace(".", ":", 1)
        key = ref.casefold()
        if key not in seen:
            seen.add(key); refs.append(ref)
        if len(refs) >= 50: break
    top = [k["palabra"] for k in keywords[:5]]
    questions = [f"¿Qué enseña el documento acerca de {word}?" for word in top[:3]]
    if refs: questions.append("¿Cómo apoyan las referencias bíblicas las ideas principales del material?")
    outline = []
    for i,part in enumerate(summary_parts[:3],1):
        short = part[:180].rstrip(" ,;:")
        outline.append({"punto":i,"idea":short + ("…" if len(part)>180 else "")})
    return {"resumen":summary[:3000],"palabras_clave":keywords,"referencias":refs,"preguntas":questions,"bosquejo":outline,"caracteres":len(clean),"palabras":len(tokens)}

def document_meta_path(doc_id):
    return DOCUMENTS / f"{doc_id}.json"

def load_document_meta(doc_id):
    path = document_meta_path(doc_id)
    if not path.is_file() or not re.fullmatch(r"[a-f0-9]{12}", doc_id): raise ValueError("Documento no encontrado")
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta = classify_document_meta(meta)
    path.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    return meta

def save_uploaded_pdf(filename, content):
    if len(content) > 150 * 1024 * 1024: raise ValueError("El PDF supera el límite de 30 MB")
    if not content.startswith(b"%PDF"): raise ValueError("El archivo seleccionado no parece ser un PDF válido")
    safe = re.sub(r"[^A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ._ -]+", "_", filename or "documento.pdf").strip() or "documento.pdf"
    if not safe.lower().endswith(".pdf"): safe += ".pdf"
    doc_id = uuid.uuid4().hex[:12]
    pdf_path = DOCUMENTS / f"{doc_id}.pdf"
    txt_path = DOCUMENTS / f"{doc_id}.txt"
    pdf_path.write_bytes(content)
    result = subprocess.run(["pdftotext", "-layout", str(pdf_path), str(txt_path)], capture_output=True, text=True)
    extracted = txt_path.read_text(encoding="utf-8", errors="replace") if txt_path.exists() else ""
    extracted = clean_text(extracted)
    state = "analizado" if len(extracted) >= 80 else "requiere_ocr"
    analysis = analyze_document(extracted) if extracted else {"resumen":"No se detectó texto digital. Este PDF probablemente está escaneado y requiere OCR.","palabras_clave":[],"referencias":[],"preguntas":[],"bosquejo":[],"caracteres":0,"palabras":0}
    meta = {"id":doc_id,"nombre":safe,"archivo":pdf_path.name,"texto":txt_path.name,"tamano":len(content),"estado":state,"creado":datetime_now(),"error_extraccion":result.stderr.strip(),"analisis":analysis,"notas":"","fichas":[]}
    document_meta_path(doc_id).write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    return meta

def datetime_now():
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def normalize_search(value):
    import unicodedata
    value = unicodedata.normalize("NFD", value.casefold())
    return "".join(ch for ch in value if unicodedata.category(ch) != "Mn")

def search_document_topic(meta, topic):
    topic = clean_text(topic)[:150]
    if len(topic) < 2: raise ValueError("Escribe un tema para analizar")
    text_name = meta.get("texto")
    if not text_name or not (DOCUMENTS / text_name).is_file():
        raise ValueError("El texto completo fue eliminado para liberar espacio; las fichas guardadas siguen disponibles")
    raw = (DOCUMENTS / text_name).read_text(encoding="utf-8", errors="replace")
    pages = raw.split("\f")
    needle = normalize_search(topic)
    words = [w for w in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+", needle) if len(w) > 2]
    findings = []
    for page_no,page in enumerate(pages,1):
        cleaned = clean_text(page)
        if not cleaned: continue
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", cleaned) if p.strip()]
        if len(paragraphs) <= 1:
            paragraphs = [p.strip() for p in re.split(r"(?<=[.!?])\s+", cleaned) if p.strip()]
        for idx,paragraph in enumerate(paragraphs):
            normalized = normalize_search(paragraph)
            exact = needle in normalized
            matches = sum(1 for word in words if word in normalized)
            if exact or (words and matches == len(words)):
                before = paragraphs[idx-1] if idx > 0 else ""
                after = paragraphs[idx+1] if idx+1 < len(paragraphs) else ""
                context = clean_text(" ".join(x for x in (before,paragraph,after) if x))
                findings.append({"pagina":page_no,"fragmento":context[:1800]})
                if len(findings) >= 30: break
        if len(findings) >= 30: break
    if not findings and words:
        # Búsqueda flexible: exige al menos la mitad de las palabras del tema.
        required = max(1, (len(words)+1)//2)
        for page_no,page in enumerate(pages,1):
            for paragraph in [p.strip() for p in re.split(r"\n+", clean_text(page)) if len(p.strip()) > 30]:
                normalized = normalize_search(paragraph)
                if sum(1 for word in words if word in normalized) >= required:
                    findings.append({"pagina":page_no,"fragmento":paragraph[:1800]})
                    if len(findings) >= 20: break
            if len(findings) >= 20: break
    joined = "\n\n".join(x["fragmento"] for x in findings)
    analysis = analyze_document(joined) if joined else {"resumen":"No se encontraron coincidencias suficientes para este tema.","palabras_clave":[],"referencias":[],"preguntas":[],"bosquejo":[],"caracteres":0,"palabras":0}
    return {"tema":topic,"coincidencias":len(findings),"paginas":sorted(set(x["pagina"] for x in findings)),"fragmentos":findings[:12],"analisis":analysis}

# BIBLIOTECA_INTELIGENTE_LOCAL_V1
def smart_document_fragments(meta, query="", limit=8):
    text_name = meta.get("texto")
    if not text_name or not (DOCUMENTS / text_name).is_file():
        raise ValueError("El texto completo fue eliminado; el análisis guardado sigue disponible, pero no se pueden preparar nuevos fragmentos")

    raw = (DOCUMENTS / text_name).read_text(encoding="utf-8", errors="replace")
    pages = raw.split("\f")
    query_words = [w for w in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+", normalize_search(query)) if len(w) > 2]

    keywords = [
        normalize_search(str(k.get("palabra", "")))
        for k in (meta.get("analisis") or {}).get("palabras_clave", [])[:10]
        if isinstance(k, dict)
    ]

    candidates = []
    total_pages = max(1, len(pages))
    for page_no, page in enumerate(pages, 1):
        cleaned = clean_text(page)
        if not cleaned:
            continue
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n|(?<=[.!?])\s+", cleaned) if 80 <= len(p.strip()) <= 2200]
        for idx, paragraph in enumerate(paragraphs):
            norm = normalize_search(paragraph)
            qscore = sum(6 for w in query_words if w in norm)
            kscore = sum(1 for w in keywords if w and w in norm)
            spread_bonus = 1.0 - abs((page_no / total_pages) - 0.5) * 0.15
            score = (qscore + kscore + min(len(paragraph), 1200) / 1200) * spread_bonus
            candidates.append((score, page_no, idx, paragraph[:1800]))

    if not candidates:
        raise ValueError("No se encontró texto suficiente para preparar el análisis")

    candidates.sort(key=lambda x: x[0], reverse=True)
    selected = []
    used_pages = set()

    for score, page_no, idx, paragraph in candidates:
        if page_no in used_pages:
            continue
        selected.append({"pagina": page_no, "fragmento": paragraph, "puntaje_local": round(score, 2)})
        used_pages.add(page_no)
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        chosen_keys = {(x["pagina"], x["fragmento"]) for x in selected}
        for score, page_no, idx, paragraph in candidates:
            key = (page_no, paragraph)
            if key in chosen_keys:
                continue
            selected.append({"pagina": page_no, "fragmento": paragraph, "puntaje_local": round(score, 2)})
            chosen_keys.add(key)
            if len(selected) >= limit:
                break

    selected.sort(key=lambda x: x["pagina"])
    return selected


def build_local_smart_preview(meta):
    analysis = meta.get("analisis") or {}
    keywords = [k.get("palabra") for k in analysis.get("palabras_clave", [])[:5] if isinstance(k, dict) and k.get("palabra")]
    outline = [x.get("idea") for x in analysis.get("bosquejo", []) if isinstance(x, dict) and x.get("idea")]
    summary = str(analysis.get("resumen") or "").strip()
    central = re.split(r"(?<=[.!?])\s+", summary)[0][:700] if summary else ""
    fragments = smart_document_fragments(meta, "", 8)

    return {
        "modo": "local",
        "ia_conectada": False,
        "tema_principal_provisional": ", ".join(keywords[:3]) if keywords else "Por determinar con IA",
        "punto_central_provisional": central or "Por determinar con IA",
        "ideas_provisionales": outline[:5],
        "referencias": analysis.get("referencias", [])[:20],
        "fragmentos": fragments,
        "aviso": "Preparación local completada. Ningún texto fue enviado a Internet."
    }


def build_local_question_preview(meta, question):
    question = clean_text(str(question or ""))[:500]
    if len(question) < 3:
        raise ValueError("Escribe una pregunta sobre el documento")

    result = search_document_topic(meta, question)
    fragments = result.get("fragmentos") or []
    if not fragments:
        words = [w for w in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+", question) if len(w) > 3]
        fragments = smart_document_fragments(meta, " ".join(words[:8]), 8)
    else:
        fragments = fragments[:8]

    return {
        "modo": "local",
        "ia_conectada": False,
        "pregunta": question,
        "coincidencias": result.get("coincidencias", len(fragments)),
        "paginas": sorted(set(int(x.get("pagina", 0)) for x in fragments if x.get("pagina"))),
        "fragmentos": fragments,
        "aviso": "Estos son los fragmentos locales que se enviarían a la IA cuando activemos la segunda etapa."
    }

def save_meta(meta):
    document_meta_path(meta["id"]).write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")


def read_pdf_bibliography(pdf_path):
    info = {}
    if pdf_path and pdf_path.is_file():
        result = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, text=True, errors="replace")
        for line in result.stdout.splitlines():
            if ":" not in line: continue
            key,value = line.split(":",1); info[key.strip().casefold()] = value.strip()
    def integer(name):
        match = re.search(r"\d+", info.get(name, "")); return int(match.group()) if match else 0
    return {"titulo":info.get("title", ""),"autor":info.get("author", ""),"fecha_publicacion":info.get("creationdate", ""),"editorial":info.get("publisher", "") or info.get("producer", ""),"paginas":integer("pages")}

def text_extraction_quality(text):
    sample = (text or "")[:120000]
    if len(sample.strip()) < 80: return "requiere_ocr"
    visible = [ch for ch in sample if not ch.isspace()]
    if not visible: return "requiere_ocr"
    letters = sum(ch.isalpha() or ch.isdigit() for ch in visible)
    suspicious = sum(ch in "@#$%^&*{}[]<>\\|~_" for ch in visible)
    word_tokens = re.findall(r"\S+", sample)
    normal_words = sum(bool(re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9.,;:¿?¡!()'\"-]+", w)) for w in word_tokens[:15000])
    ratio_letters = letters / len(visible)
    ratio_words = normal_words / max(1, min(len(word_tokens),15000))
    if ratio_letters < .62 or suspicious / len(visible) > .035 or ratio_words < .72: return "defectuoso"
    return "legible"

def classify_document_meta(meta):
    pdf_name = meta.get("archivo"); txt_name = meta.get("texto")
    pdf_path = DOCUMENTS / pdf_name if pdf_name else None
    txt_path = DOCUMENTS / txt_name if txt_name else None
    bibliography = meta.get("bibliografia") or {}
    detected = read_pdf_bibliography(pdf_path)
    for key,value in detected.items():
        if not bibliography.get(key) and value: bibliography[key] = value
    bibliography.setdefault("titulo", meta.get("nombre", ""))
    bibliography.setdefault("autor", "")
    bibliography.setdefault("fecha_publicacion", "")
    bibliography.setdefault("editorial", "")
    bibliography.setdefault("paginas", 0)
    size = pdf_path.stat().st_size if pdf_path and pdf_path.is_file() else int(meta.get("tamano") or 0)
    raw_text = txt_path.read_text(encoding="utf-8",errors="replace") if txt_path and txt_path.is_file() else ""
    quality = "archivado" if meta.get("estado") == "archivado" else text_extraction_quality(raw_text)
    large = int(bibliography.get("paginas") or 0) > 200 or size > 15*1024*1024
    meta["bibliografia"] = bibliography
    meta["tamano"] = size if pdf_path and pdf_path.is_file() else 0
    meta["tipo_documento"] = "grande" if large else "pequeno"
    meta["calidad_extraccion"] = quality
    if large:
        meta["analisis_general_omitido"] = True
    elif quality != "legible":
        meta["analisis_general_omitido"] = True
    else:
        meta["analisis_general_omitido"] = False
    return meta


def recording_meta_path(audio_id):
    return RECORDINGS / f"{audio_id}.json"

def load_recording_meta(audio_id):
    if not re.fullmatch(r"[a-f0-9]{12}", audio_id): raise ValueError("Grabación no encontrada")
    path = recording_meta_path(audio_id)
    if not path.is_file(): raise ValueError("Grabación no encontrada")
    return json.loads(path.read_text(encoding="utf-8"))

def save_recording(filename, content, title, mime):
    if not content: raise ValueError("La grabación está vacía")
    if len(content) > 200*1024*1024: raise ValueError("La grabación supera el límite de 200 MB")
    audio_id = uuid.uuid4().hex[:12]
    mime = (mime or "audio/webm").split(";",1)[0].strip().lower()
    extension = {"audio/ogg":".ogg","audio/mp4":".m4a","audio/mpeg":".mp3","audio/wav":".wav"}.get(mime,".webm")
    audio_path = RECORDINGS / f"{audio_id}{extension}"
    audio_path.write_bytes(content)
    meta = {"id":audio_id,"titulo":clean_text(title)[:250] or "Nueva reflexión","archivo":audio_path.name,"mime":mime,"tamano":len(content),"creado":datetime_now(),"duracion":None}
    recording_meta_path(audio_id).write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    return meta

class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        clean = urlparse(path).path.lstrip('/') or 'index.html'
        return str(STATIC / clean)

    def send_json(self, value, status=200):
        payload = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b'{}')

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            # CONCENTRACION_REPORTES_V1 GET
            if u.path == "/api/automation-settings": return self.send_json(automation_settings())
            if u.path == "/api/focus/sessions":
                with db() as con: rows=con.execute("SELECT * FROM sesiones_concentracion ORDER BY creado DESC LIMIT 20").fetchall()
                return self.send_json([dict(row) for row in rows])
            if u.path == "/api/plan-state": return self.send_json(plan_rows())
            if u.path == "/api/reports/preview":
                kind=q.get("kind",["monthly"])[0]
                return self.send_json(build_report("weekly" if kind=="weekly" else "monthly"))
            if u.path == "/api/books":
                version = q.get("version", ["rvr1960"])[0]
                if version not in BIBLE_VERSIONS: raise ValueError("Versión bíblica desconocida")
                return self.send_json([{"id": key, "nombre": name, "capitulos": len(load_book(key,version))} for key,name in BOOKS])
            if u.path == "/api/chapter":
                book = q.get("book", ["genesis"])[0]
                version = q.get("version", ["rvr1960"])[0]
                chapter = int(q.get("chapter", ["1"])[0])
                chapters = load_book(book, version)
                if chapter < 1 or chapter > len(chapters): raise ValueError("Capítulo inválido")
                info = BIBLE_VERSIONS[version]
                return self.send_json({"libro": BOOK_NAMES[book], "capitulo": chapter, "versiculos": chapters[chapter-1], "version":version, "version_nombre":info["nombre"], "abreviatura":info["abreviatura"]})
            if u.path == "/api/search":
                term = q.get("q", [""])[0].strip().casefold()
                requested = q.get("version", ["rvr1960"])[0]
                versions = list(BIBLE_VERSIONS) if requested == "ambas" else [requested]
                if any(version not in BIBLE_VERSIONS for version in versions): raise ValueError("Versión bíblica desconocida")
                results = []
                if len(term) >= 2:
                    for version in versions:
                        for key,name in BOOKS:
                            for ci, chapter in enumerate(load_book(key,version), 1):
                                for vi, verse in enumerate(chapter, 1):
                                    if term in verse.casefold():
                                        results.append({"libro_id":key,"libro":name,"capitulo":ci,"versiculo":vi,"texto":verse,"version":version,"abreviatura":BIBLE_VERSIONS[version]["abreviatura"]})
                                        if len(results) >= 100: return self.send_json(results)
                return self.send_json(results)
            if u.path == "/api/dashboard":
                return self.send_json(dashboard_data())
            if u.path == "/api/highlights":
                where = []; values = []
                for query_name, column in (("version","version"),("book","libro"),("chapter","capitulo"),("verse","versiculo"),("color","color")):
                    if query_name in q and q[query_name][0] != "":
                        where.append(column + "=?"); values.append(q[query_name][0])
                sql = "SELECT * FROM resaltados_biblicos"
                if where: sql += " WHERE " + " AND ".join(where)
                sql += " ORDER BY actualizado DESC,id DESC"
                with db() as con: rows = con.execute(sql, values).fetchall()
                return self.send_json([dict(row) for row in rows])
            if u.path == "/api/presentations":
                with db() as con:
                    rows = con.execute("SELECT * FROM presentaciones ORDER BY actualizado DESC").fetchall()
                return self.send_json([presentation_dict(row) for row in rows])
            presentation_match = re.fullmatch(r"/api/presentations/(\d+)", u.path)
            if presentation_match:
                with db() as con:
                    row = con.execute("SELECT * FROM presentaciones WHERE id=?", (int(presentation_match.group(1)),)).fetchone()
                if not row: raise ValueError("Presentación no encontrada")
                return self.send_json(presentation_dict(row))
            if u.path == "/api/messages":
                with db() as con:
                    rows = con.execute("SELECT * FROM mensajes ORDER BY actualizado DESC").fetchall()
                return self.send_json([dict(r) for r in rows])
            if u.path == "/api/reminders":
                with db() as con: rows = con.execute("SELECT * FROM recordatorios ORDER BY hora,id").fetchall()
                return self.send_json([dict(r) for r in rows])
            if u.path == "/api/email-config":
                config = load_email_config(False)
                return self.send_json({"provider":"gmail","sender":config.get("sender", ""),"recipient":config.get("recipient", ""),"configured":bool(config.get("sender"))})
            if u.path == "/api/recordings":
                rows = []
                for path in RECORDINGS.glob("*.json"):
                    try: rows.append(json.loads(path.read_text(encoding="utf-8")))
                    except Exception: pass
                rows.sort(key=lambda x:x.get("creado") or "", reverse=True)
                return self.send_json(rows)
            audio_match = re.fullmatch(r"/api/recordings/([a-f0-9]{12})/audio", u.path)
            if audio_match:
                meta = load_recording_meta(audio_match.group(1)); path = RECORDINGS / meta["archivo"]
                payload = path.read_bytes(); self.send_response(200); self.send_header("Content-Type",meta.get("mime") or "audio/webm"); self.send_header("Content-Length",str(len(payload))); self.send_header("Accept-Ranges","bytes"); self.end_headers(); self.wfile.write(payload); return
            if u.path == "/api/documents":
                rows = []
                for path in DOCUMENTS.glob("*.json"):
                    try:
                        item = json.loads(path.read_text(encoding="utf-8"))
                        if item.get("archivo") and (DOCUMENTS / item["archivo"]).is_file():
                            item["tamano"] = (DOCUMENTS / item["archivo"]).stat().st_size
                        rows.append({k:item.get(k) for k in ("id","nombre","estado","creado","tamano","archivo")})
                    except Exception: pass
                rows.sort(key=lambda x:x.get("creado") or "", reverse=True)
                return self.send_json(rows)
            match_doc = re.fullmatch(r"/api/documents/([a-f0-9]{12})", u.path)
            if match_doc:
                return self.send_json(load_document_meta(match_doc.group(1)))
            match_pdf = re.fullmatch(r"/api/documents/([a-f0-9]{12})/pdf", u.path)
            if match_pdf:
                meta = load_document_meta(match_pdf.group(1))
                path = DOCUMENTS / meta["archivo"]
                payload = path.read_bytes()
                self.send_response(200); self.send_header("Content-Type","application/pdf"); self.send_header("Content-Length",str(len(payload))); self.send_header("Content-Disposition",f'inline; filename="{meta["nombre"]}"'); self.end_headers(); self.wfile.write(payload); return
            return super().do_GET()
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 400)

    def do_POST(self):
        try:
            current_path = urlparse(self.path).path
            # CONCENTRACION_REPORTES_V1 POST
            if current_path == "/api/plan-state":
                data=self.read_json(); mode=str(data.get("modo",""))
                if mode not in ("cronologico","testamentos"): raise ValueError("Plan no válido")
                completed=data.get("completed") or {}; notes=data.get("notes") or {}
                if not isinstance(completed,dict) or not isinstance(notes,dict): raise ValueError("Progreso no válido")
                current=max(1,min(365,int(data.get("dia_actual",1)))); total=max(0,int(data.get("total",0)))
                done=len(completed); today_done=sum(1 for key in completed if str(key).startswith(str(current)+":"))
                day_numbers=[]
                for key in completed:
                    try: day_numbers.append(int(str(key).split(":",1)[0]))
                    except Exception: pass
                last=max(day_numbers or [0]); today_total=max(0,int(data.get("hoy_total",0)))
                payload={"completed":completed,"notes":notes}
                with db() as con:
                    con.execute("""INSERT INTO estados_plan(modo,inicio,dia_actual,completadas,total,dias_atraso,hoy_completadas,hoy_total,ultimo_dia_completado,reflexiones,datos,actualizado)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime')) ON CONFLICT(modo) DO UPDATE SET inicio=excluded.inicio,dia_actual=excluded.dia_actual,
                        completadas=excluded.completadas,total=excluded.total,dias_atraso=excluded.dias_atraso,hoy_completadas=excluded.hoy_completadas,hoy_total=excluded.hoy_total,
                        ultimo_dia_completado=excluded.ultimo_dia_completado,reflexiones=excluded.reflexiones,datos=excluded.datos,actualizado=datetime('now','localtime')""",
                        (mode,str(data.get("inicio",""))[:10],current,done,total,max(0,min(365,int(data.get("dias_atraso",0)))),today_done,today_total,last,len([x for x in notes.values() if str(x).strip()]),json.dumps(payload,ensure_ascii=False)))
                return self.send_json({"ok":True})
            if current_path == "/api/focus/sessions":
                data=self.read_json(); kind=str(data.get("tipo","estudio"))[:50]
                planned=max(1,min(240,int(data.get("minutos_planeados",25)))); seconds=max(0,min(86400,int(data.get("segundos_realizados",0))))
                with db() as con:
                    cur=con.execute("INSERT INTO sesiones_concentracion(tipo,proposito,notas,minutos_planeados,segundos_realizados,completada,creado) VALUES(?,?,?,?,?,?,datetime('now','localtime'))",
                        (kind,str(data.get("proposito",""))[:1000],str(data.get("notas",""))[:10000],planned,seconds,1 if data.get("completada") else 0))
                return self.send_json({"ok":True,"id":cur.lastrowid},201)
            if current_path == "/api/automation-settings": return self.send_json(save_automation_settings(self.read_json()))
            if current_path == "/api/reports/send":
                data=self.read_json(); kind="weekly" if data.get("kind")=="weekly" else "monthly"; report=build_report(kind)
                destination=send_gmail(("Resumen semanal" if kind=="weekly" else "Informe mensual")+" — Mi Estudio Bíblico",report["texto"],automation_settings().get("recipient",""))
                return self.send_json({"ok":True,"destination":destination})
            from_message_match = re.fullmatch(r"/api/presentations/from-message/(\d+)", current_path)
            if from_message_match:
                message_id = int(from_message_match.group(1))
                with db() as con:
                    message = con.execute("SELECT * FROM mensajes WHERE id=?", (message_id,)).fetchone()
                    if not message: raise ValueError("Mensaje no encontrado")
                    existing = con.execute("SELECT id FROM presentaciones WHERE mensaje_id=?", (message_id,)).fetchone()
                    if existing: return self.send_json({"ok":True,"id":existing["id"],"existing":True})
                    cur = con.execute("""INSERT INTO presentaciones
                        (mensaje_id,titulo,texto_base,notas_privadas,actualizado)
                        VALUES(?,?,?,?,datetime('now','localtime'))""",
                        (message_id,message["titulo"],message["texto_base"],message["contenido"]))
                return self.send_json({"ok":True,"id":cur.lastrowid},201)
            if current_path == "/api/highlights":
                data = self.read_json()
                version,book,chapter,verse,start,end,selected,color = validate_highlight(data)
                note = str(data.get("nota", "")).strip()[:5000]
                with db() as con:
                    overlap = con.execute("""SELECT id FROM resaltados_biblicos WHERE version=? AND libro=? AND capitulo=? AND versiculo=?
                        AND NOT(fin<=? OR inicio>=?) LIMIT 1""", (version,book,chapter,verse,start,end)).fetchone()
                    if overlap: raise ValueError("Ese texto ya está resaltado. Primero elimina o modifica la marca existente.")
                    cur = con.execute("""INSERT INTO resaltados_biblicos
                        (version,libro,capitulo,versiculo,inicio,fin,texto,color,nota,creado,actualizado)
                        VALUES(?,?,?,?,?,?,?,?,?,datetime('now','localtime'),datetime('now','localtime'))""",
                        (version,book,chapter,verse,start,end,selected,color,note))
                return self.send_json({"ok":True,"id":cur.lastrowid},201)
            if current_path == "/api/presentations":
                data = self.read_json(); values = presentation_values(data)
                with db() as con:
                    cur = con.execute("""INSERT INTO presentaciones
                        (titulo,texto_base,idea_central,introduccion,puntos,versiculos,aplicacion,conclusion,notas_privadas,actualizado)
                        VALUES(?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""", values)
                return self.send_json({"ok":True,"id":cur.lastrowid},201)
            if current_path == "/api/activity/visit":
                today = local_today()
                with db() as con:
                    con.execute("""INSERT INTO uso_programa(fecha,aperturas,primera_apertura,ultima_apertura) VALUES(?,1,datetime('now','localtime'),datetime('now','localtime'))
                        ON CONFLICT(fecha) DO UPDATE SET aperturas=aperturas+1,ultima_apertura=datetime('now','localtime')""",(today,))
                return self.send_json({"ok":True})
            if current_path == "/api/activity/reading":
                data = self.read_json(); book = str(data.get("book", "")); version = str(data.get("version", "rvr1960")); chapter = int(data.get("chapter", 0))
                if book not in BOOK_NAMES or chapter < 1: raise ValueError("Lectura no válida")
                with db() as con:
                    con.execute("INSERT OR IGNORE INTO lecturas_consultadas(fecha,version,libro,capitulo,consultado) VALUES(?,?,?,?,datetime('now','localtime'))",(local_today(),version,book,chapter))
                return self.send_json({"ok":True})
            if current_path == "/api/mood":
                data = self.read_json(); mood = str(data.get("estado", "")); note = str(data.get("nota", "")).strip()[:2000]
                allowed = {"muy_bien","bien","paz","triste","preocupado","fortaleza"}
                if mood not in allowed: raise ValueError("Selecciona cómo te sientes")
                with db() as con:
                    con.execute("""INSERT INTO estados_animo(fecha,estado,nota,actualizado) VALUES(?,?,?,datetime('now','localtime'))
                        ON CONFLICT(fecha) DO UPDATE SET estado=excluded.estado,nota=excluded.nota,actualizado=datetime('now','localtime')""",(local_today(),mood,note))
                return self.send_json({"ok":True})
            notified_match = re.fullmatch(r"/api/reminders/(\d+)/notified", current_path)
            if notified_match:
                data = self.read_json()
                with db() as con: con.execute("UPDATE recordatorios SET ultimo_aviso=? WHERE id=?",(str(data.get("fecha", "")),int(notified_match.group(1))))
                return self.send_json({"ok":True})
            if current_path == "/api/email-config":
                return self.send_json(save_email_config(self.read_json()))
            if current_path == "/api/email-test":
                data = self.read_json(); destination = send_gmail("Prueba de Mi Estudio Bíblico", "¡La conexión con Gmail funciona correctamente!\\n\\nDesde ahora podrás recibir tus recordatorios bíblicos por correo.", data.get("recipient", ""))
                return self.send_json({"ok":True,"destination":destination})
            if current_path == "/api/reminders":
                data = self.read_json(); title = str(data.get("titulo", "")).strip(); hour = str(data.get("hora", ""))
                if not title: raise ValueError("Escribe un título")
                if not re.fullmatch(r"(?:[01]\\d|2[0-3]):[0-5]\\d", hour): raise ValueError("Hora no válida")
                send_email = 1 if data.get("enviar_correo") else 0
                destination = str(data.get("correo_destino", "")).strip()[:320]
                if send_email and not load_email_config(False).get("configured") and not load_email_config(False).get("sender"): raise ValueError("Configura primero tu cuenta Gmail")
                with db() as con:
                    cur = con.execute("INSERT INTO recordatorios(titulo,contenido,hora,dias,activo,enviar_correo,correo_destino) VALUES(?,?,?,?,?,?,?)",(title[:250],str(data.get("contenido", ""))[:3000],hour,str(data.get("dias", "todos"))[:100],1 if data.get("activo",True) else 0,send_email,destination))
                return self.send_json({"ok":True,"id":cur.lastrowid},201)
            if current_path == "/api/recordings":
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 201*1024*1024: raise ValueError("Tamaño de grabación no permitido")
                content_type = self.headers.get("Content-Type", "")
                if "multipart/form-data" not in content_type: raise ValueError("Formato de grabación no válido")
                body = self.rfile.read(length)
                message = BytesParser(policy=email_policy).parsebytes((f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n").encode()+body)
                audio_part = next((p for p in message.iter_parts() if p.get_param("name",header="content-disposition")=="audio"),None)
                title_part = next((p for p in message.iter_parts() if p.get_param("name",header="content-disposition")=="titulo"),None)
                if audio_part is None: raise ValueError("No se recibió la grabación")
                title = title_part.get_content() if title_part is not None else "Nueva reflexión"
                meta = save_recording(audio_part.get_filename() or "grabacion.webm",audio_part.get_payload(decode=True) or b"",title,audio_part.get_content_type())
                return self.send_json(meta,201)
            # BIBLIOTECA_INTELIGENTE_LOCAL_V1 endpoints
            smart_match = re.fullmatch(r"/api/documents/([a-f0-9]{12})/smart-preview", current_path)
            if smart_match:
                meta = load_document_meta(smart_match.group(1))
                return self.send_json(build_local_smart_preview(meta))

            smart_question_match = re.fullmatch(r"/api/documents/([a-f0-9]{12})/smart-question-preview", current_path)
            if smart_question_match:
                data = self.read_json(); meta = load_document_meta(smart_question_match.group(1))
                return self.send_json(build_local_question_preview(meta, data.get("pregunta", "")))

            topic_match = re.fullmatch(r"/api/documents/([a-f0-9]{12})/topic", current_path)
            if topic_match:
                data = self.read_json(); meta = load_document_meta(topic_match.group(1))
                return self.send_json(search_document_topic(meta, data.get("tema", "")))
            card_match = re.fullmatch(r"/api/documents/([a-f0-9]{12})/cards", current_path)
            if card_match:
                data = self.read_json(); meta = load_document_meta(card_match.group(1))
                card = data.get("ficha") or {}
                if not card.get("tema"): raise ValueError("Ficha temática no válida")
                card["id"] = uuid.uuid4().hex[:10]; card["guardada"] = datetime_now()
                meta.setdefault("fichas", []).append(card); save_meta(meta)
                return self.send_json({"ok":True,"ficha":card}, 201)
            if current_path == "/api/documents":
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 151 * 1024 * 1024: raise ValueError("Tamaño de archivo no permitido")
                content_type = self.headers.get("Content-Type", "")
                if "multipart/form-data" not in content_type: raise ValueError("Formato de carga no válido")
                body = self.rfile.read(length)
                message = BytesParser(policy=email_policy).parsebytes((f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n").encode() + body)
                part = next((p for p in message.iter_parts() if p.get_param("name", header="content-disposition") == "archivo"), None)
                if part is None: raise ValueError("No se recibió el archivo")
                meta = save_uploaded_pdf(part.get_filename() or "documento.pdf", part.get_payload(decode=True) or b"")
                return self.send_json(meta, 201)
            if urlparse(self.path).path == "/api/messages":
                d = self.read_json()
                with db() as con:
                    cur = con.execute("INSERT INTO mensajes(titulo,texto_base,tipo,contenido,actualizado) VALUES(?,?,?,?,datetime('now','localtime'))",
                        (d.get("titulo") or "Mensaje sin título", d.get("texto_base", ""), d.get("tipo", "Borrador"), d.get("contenido", "")))
                return self.send_json({"ok": True, "id": cur.lastrowid}, 201)
            return self.send_json({"error":"Ruta no encontrada"},404)
        except Exception as exc:
            return self.send_json({"error":str(exc)},400)

    def do_DELETE(self):
        try:
            u = urlparse(self.path)
            # ELIMINAR_MENSAJES_ORDEN_PLAN_V1
            message_match = re.fullmatch(r"/api/messages/(\d+)", u.path)
            if message_match:
                message_id = int(message_match.group(1))
                with db() as con:
                    linked = con.execute("SELECT COUNT(*) FROM presentaciones WHERE mensaje_id=?", (message_id,)).fetchone()[0]
                    result = con.execute("DELETE FROM mensajes WHERE id=?", (message_id,))
                if not result.rowcount: return self.send_json({"error":"Mensaje no encontrado"},404)
                return self.send_json({"ok":True,"presentaciones_conservadas":linked})
            highlight_match = re.fullmatch(r"/api/highlights/(\d+)", u.path)
            if highlight_match:
                with db() as con: con.execute("DELETE FROM resaltados_biblicos WHERE id=?", (int(highlight_match.group(1)),))
                return self.send_json({"ok":True})
            presentation_match = re.fullmatch(r"/api/presentations/(\d+)", u.path)
            if presentation_match:
                with db() as con: con.execute("DELETE FROM presentaciones WHERE id=?", (int(presentation_match.group(1)),))
                return self.send_json({"ok":True})
            reminder_match = re.fullmatch(r"/api/reminders/(\d+)", u.path)
            if reminder_match:
                with db() as con: con.execute("DELETE FROM recordatorios WHERE id=?",(int(reminder_match.group(1)),))
                return self.send_json({"ok":True})
            audio_match = re.fullmatch(r"/api/recordings/([a-f0-9]{12})", u.path)
            if audio_match:
                audio_id = audio_match.group(1); meta = load_recording_meta(audio_id); path = RECORDINGS / meta["archivo"]
                if path.is_file(): path.unlink()
                recording_meta_path(audio_id).unlink(missing_ok=True)
                return self.send_json({"ok":True})
            match = re.fullmatch(r"/api/documents/([a-f0-9]{12})", u.path)
            if not match: return self.send_json({"error":"Ruta no encontrada"},404)
            doc_id = match.group(1); meta = load_document_meta(doc_id); mode = parse_qs(u.query).get("mode", ["all"])[0]
            for field in (("archivo","texto") if mode == "archive" else ("archivo","texto")):
                name = meta.get(field)
                if name:
                    path = DOCUMENTS / name
                    if path.is_file(): path.unlink()
                meta[field] = None
            if mode == "archive":
                meta["estado"] = "archivado"; meta["tamano"] = 0; save_meta(meta)
                return self.send_json({"ok":True,"modo":"archivado"})
            document_meta_path(doc_id).unlink(missing_ok=True)
            return self.send_json({"ok":True,"modo":"eliminado"})
        except Exception as exc:
            return self.send_json({"error":str(exc)},400)

    def do_PUT(self):
        try:
            current_path = urlparse(self.path).path
            highlight_match = re.fullmatch(r"/api/highlights/(\d+)", current_path)
            if highlight_match:
                data = self.read_json(); fields = []; values = []
                if "color" in data:
                    color = str(data.get("color", ""))
                    if color not in HIGHLIGHT_COLORS: raise ValueError("Color inválido")
                    fields.append("color=?"); values.append(color)
                if "nota" in data:
                    fields.append("nota=?"); values.append(str(data.get("nota", ""))[:5000])
                if fields:
                    values.append(int(highlight_match.group(1)))
                    with db() as con: con.execute("UPDATE resaltados_biblicos SET "+",".join(fields)+",actualizado=datetime('now','localtime') WHERE id=?", values)
                return self.send_json({"ok":True})
            presentation_match = re.fullmatch(r"/api/presentations/(\d+)", current_path)
            if presentation_match:
                data = self.read_json(); values = presentation_values(data) + (int(presentation_match.group(1)),)
                with db() as con:
                    con.execute("""UPDATE presentaciones SET titulo=?,texto_base=?,idea_central=?,introduccion=?,puntos=?,
                        versiculos=?,aplicacion=?,conclusion=?,notas_privadas=?,actualizado=datetime('now','localtime') WHERE id=?""", values)
                return self.send_json({"ok":True})
            reminder_match = re.fullmatch(r"/api/reminders/(\d+)", current_path)
            if reminder_match:
                data = self.read_json(); fields=[]; values=[]
                for key,column in (("titulo","titulo"),("contenido","contenido"),("hora","hora"),("dias","dias"),("activo","activo"),("enviar_correo","enviar_correo"),("correo_destino","correo_destino")):
                    if key in data:
                        fields.append(column+"=?"); values.append(1 if key=="activo" and data[key] else 0 if key=="activo" else str(data[key]))
                if fields:
                    values.append(int(reminder_match.group(1)))
                    with db() as con: con.execute("UPDATE recordatorios SET "+",".join(fields)+" WHERE id=?",values)
                return self.send_json({"ok":True})
            metadata_match = re.fullmatch(r"/api/documents/([a-f0-9]{12})/metadata", current_path)
            if metadata_match:
                data = self.read_json(); meta = load_document_meta(metadata_match.group(1)); bibliography = meta.setdefault("bibliografia", {})
                for key in ("titulo","autor","fecha_publicacion","editorial"):
                    bibliography[key] = str(data.get(key, bibliography.get(key, "")))[:500]
                save_meta(meta); return self.send_json({"ok":True,"bibliografia":bibliography})
            notes_match = re.fullmatch(r"/api/documents/([a-f0-9]{12})/notes", current_path)
            if notes_match:
                data = self.read_json(); meta = load_document_meta(notes_match.group(1))
                meta["notas"] = str(data.get("notas", ""))[:20000]; save_meta(meta)
                return self.send_json({"ok":True})
            match = re.fullmatch(r"/api/messages/(\d+)", current_path)
            if not match: return self.send_json({"error":"Ruta no encontrada"},404)
            d = self.read_json()
            with db() as con:
                con.execute("UPDATE mensajes SET titulo=?,texto_base=?,tipo=?,contenido=?,actualizado=datetime('now','localtime') WHERE id=?",
                    (d.get("titulo") or "Mensaje sin título", d.get("texto_base", ""), d.get("tipo", "Borrador"), d.get("contenido", ""), int(match.group(1))))
            return self.send_json({"ok":True})
        except Exception as exc:
            return self.send_json({"error":str(exc)},400)

if __name__ == "__main__":
    init_db()
    init_presentations_db()
    init_highlights_db()
    init_reminders_db()
    init_dashboard_db()
    init_email_reminders_db()
    init_automation_db()
    start_email_reminder_worker()
    start_automatic_mail_worker()
    print(f"Mi Estudio Bíblico: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
