# Monitor de prima de riesgo de la zona euro

Widget que mide la prima de riesgo (diferencial del bono a 10 años frente al Bund alemán) de Italia, Francia, España, Portugal y Grecia, la clasifica con un semáforo y la compara con su propia historia desde 2007. Los datos salen de la API pública del Banco Central Europeo y se actualizan solos cada día.

## Estructura

```
monitor-prima-riesgo/
├── src/prima_riesgo.py            Obtención, limpieza, cálculo y exportación a JSON
├── api.py                         API REST opcional con Flask
├── docs/index.html                El widget (lee docs/data.json)
├── docs/data.json                 Datos calculados: es el endpoint del widget
├── .github/workflows/actualizar.yml  Actualización automática diaria
└── requirements.txt
```

## Cómo funciona

1. `src/prima_riesgo.py` descarga de la API del BCE los rendimientos medios mensuales a 10 años (dataset IRS, serie `IRS.M.<país>.L.L40.CI.0000.EUR.N.Z`).
2. Limpia los datos (tipos, valores vacíos, meses sin Bund, valores fuera de rango).
3. Calcula la prima de riesgo: `(rendimiento del país − rendimiento del Bund) × 100`, en puntos básicos, y además la variación a 1, 3 y 12 meses, el percentil histórico, el máximo y el mínimo, el semáforo y el índice de fragmentación (media de los cinco diferenciales).
4. Guarda todo en `docs/data.json`, que actúa como endpoint.
5. `docs/index.html` hace `fetch("data.json")` y dibuja el widget. Con `?api=URL` puede leer de cualquier otro endpoint.
6. GitHub Actions ejecuta el script cada día a las 07:00 UTC y publica el JSON nuevo.

## Probarlo en tu ordenador

Necesitas Python 3.10 o superior.

```bash
pip install -r requirements.txt
python src/prima_riesgo.py          # descarga los datos y crea docs/data.json
cd docs
python -m http.server 8000          # abre http://localhost:8000
```

El widget no funciona si abres `index.html` con doble clic, porque el navegador bloquea la lectura de `data.json` desde el disco. Usa siempre el servidor local.

Para probar la API REST:

```bash
python api.py
# http://localhost:5000/api/prima-riesgo       todos los datos
# http://localhost:5000/api/prima-riesgo/IT    solo Italia
```

## Publicarlo en internet con actualización automática (GitHub Pages)

1. Crea una cuenta en github.com y un repositorio público nuevo, por ejemplo `monitor-prima-riesgo`.
2. Sube todos los archivos de esta carpeta (botón "Add file" → "Upload files"). Comprueba que la carpeta `.github` se ha subido: en algunos sistemas está oculta.
3. En el repositorio, ve a Settings → Actions → General → Workflow permissions, marca "Read and write permissions" y guarda.
4. Ve a Settings → Pages. En "Source" elige "Deploy from a branch", rama `main` y carpeta `/docs`. Guarda.
5. Ve a la pestaña Actions, elige "Actualizar prima de riesgo" y pulsa "Run workflow" para lanzar la primera actualización.
6. En uno o dos minutos el widget estará en `https://TU-USUARIO.github.io/monitor-prima-riesgo/` y el endpoint en `https://TU-USUARIO.github.io/monitor-prima-riesgo/data.json`.

A partir de ahí se actualiza solo cada día. Meteoeconomics podría integrarlo con un `<iframe>` que apunte a esa dirección.

## Limitaciones conocidas

- El dato es la media mensual que publica el BCE, con unas semanas de retraso. No sirve para seguir movimientos diarios.
- El Bund se usa como activo sin riesgo, pero Alemania también tiene su propio riesgo y factores técnicos (escasez de bonos, demanda refugio).
- Los umbrales del semáforo son una convención basada en episodios históricos, no una regla oficial.
- El índice de fragmentación es una media simple: no pondera por el tamaño de cada economía.
