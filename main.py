
import csv
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

BASE = "https://ligadelaamistadleon.es/"
COMPETICION = urljoin(
    BASE, "competicion/?competition_id=2&season_id=1"
)
SALIDA = Path("resultados")
SALIDA.mkdir(exist_ok=True)

SESION = requests.Session()
SESION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; LigaAmistadBot/1.0)"
})


def leer_pagina(url):
    respuesta = SESION.get(url, timeout=30)
    respuesta.raise_for_status()
    respuesta.encoding = respuesta.apparent_encoding
    return BeautifulSoup(respuesta.text, "html.parser")


def limpio(elemento):
    return " ".join(elemento.stripped_strings)


def guardar(nombre, filas, columnas):
    with (SALIDA / nombre).open(
        "w", newline="", encoding="utf-8-sig"
    ) as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=columnas, extrasaction="ignore"
        )
        escritor.writeheader()
        escritor.writerows(filas)


def enlaces_partidos(pagina):
    encontrados = set()

    for a in pagina.find_all("a", href=True):
        url = urljoin(BASE, a["href"])
        ruta = urlparse(url)

        if "/partido/" not in ruta.path:
            continue

        parametros = parse_qs(ruta.query)
        if parametros.get("competicion", [""])[0] != "2":
            continue

        if parametros.get("match_id") or parametros.get("partido"):
            encontrados.add(url)

    return encontrados


def texto_jugador(celda):
    # Los nombres pueden estar en el atributo alt de una imagen.
    imagenes = celda.find_all("img", alt=True)
    for imagen in imagenes:
        nombre = imagen.get("alt", "").strip()
        if nombre:
            return nombre

    return limpio(celda)


def contar_acciones(acciones, emoji):
    coincidencias = re.findall(
        re.escape(emoji) + r"\s*(\d*)", acciones
    )
    return sum(int(n) if n else 1 for n in coincidencias)


def extraer_partido(url):
    pagina = leer_pagina(url)
    contenido = limpio(pagina)
    parametros = parse_qs(urlparse(url).query)
    id_partido = (
        parametros.get("match_id", [""])[0]
        or parametros.get("partido", [""])[0]
    )

    jornada = ""
    fecha = ""
    competicion = re.search(
        r"Segunda división\s+Jornada\s+(\d+)\s+"
        r"(\d{2}/\d{2}/\d{4})",
        contenido,
        re.IGNORECASE
    )
    if competicion:
        jornada, fecha = competicion.groups()

    # No buscar marcadores en toda la página: primero se limita
    # la búsqueda al encabezado, antes de la convocatoria.
    encabezado = re.split(
        r"CONVOCATORIA", contenido, maxsplit=1, flags=re.IGNORECASE
    )[0]

    goles_local = ""
    goles_visitante = ""
    marcador = ""

    # La ficha del partido suele mostrar el resultado en su cabecera.
    # Solo se acepta un resultado si hay un marcador antes de la
    # sección de convocatoria.
    resultado = re.search(
        r"(?<!\d)(\d{1,2})\s*-\s*(\d{1,2})(?!\d)",
        encabezado
    )
    if resultado:
        goles_local, goles_visitante = resultado.groups()
        marcador = f"{goles_local}-{goles_visitante}"

    equipos = []
    for imagen in pagina.find_all("img", alt=True):
        nombre = imagen.get("alt", "").strip()
        if nombre and nombre not in equipos:
            equipos.append(nombre)

    local = equipos[0] if len(equipos) > 0 else ""
    visitante = equipos[1] if len(equipos) > 1 else ""

    partido = {
        "id_partido": id_partido,
        "jornada": jornada,
        "fecha": fecha,
        "local": local,
        "visitante": visitante,
        "marcador": marcador,
        "goles_local": goles_local,
        "goles_visitante": goles_visitante,
        "url": url,
        "revisar": "SI" if not marcador else ""
    }

    jugadores = []

    for tabla in pagina.find_all("table"):
        cabecera = limpio(tabla).upper()
        if "JUGADOR" not in cabecera or "ACCIONES" not in cabecera:
            continue

        equipo = ""
        titulo = tabla.find_previous(["h2", "h3", "h4"])
        if titulo:
            equipo = limpio(titulo)

        for fila in tabla.find_all("tr"):
            celdas = fila.find_all(["td", "th"])
            if len(celdas) < 4:
                continue

            valores = [limpio(c) for c in celdas]
            if "JUGADOR" in " ".join(valores).upper():
                continue

            nombre = texto_jugador(celdas[2])
            acciones = limpio(celdas[-1])

            if not nombre or nombre in ("—", "-"):
                continue

            jugadores.append({
                "id_partido": id_partido,
                "jornada": jornada,
                "fecha": fecha,
                "equipo": equipo,
                "jugador": nombre,
                "goles": contar_acciones(acciones, "⚽"),
                "amarillas": contar_acciones(acciones, "🟨"),
                "rojas": contar_acciones(acciones, "🟥"),
                "acciones_originales": acciones,
                "partido_url": url
            })

    return partido, jugadores


def main():
    partidos_por_id = {}
    jugadores_por_clave = {}
    errores = []

    print("Buscando partidos de Segunda División...")

    # Consultar jornadas por separado permite encontrar partidos
    # que no aparezcan enlazados en la portada.
    for jornada in range(1, 31):
        url_jornada = (
            f"{BASE}competicion/"
            f"?competition_id=2&jornada={jornada}&season_id=1"
        )
        try:
            pagina = leer_pagina(url_jornada)
            urls = enlaces_partidos(pagina)
            print(f"Jornada {jornada}: {len(urls)} enlaces")

            for url in urls:
                clave = (
                    parse_qs(urlparse(url).query)
                    .get("match_id", [url])[0]
                )
                if clave in partidos_por_id:
                    continue

                try:
                    partido, jugadores = extraer_partido(url)
                    partidos_por_id[clave] = partido

                    for jugador in jugadores:
                        llave = (
                            jugador["id_partido"],
                            jugador["equipo"],
                            jugador["jugador"]
                        )
                        jugadores_por_clave[llave] = jugador

                    time.sleep(1)

                except Exception as error:
                    errores.append({
                        "url": url,
                        "error": str(error)
                    })
                    print(f"Error al leer partido: {url}: {error}")

        except Exception as error:
            errores.append({
                "url": url_jornada,
                "error": str(error)
            })
            print(f"Error en jornada {jornada}: {error}")

    partidos = list(partidos_por_id.values())
    jugadores = list(jugadores_por_clave.values())

    guardar(
        "partidos.csv", partidos,
        [
            "id_partido", "jornada", "fecha", "local", "visitante",
            "marcador", "goles_local", "goles_visitante", "url", "revisar"
        ]
    )
    guardar(
        "jugadores.csv", jugadores,
        [
            "id_partido", "jornada", "fecha", "equipo", "jugador",
            "goles", "amarillas", "rojas", "acciones_originales",
            "partido_url"
        ]
    )
    guardar("errores.csv", errores, ["url", "error"])

    pendientes = sum(1 for p in partidos if p["revisar"] == "SI")

    print("\nProceso terminado.")
    print(f"Partidos encontrados: {len(partidos)}")
    print(f"Jugadores registrados: {len(jugadores)}")
    print(f"Partidos pendientes de revisar: {pendientes}")
    print(f"Errores de lectura: {len(errores)}")
    print("Resultados guardados en la carpeta resultados/.")


if __name__ == "__main__":
    main()
