"""
Monitor de prima de riesgo de la zona euro
==========================================

Calcula la prima de riesgo (diferencial frente al Bund alemán a 10 años) de
Italia, Francia, España, Portugal y Grecia a partir de la API pública del BCE
y la guarda en un archivo JSON que consume el widget (docs/data.json).

Pasos del script:
    1. Obtención de datos   -> descargar_datos()
    2. Limpieza             -> limpiar_datos()
    3. Cálculo del indicador-> calcular_indicador()
    4. Preparación para API -> exportar_json()

Uso:
    python src/prima_riesgo.py                 # descarga de la API del BCE
    python src/prima_riesgo.py --csv datos.csv # usa un CSV guardado (pruebas sin conexión)
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

# Serie del BCE: "Harmonised long-term interest rates for convergence assessment
# purposes" (dataset IRS). Rendimiento medio mensual del bono soberano a 10 años.
# Clave: IRS.M.<PAÍS>.L.L40.CI.0000.EUR.N.Z
URL_API_BCE = (
    "https://data-api.ecb.europa.eu/service/data/IRS/"
    "M.{paises}.L.L40.CI.0000.EUR.N.Z"
)
FECHA_INICIO = "2007-01"  # incluye la crisis financiera y la crisis del euro

REFERENCIA = "DE"  # Bund alemán, el activo sin riesgo de la zona euro
PAISES = {
    "IT": "Italia",
    "FR": "Francia",
    "ES": "España",
    "PT": "Portugal",
    "GR": "Grecia",
}

# Umbrales del semáforo, en puntos básicos (pb).
# Se basan en episodios históricos: por debajo de 100 pb el mercado considera
# el riesgo bajo; entre 100 y 200 pb hay tensión; por encima de 200 pb el
# mercado exige una prima propia de un país en dificultades (Italia 2018,
# 2020 y 2022) y por encima de 400 pb, de crisis (2011-2012).
UMBRALES = [
    (100, "bajo", "Riesgo bajo"),
    (200, "moderado", "Tensión moderada"),
    (400, "alto", "Riesgo alto"),
    (float("inf"), "crisis", "Crisis"),
]

# Percentil a partir del cual el diferencial se considera "en máximos" respecto
# a la propia historia del país, aunque el nivel absoluto sea bajo.
PERCENTIL_MAXIMOS = 90

# Una subida de más de 50 pb en 3 meses se marca como alerta de tensión,
# aunque el nivel todavía sea bajo: el mercado está cambiando de opinión.
ALERTA_SUBIDA_3M = 50

RUTA_SALIDA = Path(__file__).resolve().parent.parent / "docs" / "data.json"


# ---------------------------------------------------------------------------
# 1. Obtención de datos
# ---------------------------------------------------------------------------

def descargar_datos(ruta_csv: str | None = None) -> pd.DataFrame:
    """Descarga los rendimientos a 10 años desde la API del BCE (formato CSV).

    Si se pasa ruta_csv, lee ese archivo en lugar de llamar a la API
    (útil para trabajar sin conexión).
    """
    if ruta_csv:
        print(f"Leyendo datos del archivo local {ruta_csv}")
        return pd.read_csv(ruta_csv)

    codigos = "+".join([REFERENCIA, *PAISES])
    url = URL_API_BCE.format(paises=codigos)
    parametros = {"format": "csvdata", "startPeriod": FECHA_INICIO}

    print(f"Descargando datos de la API del BCE: {url}")
    respuesta = requests.get(url, params=parametros, timeout=60)
    respuesta.raise_for_status()  # error claro si la API no responde
    return pd.read_csv(io.StringIO(respuesta.text))


# ---------------------------------------------------------------------------
# 2. Limpieza y tratamiento
# ---------------------------------------------------------------------------

def limpiar_datos(bruto: pd.DataFrame) -> pd.DataFrame:
    """Convierte la respuesta del BCE en una tabla mes x país.

    - Se queda solo con las columnas necesarias.
    - Convierte fechas y valores a su tipo correcto.
    - Elimina valores vacíos o no numéricos.
    - Pasa de formato largo (una fila por país y mes) a ancho (una columna por país).
    - Elimina los meses sin dato del Bund, porque sin referencia no hay diferencial.
    """
    columnas = {"REF_AREA", "TIME_PERIOD", "OBS_VALUE"}
    faltan = columnas - set(bruto.columns)
    if faltan:
        raise ValueError(f"La respuesta del BCE no tiene las columnas {faltan}")

    datos = bruto[list(columnas)].copy()
    datos["fecha"] = pd.to_datetime(datos["TIME_PERIOD"], format="%Y-%m", errors="coerce")
    datos["valor"] = pd.to_numeric(datos["OBS_VALUE"], errors="coerce")
    datos = datos.dropna(subset=["fecha", "valor"])

    tabla = (
        datos.pivot_table(index="fecha", columns="REF_AREA", values="valor", aggfunc="last")
        .sort_index()
    )
    tabla = tabla.dropna(subset=[REFERENCIA])

    # Control de calidad: rendimientos fuera de un rango razonable indican un
    # error en la fuente. El máximo histórico de Grecia en la serie es ~29 %.
    fuera_de_rango = (tabla < -2) | (tabla > 40)
    if fuera_de_rango.any().any():
        print("Aviso: se descartan valores fuera de rango:", int(fuera_de_rango.sum().sum()))
        tabla = tabla.mask(fuera_de_rango)

    return tabla


# ---------------------------------------------------------------------------
# 3. Cálculo del indicador
# ---------------------------------------------------------------------------

def clasificar(spread_pb: float) -> tuple[str, str]:
    """Devuelve el nivel del semáforo y su etiqueta para un diferencial en pb."""
    for limite, nivel, etiqueta in UMBRALES:
        if spread_pb < limite:
            return nivel, etiqueta
    return UMBRALES[-1][1], UMBRALES[-1][2]


def cambio(serie: pd.Series, meses: int) -> float | None:
    """Variación del diferencial en los últimos n meses, en pb."""
    serie = serie.dropna()
    if len(serie) <= meses:
        return None
    return round(float(serie.iloc[-1] - serie.iloc[-1 - meses]), 1)


def calcular_indicador(tabla: pd.DataFrame) -> dict:
    """Calcula la prima de riesgo y las métricas del widget.

    Prima de riesgo (pb) = (rendimiento país - rendimiento Bund) x 100
    """
    spreads = pd.DataFrame(index=tabla.index)
    for codigo in PAISES:
        if codigo in tabla:
            spreads[codigo] = (tabla[codigo] - tabla[REFERENCIA]) * 100

    resumen = []
    for codigo, nombre in PAISES.items():
        serie = spreads[codigo].dropna()
        if serie.empty:
            continue
        actual = float(serie.iloc[-1])
        nivel, etiqueta = clasificar(actual)
        subida_3m = cambio(serie, 3)
        resumen.append({
            "codigo": codigo,
            "nombre": nombre,
            "fecha": serie.index[-1].strftime("%Y-%m"),
            "rendimiento": round(float(tabla[codigo].dropna().iloc[-1]), 2),
            "spread": round(actual, 1),
            "cambio_1m": cambio(serie, 1),
            "cambio_3m": subida_3m,
            "cambio_12m": cambio(serie, 12),
            # Qué parte del histórico ha estado por debajo del nivel actual.
            "percentil": round(float((serie < actual).mean() * 100)),
            "maximo": round(float(serie.max()), 1),
            "fecha_maximo": serie.idxmax().strftime("%Y-%m"),
            "minimo": round(float(serie.min()), 1),
            "fecha_minimo": serie.idxmin().strftime("%Y-%m"),
            "nivel": nivel,
            "etiqueta": etiqueta,
            "alerta": subida_3m is not None and subida_3m > ALERTA_SUBIDA_3M,
            "en_maximos": float((serie < actual).mean() * 100) >= PERCENTIL_MAXIMOS,
        })

    # Índice de fragmentación: media simple de los diferenciales.
    # Mide cuánto se separan los costes de financiación dentro de la zona euro.
    fragmentacion = spreads.mean(axis=1)
    frag_actual = float(fragmentacion.iloc[-1])
    frag_nivel, frag_etiqueta = clasificar(frag_actual)

    return {
        "spreads": spreads,
        "rendimientos": tabla,
        "resumen": sorted(resumen, key=lambda r: r["spread"], reverse=True),
        "fragmentacion": {
            "valor": round(frag_actual, 1),
            "cambio_12m": cambio(fragmentacion, 12),
            "nivel": frag_nivel,
            "etiqueta": frag_etiqueta,
            "serie": fragmentacion,
        },
    }


# ---------------------------------------------------------------------------
# 4. Preparación de los datos para la API
# ---------------------------------------------------------------------------

def _a_lista(serie: pd.Series, decimales: int = 1) -> list:
    """Convierte una serie en lista JSON, con None donde falta el dato."""
    return [None if pd.isna(v) else round(float(v), decimales) for v in serie]


def generar_lectura(resumen: list[dict]) -> str:
    """Frase automática que resume la situación para el lector."""
    mayor = resumen[0]
    texto = (
        f"{mayor['nombre']} es hoy el país con mayor prima de riesgo "
        f"({mayor['spread']:.0f} pb frente al Bund)."
    )
    maximos = [r for r in resumen if r["en_maximos"]]
    for r in maximos:
        texto += (f" Aunque su nivel absoluto se considera {r['etiqueta'].lower()}, {r['nombre']} está por encima "
                  f"del {r['percentil']} % de los meses desde 2007: su riesgo relativo está en máximos.")
    alertas = [r["nombre"] for r in resumen if r["alerta"]]
    if alertas:
        texto += " Tensión creciente en " + ", ".join(alertas) + ": más de 50 pb de subida en tres meses."
    else:
        texto += " Ningún país registra subidas bruscas en los últimos tres meses."
    return texto


def exportar_json(resultado: dict, ruta: Path = RUTA_SALIDA) -> dict:
    """Guarda el resultado en el JSON que actúa como endpoint del widget."""
    spreads = resultado["spreads"]
    frag = resultado["fragmentacion"]
    salida = {
        "titulo": "Monitor de prima de riesgo de la zona euro",
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "ultimo_dato": spreads.index[-1].strftime("%Y-%m"),
        "unidad": "puntos básicos (pb) frente al Bund alemán a 10 años",
        "fuente": {
            "nombre": "Banco Central Europeo, ECB Data Portal (dataset IRS)",
            "serie": "Harmonised long-term interest rates for convergence assessment purposes",
            "url": "https://data.ecb.europa.eu/data/datasets/IRS",
        },
        "umbrales": [{"hasta": None if l == float("inf") else l, "nivel": n, "etiqueta": e}
                     for l, n, e in UMBRALES],
        "lectura": generar_lectura(resultado["resumen"]),
        "resumen": resultado["resumen"],
        "fragmentacion": {k: v for k, v in frag.items() if k != "serie"},
        "series": {
            "fechas": [f.strftime("%Y-%m") for f in spreads.index],
            "bund": _a_lista(resultado["rendimientos"][REFERENCIA], 2),
            "spreads": {c: _a_lista(spreads[c]) for c in spreads},
            "fragmentacion": _a_lista(frag["serie"]),
        },
    }
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Datos guardados en {ruta} (último dato: {salida['ultimo_dato']})")
    return salida


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Actualiza el monitor de prima de riesgo.")
    parser.add_argument("--csv", help="Usar un CSV local en lugar de la API del BCE")
    args = parser.parse_args()

    try:
        bruto = descargar_datos(args.csv)
    except requests.RequestException as error:
        # Si la API falla, no se sobrescribe el último data.json válido.
        print(f"Error al descargar los datos del BCE: {error}", file=sys.stderr)
        return 1

    tabla = limpiar_datos(bruto)
    resultado = calcular_indicador(tabla)
    salida = exportar_json(resultado)

    print(salida["lectura"])
    for r in salida["resumen"]:
        print(f"  {r['nombre']:<9} {r['spread']:>6.0f} pb  {r['etiqueta']:<17} "
              f"12m: {r['cambio_12m']:+.0f} pb  percentil histórico: {r['percentil']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
