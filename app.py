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

    prompt = f"""Haceme un análisis profundo del partido {eqA} vs {eqB}.

A continuación tenés todos los datos recopilados de Sofascore para este partido. Usá ESTOS datos como base y complementá con tu conocimiento del fútbol para el análisis táctico y de contexto:

═══════════════════════════════════════
DATOS DEL PARTIDO (fuente: Sofascore)
═══════════════════════════════════════
Competición: {competicion}
Fecha: {fecha}
{f'Estadio: {estadio}' if estadio else ''}
{f'Árbitro: {arbitro}' if arbitro else 'Árbitro: sin confirmar'}

FORMA RECIENTE — {eqA} (últimos 5):
{forma_str(formaA, detA)}

FORMA RECIENTE — {eqB} (últimos 5):
{forma_str(formaB, detB)}

ESTADÍSTICAS ÚLTIMOS 5 PARTIDOS:
{eqA}: {statsA.get('gf','?')} goles marcados, {statsA.get('gc','?')} recibidos | Prom: {statsA.get('pgf','?')} GF / {statsA.get('pgc','?')} GC | Clean sheets: {statsA.get('cs','?')}
{eqB}: {statsB.get('gf','?')} goles marcados, {statsB.get('gc','?')} recibidos | Prom: {statsB.get('pgf','?')} GF / {statsB.get('pgc','?')} GC | Clean sheets: {statsB.get('cs','?')}

CORNERS PROMEDIO (últimos 5 partidos):
{eqA}: {cornersA if cornersA else 'N/D'} corners/partido | {eqB}: {cornersB if cornersB else 'N/D'} corners/partido
{f'Total combinado: {round(cornersA+cornersB,1)} corners/partido' if cornersA and cornersB else ''}

TARJETAS AMARILLAS PROMEDIO (últimos 5):
{eqA}: {amarillasA if amarillasA else 'N/D'} | {eqB}: {amarillasB if amarillasB else 'N/D'}

ALINEACIONES (Sofascore):
{eqA} ({formacionA if formacionA else 'formación no confirmada'}): {tit_str(titularesA)}
{eqB} ({formacionB if formacionB else 'formación no confirmada'}): {tit_str(titularesB)}

HISTORIAL DIRECTO (H2H):
{h2h_str}
{h2h_det}
═══════════════════════════════════════

Incluí EXACTAMENTE todo esto en tu respuesta:

1. 📊 CONTEXTO DEL PARTIDO
   - Competición y fecha
   - Horario y estadio
   - Árbitro (nombre completo si está confirmado, y su estilo: cardista, permisivo, estricto)
   - Qué se juega cada equipo (motivación, presión, necesidad de puntos)

2. 📈 POSICIONES Y FORMA
   - Tabla de posiciones actual en la {competicion}
   - Forma de últimos 5 partidos con resultados detallados (ya los tenés arriba)
   - Rendimiento local/visitante específico

3. ⚽ ALINEACIONES CONFIRMADAS/PREDICHAS
   - Formación táctica
   - Titulares por posición
   - BAJAS CONFIRMADAS (lesiones, suspensiones, dudas) con detalle
   - Jugadores en duda o con problemas físicos

4. 📊 ESTADÍSTICAS CLAVE
   - Basate en los datos de Sofascore que te di arriba
   - xG estimado según la calidad de los equipos
   - Posesión y estilo de juego
   - Clean sheets y tendencia defensiva

5. 🎯 ANÁLISIS TÁCTICO
   - Sistema de juego de cada equipo
   - Fortalezas y debilidades según los números
   - Jugadores clave a seguir
   - Matchups individuales importantes

6. 🚩 ANÁLISIS DE CÓRNERS ⭐
   Basate en los datos de Sofascore: {eqA} promedia {cornersA if cornersA else 'N/D'} y {eqB} promedia {cornersB if cornersB else 'N/D'} corners por partido (últimos 5).

   **{eqA}:**
   - Promedio corners partido: {cornersA if cornersA else 'N/D'}
   - Tendencia 1er vs 2do tiempo (estimá según tu conocimiento del equipo)

   **{eqB}:**
   - Promedio corners partido: {cornersB if cornersB else 'N/D'}
   - Tendencia 1er vs 2do tiempo (estimá según tu conocimiento del equipo)

   **COMBINADO:**
   - Promedio total: {f'{round(cornersA+cornersB,1)}' if cornersA and cornersB else 'calcular'}
   - % estimado partidos Over 8.5, 9.5, 10.5 corners
   - % estimado Over 4.5 corners al descanso

   **MERCADOS RECOMENDADOS:**
   - Over/Under corners 1er tiempo
   - Over/Under corners partido completo
   - Corners por equipo

7. ⚽ ANÁLISIS DE GOLES
   - Basate en: {eqA} promedia {statsA.get('pgf','?')} GF y {statsA.get('pgc','?')} GC; {eqB} promedia {statsB.get('pgf','?')} GF y {statsB.get('pgc','?')} GC
   - % estimado partidos Over 1.5, 2.5, 3.5 goles
   - Minutos donde más marcan (primera/segunda mitad)
   - BTTS (ambos marcan): probabilidad estimada
   - Mercados: Over/Under, BTTS, primer gol

8. 🟨 ANÁLISIS DE TARJETAS Y ÁRBITRO ⭐
   - {'Árbitro: ' + arbitro + '. Buscá su historial, estilo y promedio de tarjetas en la temporada.' if arbitro else 'Árbitro: sin confirmar. Usá el promedio general de la competición.'}
   - {eqA} promedia {amarillasA if amarillasA else 'N/D'} amarillas/partido | {eqB} promedia {amarillasB if amarillasB else 'N/D'} amarillas/partido
   - % estimado Over 3.5, 4.5, 5.5 tarjetas totales
   - Jugadores propensos a tarjetas de cada equipo
   - Historial de tarjetas en H2H
   - Mercados: Over/Under tarjetas, primer tarjeta, tarjeta a jugador específico

9. 🎯 MERCADOS Y APUESTAS
   - Análisis de 1X2, handicap, over/under goles, BTTS, corners, tarjetas
   - Cuotas aproximadas de mercado para cada opción
   - Seguridad de cada apuesta (⭐ del 1 al 5)

10. ⚠️ RIESGOS IDENTIFICADOS
    | Riesgo | Probabilidad | Impacto |
    |--------|-------------|---------|
    (completá con 3-4 riesgos reales del partido)

11. ✅ VEREDICTO FINAL
    Tabla resumen con las mejores apuestas, cuota estimada, confianza y recomendación.

═══════════════════════════════════════
🏆 CUADRO FINAL — TOP 3 APUESTAS (cuota ~1.80)
═══════════════════════════════════════
| # | Apuesta | Mercado | Cuota ~1.80 | Confianza % | Razonamiento |
|---|---------|---------|-------------|-------------|--------------|
| 1 | ...     | ...     | ~1.80       | XX%         | ...          |
| 2 | ...     | ...     | ~1.80       | XX%         | ...          |
| 3 | ...     | ...     | ~1.80       | XX%         | ...          |

═══════════════════════════════════════
🔗 CUADRO PARA COMBINAR — 3 APUESTAS SEGURAS (cuota ~1.50)
═══════════════════════════════════════
| # | Apuesta | Mercado | Cuota ~1.50 | Confianza % | Para combinar con |
|---|---------|---------|-------------|-------------|-------------------|
| 1 | ...     | ...     | ~1.50       | XX%         | ...               |
| 2 | ...     | ...     | ~1.50       | XX%         | ...               |
| 3 | ...     | ...     | ~1.50       | XX%         | ...               |

IMPORTANTE:
- Usá los datos de Sofascore que te di como base principal
- Si no tenés datos confirmados de algo, indicá "sin confirmar" o "estimado"
- Sé honesto sobre la confianza real de cada apuesta
- No inventes estadísticas, si no las tenés decilo
- Para el árbitro, usá el nombre que te di y buscá su historial en tu conocimiento
- Las cuotas son aproximadas de mercado, no exactas"""

    def generar():
        """Genera la respuesta en streaming: manda chunks SSE al browser."""
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
                    'max_tokens': 6000,
                    'stream': True,
                },
                stream=True,
                timeout=180
            )
            for line in r.iter_lines():
                if not line:
                    continue
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data_str = line[6:]
                    if data_str.strip() == '[DONE]':
                        yield 'data: [DONE]\n\n'
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get('choices', [{}])[0].get('delta', {})
                        content = delta.get('content', '')
                        if content:
                            # Mandar cada fragmento como SSE
                            yield f'data: {json.dumps({"t": content})}\n\n'
                    except Exception:
                        continue
        except Exception as e:
            yield f'data: {json.dumps({"error": str(e)})}\n\n'

    return app.response_class(
        generar(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
