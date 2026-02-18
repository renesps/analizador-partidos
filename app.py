from flask import Flask, render_template, request, jsonify
import os, requests, json

app = Flask(__name__)

SCRAPER_API_KEY = os.environ.get('SCRAPER_API_KEY', '')
KIMI_API_KEY    = os.environ.get('KIMI_API_KEY', '')

def sf_get(path):
    sf_url = 'https://api.sofascore.com/api/v1' + path
    if SCRAPER_API_KEY:
        r = requests.get('https://api.scraperapi.com',
            params={'api_key': SCRAPER_API_KEY, 'url': sf_url, 'render': 'false'},
            timeout=30)
    else:
        r = requests.get(sf_url, headers={
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
            'Referer': 'https://www.sofascore.com/',
        }, timeout=15)
    return r

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/sf')
def proxy():
    path = request.args.get('path', '')
    if not path or not path.startswith('/'):
        return jsonify({'error': 'path invalido'}), 400
    try:
        r = sf_get(path)
        return app.response_class(response=r.content, status=r.status_code, mimetype='application/json')
    except Exception as e:
        return jsonify({'error': str(e)}), 502

@app.route('/analisis-ia', methods=['POST'])
def analisis_ia():
    """Recibe los datos del partido ya procesados y los manda a Kimi para análisis."""
    if not KIMI_API_KEY:
        return jsonify({'error': 'KIMI_API_KEY no configurada'}), 503

    datos = request.get_json(force=True)
    if not datos:
        return jsonify({'error': 'Sin datos'}), 400

    # Construir prompt con todos los datos de Sofascore
    eqA = datos.get('eqA', '?')
    eqB = datos.get('eqB', '?')
    fecha = datos.get('fecha', '?')
    competicion = datos.get('competicion', '?')
    estadio = datos.get('estadio', '')
    arbitro = datos.get('arbitro', '')
    formaA = datos.get('formaA', [])
    formaB = datos.get('formaB', [])
    detA = datos.get('detA', [])
    detB = datos.get('detB', [])
    statsA = datos.get('statsA', {})
    statsB = datos.get('statsB', {})
    cornersA = datos.get('cornersA')
    cornersB = datos.get('cornersB')
    amarillasA = datos.get('amarillasA')
    amarillasB = datos.get('amarillasB')
    formacionA = datos.get('formacionA', '')
    formacionB = datos.get('formacionB', '')
    titularesA = datos.get('titularesA', [])
    titularesB = datos.get('titularesB', [])
    h2h = datos.get('h2h', {})

    def forma_str(badges, detalle):
        resultado = ' '.join(badges) if badges else 'Sin datos'
        detalles = []
        for d in detalle:
            detalles.append(f"  {d.get('fecha','')} {'vs' if d.get('local') else 'en'} {d.get('rival','?')}: {d.get('res','?')}")
        return resultado + ('\n' + '\n'.join(detalles) if detalles else '')

    def tit_str(lista):
        if not lista:
            return 'No disponible'
        return ', '.join([f"{j.get('num','')}.{j.get('nombre','?')}({j.get('pos','')})" for j in lista])

    h2h_res = h2h.get('res', {})
    h2h_list = h2h.get('list', [])
    h2h_str = f"{eqA} {h2h_res.get('vA',0)} - Empates {h2h_res.get('emp',0)} - {eqB} {h2h_res.get('vB',0)}"
    h2h_det = '\n'.join([f"  {p.get('fecha','')} {p.get('home','')} {p.get('sc','')} {p.get('away','')} ({p.get('comp','')})" for p in h2h_list[:6]])

    prompt = f"""Eres un analista de fútbol experto en scalping deportivo y análisis pre-partido.
Tenés todos los datos estadísticos del siguiente partido obtenidos de Sofascore. Con esa información, hacé un análisis profundo como lo haría un scout profesional.

═══════════════════════════════════════
PARTIDO: {eqA} vs {eqB}
Fecha: {fecha}
Competición: {competicion}
{f'Estadio: {estadio}' if estadio else ''}
{f'Árbitro: {arbitro}' if arbitro else ''}
═══════════════════════════════════════

FORMA RECIENTE — {eqA}:
{forma_str(formaA, detA)}

FORMA RECIENTE — {eqB}:
{forma_str(formaB, detB)}

ESTADÍSTICAS ÚLTIMOS 5 PARTIDOS:
{eqA}: {statsA.get('gf','?')} goles marcados, {statsA.get('gc','?')} recibidos | Prom: {statsA.get('pgf','?')} GF / {statsA.get('pgc','?')} GC | Clean sheets: {statsA.get('cs','?')}
{eqB}: {statsB.get('gf','?')} goles marcados, {statsB.get('gc','?')} recibidos | Prom: {statsB.get('pgf','?')} GF / {statsB.get('pgc','?')} GC | Clean sheets: {statsB.get('cs','?')}

CORNERS PROMEDIO (últimos 5):
{eqA}: {cornersA if cornersA else 'N/D'} | {eqB}: {cornersB if cornersB else 'N/D'}
{f'Total combinado: {round(cornersA+cornersB,1)}' if cornersA and cornersB else ''}

TARJETAS AMARILLAS PROMEDIO (últimos 5):
{eqA}: {amarillasA if amarillasA else 'N/D'} | {eqB}: {amarillasB if amarillasB else 'N/D'}

ALINEACIONES PROBABLES:
{eqA} ({formacionA}): {tit_str(titularesA)}
{eqB} ({formacionB}): {tit_str(titularesB)}

HISTORIAL DIRECTO (H2H):
{h2h_str}
{h2h_det}

═══════════════════════════════════════
Con TODOS estos datos, generá un análisis estructurado con estas secciones:

1. **CONTEXTO DEL PARTIDO** — Qué se juega cada equipo, importancia del partido, momento de forma actual

2. **ANÁLISIS TÁCTICO** — Cómo juega cada equipo basándote en su forma y resultados, qué planteo probable tendrá cada DT, fortalezas y debilidades según los números

3. **CLAVES DEL PARTIDO** — Los 3-4 factores decisivos que van a determinar el resultado

4. **MERCADOS RECOMENDADOS PARA SCALPING** — Basándote en los patrones estadísticos (corners, goles, tarjetas, resultado), qué mercados tienen más valor y por qué. Sé específico con los números

5. **PREDICCIÓN** — Tu pronóstico final con razonamiento estadístico

Sé directo, concreto y basa TODO en los datos que te di. No inventes información que no esté en los datos."""

    try:
        r = requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {KIMI_API_KEY}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'https://analizador-partidos.onrender.com',
            },
            json={
                'model': 'moonshotai/kimi-k2',
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.4,
                'max_tokens': 2000,
            },
            timeout=60
        )
        data = r.json()
        if r.status_code != 200:
            return jsonify({'error': data.get('error', {}).get('message', 'Error de API')}), 502
        texto = data['choices'][0]['message']['content']
        return jsonify({'analisis': texto})
    except Exception as e:
        return jsonify({'error': str(e)}), 502

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
