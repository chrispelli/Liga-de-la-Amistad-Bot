
import csv
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup, NavigableString


BASE = "https://ligadelaamistadleon.es/"
COMPETICION = 2
TEMPORADA = 1
JORNADAS = 30

CARPETA = Path("resultados")
CARPETA.mkdir(exist_ok=True)

SESION = requests.Session()
SESION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; LigaAmistadBot/1.0)"
})


def reparar_texto(valor):
    """Intenta corregir caracteres UTF-8 interpretados incorrectamente."""
    if not valor:
        return ""

    indicadores = ("Ã", "Â", "â€", "âš", "ðŸ")

    if not any(indicador in valor for indicador in indicadores):
        return valor

    for codificacion in ("cp1252", "latin1"):
        try:
            reparado = valor.encode(codificacion).decode("utf-8")

            errores_originales = sum(
                valor.count(indicador) for indicador in indicadores
            )
            errores_reparados = sum(
                reparado.count(indicador) for indicador in indicadores
            )

            if errores_reparados < errores_originales:
                return reparado

        except (UnicodeEncodeError, UnicodeDecodeError):
            pass

    return valor


def obtener_pagina(url):
    """Descarga la página y analiza su HTML."""
    respuesta = SESION.get(url, timeout=30)
    respuesta.raise_for_status()

    # Respeta la codificación declarada por la página cuando exista.
    if not respuesta.encoding or respuesta.encoding.lower() == "iso-8859-1":
        respuesta.encoding = respuesta.apparent_encoding or "utf-8"

    return BeautifulSoup(respuesta.content, "html.parser")


def texto(elemento):
    """Extrae texto y corrige posibles errores de codificación."""
    contenido = elemento.get_text(" ", strip=True)
    return reparar_texto(contenido)


def texto_acciones(celda):
    """Extrae texto, alt y title de los iconos de acciones."""
    partes = []

    for nodo in celda.descendants:
        if getattr(nodo, "name", None) == "img":
            partes.append(nodo.get("alt", ""))
            partes.append(nodo.get("title", ""))

        elif isinstance(nodo, NavigableString):
            partes.append(str(nodo))

    resultado = " ".join(parte for parte in partes if parte)
    return reparar_texto(resultado)


def normalizar_acciones(acciones):
    acciones = reparar_texto(acciones)

    return (
        acciones
        .replace("\ufe0f", "")
        .replace("\ufe0e", "")
        .replace("\u200d", "")
    )


def contar_acciones(acciones, emoji):
    """Cuenta goles o tarjetas, respetando el número junto al icono."""
    acciones = normalizar_acciones(acciones)

    patron = re.escape(emoji) + r"\s*(\d*)"
    coincidencias = re.findall(patron, acciones)

    return sum(int(numero) if numero else 1 for numero in coincidencias)


def conseguir_id_partido(url):
    consulta = parse_qs(urlparse(url).query)

    return (
        consulta.get("match_id", [None])[0]
        or consulta.get("partido", [None])[0]
    )


def conseguir_enlaces_partidos(sopa):
    enlaces = {}

    for enlace in sopa.find_all("a", href=True):
        href = enlace["href"]

        if "match_id=" not in href and "partido=" not in href:
            continue

        url = urljoin(BASE, href)

        if "competition_id=2" not in url and "competicion=2" not in url:
            continue

        partido_id = conseguir_id_partido(url)

        if partido_id:
            enlaces[partido_id] = url

    return enlaces


def obtener_jornada():
    partidos = {}

    for jornada in range(1, JORNADAS + 1):
        url = (
            f"{BASE}competicion/"
            f"?competition_id={COMPETICION}"
            f"&jornada={jornada}"
            f"&season_id={TEMPORADA}"
        )

        print(f"Consultando jornada {jornada}...")

        try:
            sopa = obtener_pagina(url)
            enlaces = conseguir_enlaces_partidos(sopa)

            for partido_id, partido_url in enlaces.items():
                partidos[partido_id] = {
                    "jornada": jornada,
                    "url": partido_url
                }

        except Exception as error:
            print(f"Error en jornada {jornada}: {error}")

        time.sleep(0.5)

    return partidos


def extraer_equipos(sopa):
    """Busca los nombres de los equipos en los textos alt de imágenes."""
    equipos = []

    for imagen in sopa.find_all("img", alt=True):
        nombre = reparar_texto(imagen.get("alt", "").strip())

        if not nombre:
            continue

        nombre_limpio = nombre.lower()

        if any(palabra in nombre_limpio for palabra in (
            "logo", "escudo", "imagen", "liga de la amistad"
        )):
            continue

        if nombre not in equipos:
            equipos.append(nombre)

        if len(equipos) == 2:
            break

    local = equipos[0] if len(equipos) > 0 else ""
    visitante = equipos[1] if len(equipos) > 1 else ""

    return local, visitante


def extraer_marcador(sopa):
    contenido = texto(sopa)

    antes_convocatoria = re.split(
        r"CONVOCATORIA",
        contenido,
        maxsplit=1,
        flags=re.IGNORECASE
    )[0]

    coincidencia = re.search(
        r"\b(\d+)\s+[-–]\s+(\d+)\b",
        antes_convocatoria
    )

    if coincidencia:
        return int(coincidencia.group(1)), int(coincidencia.group(2))

    return "", ""


def extraer_fecha(sopa):
    contenido = texto(sopa)

    coincidencia = re.search(
        r"\b(\d{2}/\d{2}/\d{4})\b",
        contenido
    )

    return coincidencia.group(1) if coincidencia else ""


def extraer_jugadores(sopa, partido_id, jornada, fecha, partido_url):
    jugadores = []

    for tabla in sopa.find_all("table"):
        contenido_tabla = texto(tabla).upper()

        if "JUGADOR" not in contenido_tabla:
            continue

        if "ACCIONES" not in contenido_tabla:
            continue

        anterior = tabla.find_previous(["h1", "h2", "h3", "h4"])
        equipo_actual = texto(anterior) if anterior else ""

        for fila in tabla.find_all("tr"):
            celdas = fila.find_all(["td", "th"])

            if len(celdas) < 3:
                continue

            valores = [texto(celda) for celda in celdas]

            if any("JUGADOR" in valor.upper() for valor in valores):
                continue

            if any("ACCIONES" in valor.upper() for valor in valores):
                continue

            jugador = valores[2].strip()

            if not jugador:
                continue

            acciones = texto_acciones(celdas[-1])

            goles = contar_acciones(acciones, "⚽")
            amarillas = contar_acciones(acciones, "🟨")
            rojas = contar_acciones(acciones, "🟥")

            jugadores.append({
                "id_partido": partido_id,
                "jornada": jornada,
                "fecha": fecha,
                "equipo": equipo_actual,
                "jugador": jugador,
                "goles": goles,
                "amarillas": amarillas,
                "rojas": rojas,
                "acciones_originales": acciones,
                "partido_url": partido_url
            })

    return jugadores


def procesar_partido(partido_id, jornada, partido_url):
    print(f"Procesando partido {partido_id}...")

    sopa = obtener_pagina(partido_url)

    local, visitante = extraer_equipos(sopa)
    goles_local, goles_visitante = extraer_marcador(sopa)
    fecha = extraer_fecha(sopa)

    marcador = ""

    if goles_local != "" and goles_visitante != "":
        marcador = f"{goles_local}-{goles_visitante}"

    revisar = "NO"

    if marcador == "" or local == "" or visitante == "":
        revisar = "SI"

    partido = {
        "id_partido": partido_id,
        "jornada": jornada,
        "fecha": fecha,
        "local": local,
        "visitante": visitante,
        "marcador": marcador,
        "goles_local": goles_local,
        "goles_visitante": goles_visitante,
        "url": partido_url,
        "revisar": revisar
    }

    jugadores = extraer_jugadores(
        sopa,
        partido_id,
        jornada,
        fecha,
        partido_url
    )

    return partido, jugadores


def guardar_csv(nombre_archivo, columnas, filas):
    ruta = CARPETA / nombre_archivo

    with open(ruta, "w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(
            archivo,
            fieldnames=columnas,
            extrasaction="ignore"
        )

        escritor.writeheader()
        escritor.writerows(filas)

    print(f"Archivo creado: {ruta}")


def main():
    print("===================================")
    print(" BOT LIGA DE LA AMISTAD DE LEÓN")
    print(" SEGUNDA DIVISIÓN")
    print("===================================")

    partidos_encontrados = obtener_jornada()

    partidos_resultado = []
    jugadores_resultado = []
    errores = []

    for partido_id, datos in partidos_encontrados.items():
        try:
            partido, jugadores = procesar_partido(
                partido_id,
                datos["jornada"],
                datos["url"]
            )

            partidos_resultado.append(partido)
            jugadores_resultado.extend(jugadores)

        except Exception as error:
            print(f"Error en partido {partido_id}: {error}")

            errores.append({
                "id_partido": partido_id,
                "url": datos["url"],
                "error": str(error)
            })

        time.sleep(0.5)

    jugadores_unicos = {}

    for jugador in jugadores_resultado:
        clave = (
            jugador["id_partido"],
            jugador["equipo"],
            jugador["jugador"]
        )

        jugadores_unicos[clave] = jugador

    jugadores_resultado = list(jugadores_unicos.values())

    guardar_csv(
        "partidos.csv",
        [
            "id_partido",
            "jornada",
            "fecha",
            "local",
            "visitante",
            "marcador",
            "goles_local",
            "goles_visitante",
            "url",
            "revisar"
        ],
        partidos_resultado
    )

    guardar_csv(
        "jugadores.csv",
        [
            "id_partido",
            "jornada",
            "fecha",
            "equipo",
            "jugador",
            "goles",
            "amarillas",
            "rojas",
            "acciones_originales",
            "partido_url"
        ],
        jugadores_resultado
    )

    guardar_csv(
        "errores.csv",
        ["id_partido", "url", "error"],
        errores
    )

    print("-----------------------------------")
    print(f"Partidos encontrados: {len(partidos_resultado)}")
    print(f"Jugadores registrados: {len(jugadores_resultado)}")
    print(f"Errores: {len(errores)}")
    print("Proceso terminado.")
    print("-----------------------------------")


if __name__ == "__main__":
    main()
