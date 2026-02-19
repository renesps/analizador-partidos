from flask import Flask, render_template, request, jsonify
import os, requests, sqlite3, json, time

app = Flask(__name__)

SCRAPER_API_KEY = os.environ.get('SCRAPER_API_KEY', '')
KIMI_API_KEY    = os.environ.get('KIMI_API_KEY', '')

DB_PATH = os.environ.get('DB_PATH', 'historial.db')

# ── Base de datos ────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS historial (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                partido   TEXT NOT NULL,
                competicion TEXT,
                fecha_partido TEXT,
                fecha_analisis INTEGER NOT NULL,
                stats_json TEXT,
                analisis_ia TEXT
            )
        ''')
        conn.commit()

def purge_old():
    """Borra entradas con más de 24 horas de antigüedad."""
    cutoff = int(time.time()) - 86400
    with get_db() as conn:
        conn.execute('DELETE FROM historial WHERE fecha_analisis < ?', (cutoff,))
        conn.commit()

init_db()

# ── Sofascore proxy ──────────────────────────────────────────────────────────
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

# ── Rutas principales ────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html', kimi_key=KIMI_API_KEY)

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

# ── Historial ────────────────────────────────────────────────────────────────
@app.route('/historial', methods=['GET'])
def historial_list():
    """Devuelve la lista de análisis guardados (sin el texto completo de IA)."""
    purge_old()
    try:
        with get_db() as conn:
            rows = conn.execute('''
                SELECT id, partido, competicion, fecha_partido, fecha_analisis
                FROM historial
                ORDER BY fecha_analisis DESC
                LIMIT 50
            ''').fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/historial/<int:id>', methods=['GET'])
def historial_get(id):
    """Devuelve un análisis completo por ID."""
    try:
        with get_db() as conn:
            row = conn.execute('SELECT * FROM historial WHERE id=?', (id,)).fetchone()
        if not row:
            return jsonify({'error': 'No encontrado'}), 404
        d = dict(row)
        if d.get('stats_json'):
            try: d['stats_json'] = json.loads(d['stats_json'])
            except: pass
        return jsonify(d)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/historial', methods=['POST'])
def historial_save():
    """Guarda un nuevo análisis."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Sin datos'}), 400
        with get_db() as conn:
            cur = conn.execute('''
                INSERT INTO historial (partido, competicion, fecha_partido, fecha_analisis, stats_json, analisis_ia)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                data.get('partido', ''),
                data.get('competicion', ''),
                data.get('fecha_partido', ''),
                int(time.time()),
                json.dumps(data.get('stats_json')) if data.get('stats_json') else None,
                data.get('analisis_ia', ''),
            ))
            conn.commit()
            return jsonify({'id': cur.lastrowid}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/historial/<int:id>', methods=['DELETE'])
def historial_delete(id):
    """Borra un análisis del historial."""
    try:
        with get_db() as conn:
            conn.execute('DELETE FROM historial WHERE id=?', (id,))
            conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
