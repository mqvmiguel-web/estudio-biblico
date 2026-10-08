#!/usr/bin/env python3
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import ast
import json
import re
import sqlite3
import subprocess
import uuid
from collections import Counter
from email.parser import BytesParser
from email.policy import default as email_policy

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
BIBLE = ROOT / "biblia" / "rvr1960"
DB = ROOT / "data" / "estudio.db"
DOCUMENTS = ROOT / "data" / "documentos"
PORT = 8765
DOCUMENTS.mkdir(parents=True, exist_ok=True)

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
    return json.loads(path.read_text(encoding="utf-8"))

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

def save_meta(meta):
    document_meta_path(meta["id"]).write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")

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
            u = urlparse(self.path); match = re.fullmatch(r"/api/documents/([a-f0-9]{12})", u.path)
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
    print(f"Mi Estudio Bíblico: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
