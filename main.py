
import csv
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://ligadelaamistadleon.es/"
OUTPUT = Path("resultados")
OUTPUT.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "LigaAmistadBot/1.0 (lector de resultados; contacto: usuario)"
}

def obtener_pagina(url):
    respuesta = requests.get(url, headers=HEADERS, timeout=25)
    respuesta.raise_for_status()
    return BeautifulSoup(respuesta.text, "html.parser")

def texto(elemento):
    return " ".join(elemento.stripped_strings)

def guardar_csv(ruta, filas, columnas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(filas)

def main():
    print("Leyendo la web oficial...")
    portada = obtener_pagina(BASE_URL)

    partidos = []
    vistos = set()

    # En la web, los partidos de Segunda División usan competicion=2.
    for enlace in portada.find_all("a", href=True):
        url = urljoin(BASE_URL, enlace["href"])
        if "/partido/" not in url or "competicion=2" not in url:
            continue
        if url in vistos:
            continue
        vistos.add(url)

        resumen = texto(enlace)
        if not resumen:
            continue

        partidos.append({
            "resumen_web": resumen,
            "url": url,
            "jornada": "",
            "fecha": "",
            "marcador": ""
        })

    jugadores = []
    errores = []

    for numero, partido in enumerate(partidos, start=1):
        print(f"Revisando partido {numero}/{len(partidos)}")
        try:
            pagina = obtener_pagina(partido["url"])
            contenido = texto(pagina)

            datos = re.search(
                r"Segunda división\s+Jornada\s+(\d+)\s+"
                r"(\d{2}/\d{2}/\d{4})",
                contenido,
                re.IGNORECASE
            )
            if datos:
                partido["jornada"] = datos.group(1)
                partido["fecha"] = datos.group(2)

        marcador = re.search(r"\b(\d+)\s+-\s+(\d+)\b", contenido)
            if marcador:
                partido["marcador"] = (
                    f"{marcador.group(1)}-{marcador.group(2)}"
                )

            # Leer las tablas de jugadores de la ficha del partido.
            for tabla in pagina.find_all("table"):
                cabecera = texto(tabla).upper()
                if "JUGADOR" not in cabecera or "ACCIONES" not in cabecera:
                    continue

                equipo = "Por identificar"
                anterior = tabla.find_previous(["h2", "h3", "h4"])
                if anterior:
                    equipo = texto(anterior)

                for fila in tabla.find_all("tr"):
                    celdas = fila.find_all(["td", "th"])
                    if len(celdas) < 3:
                        continue

                    valores = [texto(celda) for celda in celdas]
                    if "JUGADOR" in " ".join(valores).upper():
                        continue

                    nombre = valores[2] if len(valores) >= 3 else ""
                    acciones = valores[-1]

                    if not nombre or nombre in ("—", "-"):
                        continue

                    goles = sum(
                        int(n or 1)
                        for n in re.findall(r"⚽\s*(\d*)", acciones)
                    )
                    amarillas = sum(
                        int(n or 1)
                        for n in re.findall(r"🟨\s*(\d*)", acciones)
                    )
                    rojas = sum(
                        int(n or 1)
                        for n in re.findall(r"🟥\s*(\d*)", acciones)
                    )

                    jugadores.append({
                        "jugador": nombre,
                        "equipo": equipo,
                        "goles": goles,
                        "tarjetas_amarillas": amarillas,
                        "tarjetas_rojas": rojas,
                        "partido_url": partido["url"],
                        "acciones_web": acciones
                    })

            time.sleep(1)  # Evitar hacer peticiones demasiado seguidas.

        except Exception as error:
            errores.append({
                "url": partido["url"],
                "error": str(error)
            })
            print(f"AVISO: no se pudo leer {partido['url']}: {error}")

    guardar_csv(
        OUTPUT / "partidos.csv",
        partidos,
        ["resumen_web", "url", "jornada", "fecha", "marcador"]
    )
    guardar_csv(
        OUTPUT / "jugadores.csv",
        jugadores,
        [
            "jugador", "equipo", "goles", "tarjetas_amarillas",
            "tarjetas_rojas", "partido_url", "acciones_web"
        ]
    )
    guardar_csv(
        OUTPUT / "errores.csv",
        errores,
        ["url", "error"]
    )

    print("\nProceso terminado.")
    print(f"Partidos encontrados: {len(partidos)}")
    print(f"Registros de jugadores: {len(jugadores)}")
    print("Archivos creados en la carpeta resultados/")
    print("Importante: revisa los CSV antes de usar los datos.")

if __name__ == "__main__":
    main()
