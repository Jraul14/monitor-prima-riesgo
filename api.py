"""
API opcional del monitor de prima de riesgo (Flask).

Sirve los datos calculados por src/prima_riesgo.py en un endpoint REST, para
que Meteoeconomics u otra aplicación puedan consumirlos. En la versión publicada
en GitHub Pages no hace falta: allí el endpoint es el propio docs/data.json.

Uso:
    python api.py
    -> widget:   http://localhost:5000/
    -> endpoint: http://localhost:5000/api/prima-riesgo
    -> un país:  http://localhost:5000/api/prima-riesgo/IT
"""

import json
from pathlib import Path

from flask import Flask, abort, jsonify, send_from_directory

DOCS = Path(__file__).resolve().parent / "docs"
app = Flask(__name__)


def cargar() -> dict:
    ruta = DOCS / "data.json"
    if not ruta.exists():
        abort(503, "Todavía no hay datos. Ejecuta primero: python src/prima_riesgo.py")
    return json.loads(ruta.read_text(encoding="utf-8"))


@app.after_request
def permitir_cors(respuesta):
    # Permite que otras webs (por ejemplo, Meteoeconomics) lean el endpoint.
    respuesta.headers["Access-Control-Allow-Origin"] = "*"
    return respuesta


@app.get("/api/prima-riesgo")
def prima_riesgo():
    return jsonify(cargar())


@app.get("/api/prima-riesgo/<codigo>")
def prima_riesgo_pais(codigo: str):
    datos = cargar()
    codigo = codigo.upper()
    pais = next((r for r in datos["resumen"] if r["codigo"] == codigo), None)
    if pais is None:
        abort(404, f"País no disponible: {codigo}. Usa IT, FR, ES, PT o GR.")
    return jsonify({**pais, "serie": dict(zip(datos["series"]["fechas"], datos["series"]["spreads"][codigo]))})


@app.get("/")
def widget():
    # Sirve el widget apuntando a este endpoint.
    return send_from_directory(DOCS, "index.html")


@app.get("/data.json")
def data_json():
    return jsonify(cargar())


if __name__ == "__main__":
    app.run(debug=True)
