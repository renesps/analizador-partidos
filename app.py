from flask import Flask, render_template, request, jsonify
import os, requests, sqlite3, json, time, threading

app = Flask(__name__)

SCRAPER_API_KEY = os.environ.get('SCRAPER_API_KEY', '')
SCRAPE_DO_KEY   = os.environ.get('SCRAPE_DO_KEY', '')
KIMI_API_KEY    = os.environ.get('KIMI_API_KEY', '')
DB_PATH         = os.environ.get('DB_PATH', 'historial.db')

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

# ── Caché en memoria (TTL 5 min) ─────────────────────────────────────────────
_cache      = {}          # { url: (timestamp, response_bytes, status_code) }
_cache_lock = threading.Lock()
CACHE_TTL   = 300         # segundos

def cache_get(url):
    with _cache_lock:
        entry = _cache.get(url)
        if entry and (time.time() - entry[0]) < CACHE_TTL:
            return entry[1], entry[2]   # (content_bytes, status_code)
    return None, None

def cache_set(url, content_bytes, status_code):
    with _cache_lock:
        _cache[url] = (time.time(), content_bytes, status_code)

# ── Rate limiting (mín. 1 s entre requests reales) ───────────────────────────
_last_req_time = 0.0
_rate_lock     = threading.Lock()
MIN_INTERVAL   = 1.0      # segundos

def rate_limit():
    global _last_req_time
    with _rate_lock:
        wait = MIN_INTERVAL - (time.time() - _last_req_time)
        if wait > 0:
            time.sleep(wait)
        _last_req_time = time.time()

# ── Headers que imitan Chrome en Windows ─────────────────────────────────────
SF_HEADERS = {
    'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept':          'application/json, text/plain, */*',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer':         'https://www.sofascore.com/',
    'Origin':          'https://www.sofascore.com',
    'Cache-Control':   'no-cache',
    'Sec-Fetch-Dest':  'empty',
    'Sec-Fetch-Mode':  'cors',
    'Sec-Fetch-Site':  'same-site',
    'Connection':      'keep-alive',
}

# ── Sofascore proxy con fallback chain ───────────────────────────────────────
class FakeResponse:
    """Objeto mínimo compatible con requests.Response para el proxy."""
    def __init__(self, content, status_code):
        self.content     = content
        self.status_code = status_code

def sf_get(path):
    sf_url = 'https://api.sofascore.com/api/v1' + path

    # 1. Caché
    cached_content, cached_status = cache_get(sf_url)
    if cached_content is not None:
        app.logger.debug('SF CACHE hit: %s', path)
        return FakeResponse(cached_content, cached_status)

    # 2. Rate limit solo para requests reales
    rate_limit()

    # 3. Intento directo (gratis, sin proxy)
    try:
        r = requests.get(sf_url, headers=SF_HEADERS, timeout=15)
        if r.status_code == 200:
            cache_set(sf_url, r.content, r.status_code)
            app.logger.info('SF DIRECT ok: %s', path)
            return r
        app.logger.warning('SF DIRECT %s: %s', r.status_code, path)
    except Exception as e:
        app.logger.warning('SF DIRECT error: %s | %s', e, path)

    # 4. Fallback: Scrape.do (1 000 req/mes gratis)
    if SCRAPE_DO_KEY:
        try:
            r = requests.get(
                'https://api.scrape.do/',
                params={'token': SCRAPE_DO_KEY, 'url': sf_url},
                timeout=30,
            )
            if r.status_code == 200:
                cache_set(sf_url, r.content, r.status_code)
                app.logger.info('SF SCRAPE.DO ok: %s', path)
                return r
            app.logger.warning('SF SCRAPE.DO %s: %s', r.status_code, path)
        except Exception as e:
            app.logger.warning('SF SCRAPE.DO error: %s | %s', e, path)

    # 5. Fallback final: ScraperAPI (preservar créditos, solo si los anteriores fallan)
    if SCRAPER_API_KEY:
        try:
            r = requests.get(
                'https://api.scraperapi.com',
                params={'api_key': SCRAPER_API_KEY, 'url': sf_url, 'render': 'false'},
                timeout=30,
            )
            if r.status_code == 200:
                cache_set(sf_url, r.content, r.status_code)
            app.logger.info('SF SCRAPERAPI %s: %s', r.status_code, path)
            return r
        except Exception as e:
            app.logger.error('SF SCRAPERAPI error: %s | %s', e, path)
            return FakeResponse(b'{"error":"scraperapi failed"}', 502)

    # Sin ningún proxy disponible
    app.logger.error('SF NO PROXY AVAILABLE: %s', path)
    return FakeResponse(b'{"error":"no proxy available"}', 503)

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
