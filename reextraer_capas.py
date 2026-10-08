#!/usr/bin/env python3
"""Quita las capas duplicadas del texto extraído de un PDF.

Este PDF guarda el mismo texto unas 22 veces por página, así que `pdftotext -raw`
entrega 27 MB de texto con fragmentos basura intercalados (los análisis tardan
mucho y salen con palabras sueltas). Acá se limpia página por página: se conserva
cada línea una sola vez y se descartan los restos de las capas ocultas.

La paginación es la de `pdftotext` (verificada contra el render de la página),
que es correcta; `pdftohtml` se probó y repite/omite páginas con este archivo.

Uso:  python3 reextraer_capas.py 2d674f457e9a
"""
import json
import os
import re
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(BASE, "data", "documentos")


def limpiar_pagina(texto):
    """Una sola copia del texto de la página, sin restos de capas ocultas."""
    salida, vistas = [], set()
    for linea in texto.split("\n"):
        linea = re.sub(r"\s+", " ", linea).strip()
        if not linea:
            continue
        clave = linea.casefold()
        if clave in vistas:
            continue                      # la ~22 capas repiten la misma línea
        letras = re.findall(r"[a-záéíóúüñ]", clave)
        palabras = re.findall(r"[a-záéíóúüñ]+", clave)
        if len(letras) < 12:
            continue                      # restos tipo "1 3 1", "a s"
        if not palabras or max(len(p) for p in palabras) <= 3:
            continue                      # letras sueltas: "pro lo Dio sal rec"
        vistas.add(clave)
        salida.append(linea)
    # Las líneas vienen cortadas por el ancho de columna: se reagrupan en
    # párrafos (una línea que termina en punto y la siguiente en mayúscula
    # empieza otro).
    partes, actual = [], []
    for linea in salida:
        if actual and re.search(r"[.!?»:”…]\s*$", actual[-1]) and \
                re.match(r"[A-ZÁÉÍÓÚÜÑ¿\"«¡—“]", linea):
            partes.append(" ".join(actual))
            actual = []
        actual.append(linea)
    if actual:
        partes.append(" ".join(actual))
    return "\n\n".join(partes)


def paginas_del_pdf(pdf):
    crudo = subprocess.run(["pdftotext", "-raw", pdf, "-"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace").stdout
    return crudo.split("\f")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    doc_id = sys.argv[1]
    meta_path = os.path.join(DOCS, f"{doc_id}.json")
    if not os.path.isfile(meta_path):
        print("No existe la ficha del documento", file=sys.stderr)
        return 1
    meta = json.loads(open(meta_path, encoding="utf-8").read())
    pdf = os.path.join(DOCS, meta["archivo"])
    txt = os.path.join(DOCS, meta["texto"])

    sys.path.insert(0, BASE)
    import server as S  # el arranque está bajo __main__: importar es seguro

    respaldo = f"{txt}.bak-capas"
    if not os.path.isfile(respaldo):
        os.replace(txt, respaldo)         # el original con las ~22 capas
        print(f"respaldo: {os.path.basename(respaldo)}", flush=True)

    fd, tmp = tempfile.mkstemp(prefix=f".{doc_id}-", suffix=".tmp", dir=DOCS)
    os.close(fd)
    paginas_crudas = paginas_del_pdf(pdf)
    if paginas_crudas and not paginas_crudas[-1].strip():
        paginas_crudas.pop()              # sobra el \f final que agrega pdftotext
    limpia, legibles = [], 0
    try:
        for i, cruda in enumerate(paginas_crudas, 1):
            cuerpo = limpiar_pagina(cruda)
            limpia.append(cuerpo)
            if cuerpo and S.is_legible_text(S.clean_text(cuerpo)):
                legibles += 1
            if i % 300 == 0:
                print(f"  {i} páginas…", flush=True)
        with open(tmp, "w", encoding="utf-8") as out:
            out.write("\f".join(limpia))
        os.replace(tmp, txt)
        os.chmod(txt, 0o644)
    finally:
        if os.path.isfile(tmp):
            os.remove(tmp)
    paginas = len(limpia)

    raw = open(txt, encoding="utf-8", errors="replace").read()
    meta["analisis"] = S.analyze_document(S.clean_text(raw))
    meta["analisis"]["refs_v"] = 3
    meta["texto_paginas"] = paginas
    meta = S.classify_document_meta(meta)
    meta["extraccion_capas"] = {
        "herramienta": "pdftotext -raw + dedupe de capas por línea",
        "paginas": paginas, "legibles": legibles,
        "respaldo": os.path.basename(respaldo),
        "terminado": S.datetime_now(),
    }
    open(meta_path, "w", encoding="utf-8").write(
        json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"Listo. páginas={paginas} legibles={legibles} "
          f"calidad={meta.get('calidad_extraccion')} "
          f"refs={len(meta['analisis'].get('referencias') or [])} "
          f"tamaño={os.path.getsize(txt):,} B (antes {os.path.getsize(respaldo):,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
