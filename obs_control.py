"""Control de OBS por obs-websocket 5.x.

Solo lo usa el predicador desde la vista de Inicio. El password de OBS se
lee aqui, en el servidor, y NUNCA se envia al navegador: el frontend solo
recibe el estado (si esta transmitiendo, la escena activa y la lista de
escenas).

Si OBS esta cerrado, el websocket apagado o falta el modulo websocket-client,
todo falla con un mensaje claro en vez de romper la app.
"""
import base64
import hashlib
import json
import threading
import time
from pathlib import Path

# OBS se instalo como Flatpak, asi que su config vive en ~/.var/app/... Dejamos
# la ruta normal como segundo intento por si algun dia se instala de otra forma.
CONFIG_OBS = [
    Path.home() / ".var/app/com.obsproject.Studio/config/obs-studio"
    / "plugin_config/obs-websocket/config.json",
    Path.home() / ".config/obs-studio/plugin_config/obs-websocket/config.json",
]

# Se abre una conexion por peticion (son pocas y el coste es bajo). El lock evita
# que dos clics a la vez abran conexiones cruzadas.
_candado = threading.Lock()

# El estado se cachea 2 s: la interfaz lo consulta cada pocos segundos y no
# tiene sentido abrir un socket nuevo en cada refresco.
_cache = {"datos": None, "cuando": 0.0}
CACHE_SEGUNDOS = 2.0


class ObsNoDisponible(Exception):
    """OBS no responde, o algo impide controlarlo. El mensaje va al usuario."""


def _config():
    """Devuelve la config del websocket si esta habilitado, o None."""
    for ruta in CONFIG_OBS:
        if not ruta.is_file():
            continue
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if datos.get("server_enabled") and datos.get("server_password"):
            return datos
    return None


def _conectar():
    """Abre y autentica una conexion con el websocket de OBS."""
    datos = _config()
    if not datos:
        raise ObsNoDisponible(
            "El control de OBS esta apagado. En OBS ve a Herramientas ▸ "
            "WebSocket Server y activalo.")

    try:
        import websocket
    except ImportError:
        raise ObsNoDisponible(
            "A Python le falta el modulo websocket-client, necesario para "
            "controlar OBS.")

    try:
        ws = websocket.create_connection(
            "ws://127.0.0.1:%d" % datos.get("server_port", 4455), timeout=4)
    except Exception as exc:
        raise ObsNoDisponible(
            "No se pudo conectar con OBS. Revisa que OBS este abierto. (%s)"
            % type(exc).__name__)

    try:
        # obs-websocket 5.x no acepta el password tal cual: hay que responderle
        # con un hash de su desafio.
        hola = json.loads(ws.recv())
        if hola.get("op") != 0:
            raise ObsNoDisponible("OBS no respondio como se espera.")
        reto = hola["d"]["authentication"]
        secreto = base64.b64encode(
            hashlib.sha256((datos["server_password"] + reto["salt"]).encode())
            .digest()).decode()
        respuesta = base64.b64encode(
            hashlib.sha256((secreto + reto["challenge"]).encode()).digest()
        ).decode()
        ws.send(json.dumps({
            "op": 1,
            "d": {"rpcVersion": 1, "authentication": respuesta,
                  "eventSubscriptions": 0},
        }))
        if json.loads(ws.recv()).get("op") != 2:
            raise ObsNoDisponible("El password de OBS no coincide.")
    except ObsNoDisponible:
        ws.close()
        raise
    except Exception:
        ws.close()
        raise ObsNoDisponible("No se pudo autenticar con OBS.")
    return ws


def _pedir(nombre, datos=None):
    """Envia un request a OBS y devuelve su responseData."""
    with _candado:
        ws = _conectar()
        try:
            ws.send(json.dumps({
                "op": 6,
                "d": {"requestType": nombre, "requestId": "me",
                      "requestData": datos or {}},
            }))
            while True:
                crudo = ws.recv()
                if not crudo:
                    raise ObsNoDisponible("OBS cerro la conexion.")
                if isinstance(crudo, bytes):
                    crudo = crudo.decode("utf-8", "replace")
                mensaje = json.loads(crudo)
                if mensaje.get("op") != 7:
                    continue  # un evento, no nuestra respuesta
                cuerpo = mensaje.get("d", {})
                if cuerpo.get("requestId") != "me":
                    continue
                estado = cuerpo.get("requestStatus", {})
                if estado.get("result") is False:
                    raise ObsNoDisponible(
                        estado.get("comment") or "OBS rechazo la peticion.")
                return cuerpo.get("responseData", {})
        except ObsNoDisponible:
            raise
        except Exception as exc:
            raise ObsNoDisponible("Fallo la comunicacion con OBS. (%s)"
                                  % type(exc).__name__)
        finally:
            try:
                ws.close()
            except Exception:
                pass


def _lectura(nombre, defecto=None):
    """Como _pedir, pero un request que falle no tumba todo el estado."""
    try:
        return _pedir(nombre)
    except ObsNoDisponible:
        if defecto is None:
            raise
        return defecto


def estado(forzar=False):
    """Estado de OBS para la interfaz. Nunca lanza: devuelve {'conectado': False}."""
    ahora = time.time()
    if (not forzar and _cache["datos"] is not None
            and ahora - _cache["datos"]["_ts"] < CACHE_SEGUNDOS):
        return {k: v for k, v in _cache["datos"].items() if k != "_ts"}

    try:
        escenas = _pedir("GetSceneList")
        transmision = _lectura("GetStreamStatus", {})
        grabacion = _lectura("GetRecordStatus", {})
    except ObsNoDisponible as exc:
        return {"conectado": False, "motivo": str(exc)}

    datos = {
        "conectado": True,
        "transmitiendo": bool(transmision.get("outputActive")),
        "reconectando": bool(transmision.get("outputReconnecting")),
        "estado_transmision": transmision.get("outputStatus") or "",
        "grabando": bool(grabacion.get("outputActive")),
        "grabacion_pausada": bool(grabacion.get("outputPaused")),
        "escena": escenas.get("currentProgramSceneName", ""),
        "escenas": [e.get("sceneName") for e in escenas.get("scenes", [])
                    if e.get("sceneName")],
        "_ts": ahora,
    }
    _cache["datos"] = datos
    return {k: v for k, v in datos.items() if k != "_ts"}


def _alternar(activo, iniciar, detener):
    """Arranca o para la salida indicada, segun este activa o no."""
    if activo:
        _pedir(detener)
        return "detenido"
    _pedir(iniciar)
    return "iniciado"


def transmision(accion=None):
    """'iniciar'/'detener' explicito, o alternar si no se indica."""
    actual = estado(forzar=True)
    if not actual.get("conectado"):
        raise ObsNoDisponible(actual.get("motivo", "OBS no disponible."))
    if accion not in ("iniciar", "detener"):
        return _alternar(actual["transmitiendo"], "StartStream", "StopStream"), actual
    pedido = "StartStream" if accion == "iniciar" else "StopStream"
    _pedir(pedido)
    return ("iniciado" if accion == "iniciar" else "detenido"), estado(forzar=True)


def grabacion(accion=None):
    """Igual que transmision() pero para la grabacion local."""
    actual = estado(forzar=True)
    if not actual.get("conectado"):
        raise ObsNoDisponible(actual.get("motivo", "OBS no disponible."))
    if accion not in ("iniciar", "detener"):
        return _alternar(actual["grabando"], "StartRecord", "StopRecord"), actual
    pedido = "StartRecord" if accion == "iniciar" else "StopRecord"
    _pedir(pedido)
    return ("iniciado" if accion == "iniciar" else "detenido"), estado(forzar=True)


def cambiar_escena(nombre):
    """Cambia la escena del programa. Devuelve el estado nuevo."""
    if not nombre:
        raise ObsNoDisponible("No se indico que escena cambiar.")
    try:
        _pedir("SetCurrentProgramScene", {"sceneName": nombre})
    except ObsNoDisponible as exc:
        # OBS contesta en ingles; al predicador le sirve mas saber que paso.
        raise ObsNoDisponible("No se pudo cambiar a la escena '%s'. %s"
                              % (nombre, exc))
    return estado(forzar=True)
