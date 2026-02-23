from flask import Flask, render_template, request, jsonify, make_response, send_from_directory
import os, requests, json, time, threading

app = Flask(__name__)

SCRAPER_API_KEY = os.environ.get('SCRAPER_API_KEY', '')
SCRAPE_DO_KEY   = os.environ.get('SCRAPE_DO_KEY', '')
KIMI_API_KEY    = os.environ.get('KIMI_API_KEY', '')
ODDS_API_KEY    = os.environ.get('ODDS_API_KEY', '')   # The Odds API (free tier 500 req/mes)
DATABASE_URL    = os.environ.get('DATABASE_URL', '')  # PostgreSQL en Supabase
DB_PATH         = os.environ.get('DB_PATH', 'historial.db')  # SQLite fallback local

# ── Base de datos: PostgreSQL (Supabase) con fallback a SQLite ────────────────
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras

def get_db():
    if USE_PG:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    else:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    if USE_PG:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS historial (
                        id            SERIAL PRIMARY KEY,
                        partido       TEXT NOT NULL,
                        competicion   TEXT,
                        fecha_partido TEXT,
                        fecha_analisis BIGINT NOT NULL,
                        stats_json    TEXT,
                        analisis_ia   TEXT
                    )
                ''')
            conn.commit()
    else:
        import sqlite3
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
    if USE_PG:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute('DELETE FROM historial WHERE fecha_analisis < %s', (cutoff,))
            conn.commit()
    else:
        import sqlite3
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
    """
    Proxy server-side para Sofascore.
    Intenta directo primero; si da 403 (IP datacenter bloqueada), usa ScraperAPI como fallback.
    """
    sf_url = 'https://api.sofascore.com/api/v1' + path

    # 1. Caché
    cached_content, cached_status = cache_get(sf_url)
    if cached_content is not None:
        return FakeResponse(cached_content, cached_status)

    rate_limit()

    # 2. Intento directo
    try:
        r = requests.get(sf_url, headers=SF_HEADERS, timeout=15)
        if r.status_code == 200:
            cache_set(sf_url, r.content, r.status_code)
            app.logger.info('SF directo ok: %s', path)
            return r
        app.logger.warning('SF directo %s: %s', r.status_code, path)
    except Exception as e:
        app.logger.error('SF directo error: %s | %s', e, path)

    # 3. Fallback: ScraperAPI (IPs residenciales, bypasea bloqueo de datacenter)
    if SCRAPER_API_KEY:
        try:
            params = {
                'api_key': SCRAPER_API_KEY,
                'url': sf_url,
                'keep_headers': 'true',
            }
            r2 = requests.get('http://api.scraperapi.com', params=params,
                              headers=SF_HEADERS, timeout=25)
            if r2.status_code == 200:
                cache_set(sf_url, r2.content, 200)
                app.logger.info('SF via ScraperAPI ok: %s', path)
                return r2
            app.logger.warning('ScraperAPI %s: %s', r2.status_code, path)
        except Exception as e:
            app.logger.error('ScraperAPI error: %s | %s', e, path)

    return FakeResponse(b'{"error":"sofascore unavailable"}', 503)

# ── Rutas principales ────────────────────────────────────────────────────────
@app.route('/')
def index():
    resp = make_response(render_template('index.html', kimi_key=KIMI_API_KEY))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp

@app.route('/service-worker.js')
def service_worker():
    """Sirve el SW desde la raíz (requerido para que tenga scope '/')."""
    resp = make_response(send_from_directory('static', 'service-worker.js'))
    resp.headers['Content-Type']  = 'application/javascript'
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/manifest.json')
def manifest():
    resp = make_response(send_from_directory('static', 'manifest.json'))
    resp.headers['Content-Type']  = 'application/manifest+json'
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp

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

# ── Cuotas en vivo — The Odds API ────────────────────────────────────────────
@app.route('/odds')
def get_odds():
    """
    Obtiene cuotas en vivo de The Odds API.
    Query param: ?match=TEAM_A_vs_TEAM_B
    Retorna: { home, draw, away, over25, under25, source }
    """
    if not ODDS_API_KEY:
        return jsonify({'error': 'ODDS_API_KEY no configurada'}), 503

    match_param = request.args.get('match', '').strip()
    if not match_param or '_vs_' not in match_param:
        return jsonify({'error': 'Parámetro match inválido'}), 400

    # Caché por 10 minutos para las cuotas
    cache_key = 'odds:' + match_param
    cached, _ = cache_get(cache_key)
    if cached:
        return app.response_class(response=cached, status=200, mimetype='application/json')

    parts       = match_param.split('_vs_', 1)
    team_a_raw  = parts[0].strip().lower()
    team_b_raw  = parts[1].strip().lower()

    import re
    def normalize(s):
        s = s.lower().strip()
        for suffix in [' fc', ' cf', ' sc', ' ac', ' united', ' city', ' f.c.', ' s.a.', ' sad']:
            s = s.replace(suffix, '')
        return re.sub(r'[^a-z0-9 ]', '', s).strip()

    na = normalize(team_a_raw)
    nb = normalize(team_b_raw)

    try:
        params = {
            'apiKey':      ODDS_API_KEY,
            'regions':     'eu',
            'markets':     'h2h,totals',
            'oddsFormat':  'decimal',
        }
        # Fetch all active soccer odds in one request
        resp = requests.get(
            'https://api.the-odds-api.com/v4/sports/soccer/odds/',
            params=params, timeout=12
        )
        if not resp.ok:
            return jsonify({'error': f'Odds API HTTP {resp.status_code}'}), 502

        events = resp.json()
        if not isinstance(events, list):
            return jsonify({'error': 'Respuesta inesperada de Odds API'}), 502

        # Fuzzy match por nombre de equipo
        best_event = None
        best_score = 0
        for ev in events:
            hn = normalize(ev.get('home_team', ''))
            an = normalize(ev.get('away_team', ''))
            score = 0
            if na in hn or hn in na: score += 3
            if nb in an or an in nb: score += 3
            if na[:4] in hn:         score += 1
            if nb[:4] in an:         score += 1
            if score > best_score:
                best_score  = score
                best_event  = ev

        if not best_event or best_score < 3:
            return jsonify({'error': 'Partido no encontrado en The Odds API'}), 404

        # Extraer cuotas priorizando Bet365, luego 1xbet, luego cualquier otro
        PREFERRED_BOOKS = ['bet365', '1xbet', 'betfair', 'unibet', 'bwin', 'betway', 'william hill']

        def bk_priority(bk):
            title = bk.get('title', '').lower()
            for i, name in enumerate(PREFERRED_BOOKS):
                if name in title:
                    return i
            return len(PREFERRED_BOOKS)  # último lugar si no está en la lista preferida

        bookmakers_sorted = sorted(best_event.get('bookmakers', []), key=bk_priority)

        home_odd = draw_odd = away_odd = None
        over25   = under25  = None
        source   = ''

        for bk in bookmakers_sorted:
            for mkt in bk.get('markets', []):
                if mkt['key'] == 'h2h' and home_odd is None:
                    outs = {o['name']: o['price'] for o in mkt.get('outcomes', [])}
                    home_odd = outs.get(best_event['home_team'])
                    draw_odd = outs.get('Draw')
                    away_odd = outs.get(best_event['away_team'])
                    source   = bk.get('title', '')
                if mkt['key'] == 'totals' and over25 is None:
                    for o in mkt.get('outcomes', []):
                        pt = abs(o.get('point', 0) - 2.5)
                        if o['name'] == 'Over'  and pt < 0.01: over25  = o['price']
                        if o['name'] == 'Under' and pt < 0.01: under25 = o['price']
            if home_odd and over25:
                break  # Tenemos todo lo que necesitamos

        result = json.dumps({
            'home': home_odd, 'draw': draw_odd, 'away': away_odd,
            'over25': over25, 'under25': under25, 'source': source,
        }).encode()
        cache_set(cache_key, result, 200)
        return app.response_class(response=result, status=200, mimetype='application/json')

    except Exception as e:
        app.logger.error('Odds API error: %s', e)
        return jsonify({'error': str(e)}), 500

# ── Historial ────────────────────────────────────────────────────────────────
@app.route('/historial', methods=['GET'])
def historial_list():
    """Devuelve la lista de análisis guardados (sin el texto completo de IA)."""
    purge_old()
    try:
        if USE_PG:
            with get_db() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute('''
                        SELECT id, partido, competicion, fecha_partido, fecha_analisis
                        FROM historial
                        ORDER BY fecha_analisis DESC
                        LIMIT 50
                    ''')
                    rows = cur.fetchall()
            return jsonify([dict(r) for r in rows])
        else:
            import sqlite3
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
        if USE_PG:
            with get_db() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute('SELECT * FROM historial WHERE id=%s', (id,))
                    row = cur.fetchone()
        else:
            import sqlite3
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

        partido       = data.get('partido', '')
        competicion   = data.get('competicion', '')
        fecha_partido = data.get('fecha_partido', '')
        fecha_analisis = int(time.time())
        stats_json    = json.dumps(data.get('stats_json')) if data.get('stats_json') else None
        analisis_ia   = data.get('analisis_ia', '')

        if USE_PG:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        INSERT INTO historial (partido, competicion, fecha_partido, fecha_analisis, stats_json, analisis_ia)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                    ''', (partido, competicion, fecha_partido, fecha_analisis, stats_json, analisis_ia))
                    new_id = cur.fetchone()[0]
                conn.commit()
            return jsonify({'id': new_id}), 201
        else:
            import sqlite3
            with get_db() as conn:
                cur = conn.execute('''
                    INSERT INTO historial (partido, competicion, fecha_partido, fecha_analisis, stats_json, analisis_ia)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (partido, competicion, fecha_partido, fecha_analisis, stats_json, analisis_ia))
                conn.commit()
                return jsonify({'id': cur.lastrowid}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/historial/<int:id>', methods=['DELETE'])
def historial_delete(id):
    """Borra un análisis del historial."""
    try:
        if USE_PG:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute('DELETE FROM historial WHERE id=%s', (id,))
                conn.commit()
        else:
            import sqlite3
            with get_db() as conn:
                conn.execute('DELETE FROM historial WHERE id=?', (id,))
                conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
