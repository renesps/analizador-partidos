from flask import Flask, render_template, request, jsonify
import requests
import time
import random
from datetime import datetime, timedelta

app = Flask(__name__)

# ── Headers para Sofascore (búsqueda de equipos/partido desde el servidor) ────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
]

def sofascore_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
        'Origin': 'https://www.sofascore.com',
        'Referer': 'https://www.sofascore.com/',
    }

def sofascore_get(url, params=None):
    try:
        r = requests.get(url, params=params, headers=sofascore_headers(), timeout=10)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/buscar', methods=['POST'])
def buscar():
    """
    Busca el partido en Sofascore y devuelve el event_id + team_ids.
    El navegador del cliente usa esos IDs para hacer el resto de las calls
    a api.sofascore.com directamente (evita el bloqueo de IPs de datacenter).
    """
    data = request.json or {}
    equipo_a = data.get('equipo_a', '').strip()
    equipo_b = data.get('equipo_b', '').strip()

    if not equipo_a or not equipo_b:
        return jsonify({'error': 'Faltan equipos'}), 400

    # Buscar equipo A
    r_a = sofascore_get('https://api.sofascore.com/api/v1/search/all', {'q': equipo_a})
    team_a = None
    if r_a and 'results' in r_a:
        for item in r_a['results']:
            if item.get('type') == 'team':
                e = item.get('entity', {})
                team_a = {'id': e.get('id'), 'nombre': e.get('name')}
                break

    if not team_a:
        return jsonify({'error': f'No se encontró el equipo: {equipo_a}'}), 404

    time.sleep(random.uniform(1.0, 2.0))

    # Buscar equipo B
    r_b = sofascore_get('https://api.sofascore.com/api/v1/search/all', {'q': equipo_b})
    team_b = None
    if r_b and 'results' in r_b:
        for item in r_b['results']:
            if item.get('type') == 'team':
                e = item.get('entity', {})
                team_b = {'id': e.get('id'), 'nombre': e.get('name')}
                break

    if not team_b:
        return jsonify({'error': f'No se encontró el equipo: {equipo_b}'}), 404

    time.sleep(random.uniform(1.0, 2.0))

    # Buscar el partido en próximos eventos del equipo A
    event_id = None
    evento = None
    for pagina in [0, 1]:
        r_ev = sofascore_get(f'https://api.sofascore.com/api/v1/team/{team_a["id"]}/events/next/{pagina}')
        if not r_ev or 'events' not in r_ev:
            continue
        for ev in r_ev['events']:
            home_id = ev.get('homeTeam', {}).get('id')
            away_id = ev.get('awayTeam', {}).get('id')
            if team_b['id'] in [home_id, away_id]:
                event_id = ev['id']
                evento = ev
                break
        if event_id:
            break
        time.sleep(random.uniform(1.0, 1.5))

    if not event_id:
        return jsonify({'error': f'No se encontró el próximo partido entre {equipo_a} y {equipo_b}'}), 404

    # Metadata básica del partido
    ts = evento.get('startTimestamp', 0)
    fecha = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%S+00:00') if ts else ''

    return jsonify({
        'event_id': event_id,
        'team_a_id': team_a['id'],
        'team_b_id': team_b['id'],
        'equipo_a': evento.get('homeTeam', {}).get('name', team_a['nombre']),
        'equipo_b': evento.get('awayTeam', {}).get('name', team_b['nombre']),
        'competicion': evento.get('tournament', {}).get('name', ''),
        'fecha': fecha,
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
