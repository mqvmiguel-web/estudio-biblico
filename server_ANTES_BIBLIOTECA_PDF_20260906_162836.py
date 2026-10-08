#!/usr/bin/env python3
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import ast
import json
import re
import sqlite3

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
BIBLE = ROOT / "biblia" / "rvr1960"
DB = ROOT / "data" / "estudio.db"
PORT = 8765

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

def load_book(book):
    if book in _cache: return _cache[book]
    if book not in BOOK_NAMES: raise ValueError("Libro desconocido")
    raw = (BIBLE / f"{book}.js").read_text(encoding="utf-8").strip()
    raw = re.sub(r'^(?:export\s+default|module\.exports\s*=)\s*', '', raw)
    raw = raw[:-1] if raw.endswith(';') else raw
    value = ast.literal_eval(raw)
    _cache[book] = value
    return value

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
            if u.path == "/api/books":
                return self.send_json([{"id": key, "nombre": name, "capitulos": len(load_book(key))} for key,name in BOOKS])
            if u.path == "/api/chapter":
                book = q.get("book", ["genesis"])[0]
                chapter = int(q.get("chapter", ["1"])[0])
                chapters = load_book(book)
                if chapter < 1 or chapter > len(chapters): raise ValueError("Capítulo inválido")
                return self.send_json({"libro": BOOK_NAMES[book], "capitulo": chapter, "versiculos": chapters[chapter-1]})
            if u.path == "/api/search":
                term = q.get("q", [""])[0].strip().casefold()
                results = []
                if len(term) >= 3:
                    for key,name in BOOKS:
                        for ci, chapter in enumerate(load_book(key), 1):
                            for vi, verse in enumerate(chapter, 1):
                                if term in verse.casefold():
                                    results.append({"libro_id":key,"libro":name,"capitulo":ci,"versiculo":vi,"texto":verse})
                                    if len(results) >= 100: return self.send_json(results)
                return self.send_json(results)
            if u.path == "/api/messages":
                with db() as con:
                    rows = con.execute("SELECT * FROM mensajes ORDER BY actualizado DESC").fetchall()
                return self.send_json([dict(r) for r in rows])
            return super().do_GET()
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 400)

    def do_POST(self):
        try:
            if urlparse(self.path).path == "/api/messages":
                d = self.read_json()
                with db() as con:
                    cur = con.execute("INSERT INTO mensajes(titulo,texto_base,tipo,contenido,actualizado) VALUES(?,?,?,?,datetime('now','localtime'))",
                        (d.get("titulo") or "Mensaje sin título", d.get("texto_base", ""), d.get("tipo", "Borrador"), d.get("contenido", "")))
                return self.send_json({"ok": True, "id": cur.lastrowid}, 201)
            return self.send_json({"error":"Ruta no encontrada"},404)
        except Exception as exc:
            return self.send_json({"error":str(exc)},400)

    def do_PUT(self):
        try:
            match = re.fullmatch(r"/api/messages/(\d+)", urlparse(self.path).path)
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
    print(f"Mi Estudio Bíblico: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
