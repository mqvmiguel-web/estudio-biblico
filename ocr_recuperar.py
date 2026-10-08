#!/usr/bin/env python3
"""Recupera con OCR las páginas cuyo texto interno está cifrado.

Muchos PDF traen fuentes sin mapa Unicode: el texto digital sale ilegible
("HHHD(%V&'D'&J") y arruina resúmenes, ideas y búsquedas. Este script renderiza
esas páginas con poppler y las reconoce con tesseract (español), y va mezclando
el resultado dentro del .txt del documento, sin tocar las páginas que ya eran
legibles.

Uso:
    python3 ocr_recuperar.py dc8c2e9da7d3 [--workers 4] [--solo 900-950]

Características:
  * Reanuda: los avances quedan en <doc>.ocr.jsonl (si se corta, sigue).
  * Reconstruye el .txt de forma atómica cada N páginas (la app sigue sirviendo).
  * Al terminar refresca la ficha: calidad de extracción y referencias bíblicas.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(BASE, "data", "documentos")
LOGS = os.path.join(BASE, "logs")
TESSDATA = os.path.expanduser("~/.local/share/tessdata")
IDIOMA = "spa"
DPI = 200
MAX_POR_TRAMO = 10  # páginas que renderiza poppler por invocación


def log(doc_id, mensaje):
    os.makedirs(LOGS, exist_ok=True)
    linea = f"{time.strftime('%H:%M:%S')} {mensaje}"
    print(linea, flush=True)
    with open(os.path.join(LOGS, f"ocr-{doc_id}.log"), "a", encoding="utf-8") as f:
        f.write(linea + "\n")


def _ocr_tramo(args):
    """Renderiza un tramo contiguo de páginas y devuelve {pagina: texto}."""
    paginas, pdf = args
    tmpdir = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"ocr_{os.getpid()}")
    os.makedirs(tmpdir, exist_ok=True)
    prefijo = os.path.join(tmpdir, "pg")
    salida = {}
    try:
        subprocess.run(
            ["pdftoppm", "-f", str(min(paginas)), "-l", str(max(paginas)),
             "-r", str(DPI), "-gray", "-png", pdf, prefijo],
            check=True, capture_output=True, timeout=600,
        )
        for ruta in sorted(glob.glob(prefijo + "-*.png")):
            match = re.search(r"-(\d+)\.png$", ruta)
            if not match:
                continue
            numero = int(match.group(1))
            if numero not in paginas:
                os.unlink(ruta)
                continue
            base = ruta[:-4]
            texto = ""
            try:
                subprocess.run(
                    ["tesseract", ruta, base, "-l", IDIOMA, "--psm", "3"],
                    check=True, capture_output=True, timeout=300,
                    env={**os.environ, "TESSDATA_PREFIX": TESSDATA},
                )
                with open(base + ".txt", encoding="utf-8", errors="replace") as f:
                    texto = f.read()
            except Exception:
                texto = ""
            finally:
                for basura in (ruta, base + ".txt"):
                    if os.path.exists(basura):
                        os.unlink(basura)
            salida[numero] = texto
    finally:
        for basura in glob.glob(prefijo + "-*"):
            try:
                os.unlink(basura)
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
    return salida


def tramos(paginas, maximo=MAX_POR_TRAMO):
    """Agrupa páginas consecutivas para renderizar de a varias por invocación."""
    grupos, actual = [], []
    for p in paginas:
        if actual and (p != actual[-1] + 1 or len(actual) >= maximo):
            grupos.append(actual)
            actual = []
        actual.append(p)
    if actual:
        grupos.append(actual)
    return grupos


def reconstruir(txt_path, paginas_originales, ocr):
    partes = [ocr.get(i, p) for i, p in enumerate(paginas_originales, 1)]
    temporal = txt_path + ".ocr-tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        f.write("\f".join(partes))
    os.replace(temporal, txt_path)  # atómico: la app nunca ve un .txt a medias


def refrescar_ficha(doc_id, total_ocr):
    sys.path.insert(0, BASE)
    import server as S  # todo el arranque está bajo __main__: importar es seguro
    meta_path = S.document_meta_path(doc_id)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    raw = (S.DOCUMENTS / meta["texto"]).read_text(encoding="utf-8", errors="replace")
    # El análisis general vino cifrado: se vuelve a generar con el texto recuperado.
    meta["analisis"] = S.analyze_document(S.clean_text(raw))
    meta["analisis"]["refs_v"] = 3
    meta = S.classify_document_meta(meta)
    meta["recuperacion_ocr"] = {
        "idioma": IDIOMA, "dpi": DPI, "paginas_recuperadas": total_ocr,
        "terminado": S.datetime_now(),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta.get("calidad_extraccion"), len(meta["analisis"].get("referencias") or [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_id")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cada", type=int, default=25, help="reconstruir el .txt cada N páginas")
    ap.add_argument("--solo", default="", help="rango de páginas, ej. 900-950")
    args = ap.parse_args()

    meta_path = os.path.join(DOCS, f"{args.doc_id}.json")
    if not os.path.isfile(meta_path):
        print("No existe la ficha del documento", file=sys.stderr)
        return 1
    meta = json.loads(open(meta_path, encoding="utf-8").read())
    pdf = os.path.join(DOCS, meta["archivo"])
    txt_path = os.path.join(DOCS, meta["texto"])
    if not os.path.exists(txt_path + ".antes-ocr"):
        with open(txt_path, "rb") as origen, open(txt_path + ".antes-ocr", "wb") as copia:
            copia.write(origen.read())

    sys.path.insert(0, BASE)
    import server as S
    paginas_originales = open(txt_path, encoding="utf-8", errors="replace").read().split("\f")
    objetivo = [i for i, p in enumerate(paginas_originales, 1)
                if not S.is_legible_text(S.clean_text(p))]
    if args.solo:
        a, b = (args.solo.split("-") + [args.solo])[:2]
        rango = set(range(int(a), int(b) + 1))
        objetivo = [p for p in objetivo if p in rango]

    jsonl = os.path.join(DOCS, f"{args.doc_id}.ocr.jsonl")
    hechas = {}
    if os.path.exists(jsonl):
        with open(jsonl, encoding="utf-8") as f:
            for linea in f:
                try:
                    reg = json.loads(linea)
                    hechas[reg["pagina"]] = reg["texto"]
                except Exception:
                    pass
    pendientes = [p for p in objetivo if p not in hechas]
    log(args.doc_id, f"OCR {args.doc_id}: {len(objetivo)} páginas ilegibles, "
                     f"{len(hechas)} ya hechas, {len(pendientes)} pendientes, "
                     f"{args.workers} trabajadores")
    if not pendientes:
        log(args.doc_id, "Nada pendiente.")
        return 0

    grupos = tramos(pendientes)
    inicio, hechas_previas, pend = time.time(), len(hechas), len(pendientes)
    contador_desde_rebuild = 0
    ultimo_registro = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool, \
            open(jsonl, "a", encoding="utf-8") as registro:
        for resultado in pool.map(_ocr_tramo, [(g, pdf) for g in grupos]):
            for pagina, texto in resultado.items():
                hechas[pagina] = texto
                registro.write(json.dumps({"pagina": pagina, "texto": texto},
                                           ensure_ascii=False) + "\n")
                contador_desde_rebuild += 1
            registro.flush()
            if contador_desde_rebuild >= args.cada:
                reconstruir(txt_path, paginas_originales, hechas)
                contador_desde_rebuild = 0
            completadas = len(hechas) - hechas_previas
            if completadas - ultimo_registro >= 50:
                ultimo_registro = completadas
                transcurrido = time.time() - inicio
                restante = (pend - completadas) * transcurrido / max(completadas, 1)
                log(args.doc_id, f"progreso {completadas}/{pend} "
                                 f"({100 * completadas // max(pend, 1)}%) · "
                                 f"restan ~{restante / 60:.0f} min")

    reconstruir(txt_path, paginas_originales, hechas)
    log(args.doc_id, f"Texto reconstruido ({sum(1 for _ in hechas)} páginas OCR). "
                     "Refrescando ficha…")
    calidad, refs = refrescar_ficha(args.doc_id, len(hechas))
    log(args.doc_id, f"Listo. calidad_extraccion={calidad} · referencias={refs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
