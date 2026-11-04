
import csv
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup


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


def obtener_pagina(url):
    """Descarga el HTML y lo interpreta expresamente como UTF-8."""
    respuesta = SESION.get(url, timeout=30)
    respuesta.raise_for_status()

    html = respuesta.content.decode("utf-8", errors="replace")
    return BeautifulSoup(html, "html.parser")


def texto(elemento):
    return elemento.get_text(" ", strip=True)


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
    """Obtiene los equipos desde los encabezados del partido."""
    equipos = []

    for encabezado in sopa.find_all(["h2", "h3"]):
        nombre = texto(encabezado).strip()

        if nombre and nombre not in equipos:
            equipos.append(nombre)

    if len(equipos) >= 2:
        return equipos[0], equipos[1]

    # Alternativa: nombres de los escudos.
    equipos = []

    for imagen in sopa.find_all("img", alt=True):
        nombre = imagen.get("alt", "").strip()

        if nombre and nombre not in equipos:
            equipos.append(nombre)

        if len(equipos) == 2:
            break

    return (
        equipos[0] if equipos else "",
        equipos[1] if len(equipos) > 1 else ""
    )


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


def obtener_nombre_jugador(celda):
    """
    Prioriza el atributo alt de la imagen del jugador,
    que contiene el nombre completo publicado por la liga.
    """
    imagen = celda.find("img", alt=True)

    if imagen:
        nombre = imagen.get("alt", "").strip()
        if nombre:
            return nombre

    return texto(celda).strip()


def extraer_acciones(celda):
    """Lee las acciones publicadas en la última celda."""
    return texto(celda)


def contar_acciones(acciones, emoji):
    """Cuenta los iconos y sus cantidades."""
    acciones = (
        acciones
        .replace("\ufe0f", "")
        .replace("\ufe0e", "")
        .replace("\u200d", "")
    )

    patron = re.escape(emoji) + r"\s*(\d*)"
    coincidencias = re.findall(patron, acciones)

    return sum(int(numero) if numero else 1 for numero in coincidencias)


def descripcion_acciones(goles, amarillas, rojas):
    """Devuelve acciones en texto normal, sin emojis."""
    partes = []

    if goles:
        partes.append(f"Goles: {goles}")

    if amarillas:
        partes.append(f"Amarillas: {amarillas}")

    if rojas:
        partes.append(f"Rojas: {rojas}")

    return "; ".join(partes) if partes else "Sin acciones"


def extraer_jugadores(sopa, partido_id, jornada, fecha, partido_url):
    jugadores = []

    for tabla in sopa.find_all("table"):
        cabecera = texto(tabla).upper()

        if "JUGADOR" not in cabecera or "ACCIONES" not in cabecera:
            continue

        encabezado = tabla.find_previous(["h2", "h3", "h4"])
        equipo_actual = texto(encabezado) if encabezado else ""

        for fila in tabla.find_all("tr"):
            celdas = fila.find_all(["td", "th"])

            if len(celdas) < 4:
                continue

            valores = [texto(celda).upper() for celda in celdas]

            if any("JUGADOR" in valor for valor in valores):
                continue

            if any("ACCIONES" in valor for valor in valores):
                continue

            jugador = obtener_nombre_jugador(celdas[2])

            if not jugador or jugador == "—":
                continue

            acciones = extraer_acciones(celdas[-1])

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
                "acciones_originales": descripcion_acciones(
                    goles, amarillas, rojas
                ),
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
