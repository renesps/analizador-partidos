from flask import Flask, render_template, request, jsonify
import requests
from datetime import datetime, timedelta
import time

from scraping_module import ScraperDeportivo

app = Flask(__name__)

# ── API-Football (fallback para datos históricos 2022-2024) ───────────────────
API_FOOTBALL_KEY = "12847b343c75c28d90392de6f3f3d907"
API_BASE_URL = "https://v3.football.api-sports.io"
API_HEADERS = {
    'x-rapidapi-host': "v3.football.api-sports.io",
    'x-rapidapi-key': API_FOOTBALL_KEY,
}

LIGAS_IDS_API = {
    'Premier League': 39,
    'La Liga': 140,
    'Serie A': 135,
    'Bundesliga': 78,
    'Ligue 1': 61,
    'Champions League': 2,
    'Primeira Liga': 94,
    'Liga Portugal': 94,
    'Betclic': 94,
    'Copa Libertadores': 13,
    'Libertadores': 13,
    'Copa Sudamericana': 11,
    'Sudamericana': 11,
    'Super Lig': 203,
    'Süper Lig': 203,
    'Turquia': 203,
    'Liga Profesional Argentina': 128,
    'Liga Argentina': 128,
    'Primera Division Argentina': 128,
    'Argentina': 128,
}


class AnalizadorPartidos:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(API_HEADERS)
        self.scraper = ScraperDeportivo()

    # ── API-Football helpers ───────────────────────────────────────────────────

    def _api_request(self, endpoint, params=None):
        try:
            url = f"{API_BASE_URL}/{endpoint}"
            r = self.session.get(url, params=params, timeout=10)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(2)
                return self._api_request(endpoint, params)
            return {"error": f"Status {r.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def _api_buscar_equipo(self, nombre):
        result = self._api_request("teams", {'search': nombre})
        if 'response' in result and result['response']:
            return result['response'][0]['team']
        return None

    def _api_buscar_fixture(self, team_a_id, team_b_id, liga, season):
        params = {'season': season, 'team': team_a_id}
        if liga and liga in LIGAS_IDS_API:
            params['league'] = LIGAS_IDS_API[liga]
        fixtures = self._api_request("fixtures", params)
        if 'response' not in fixtures or not fixtures['response']:
            return None
        for f in fixtures['response']:
            hid = f['teams']['home']['id']
            aid = f['teams']['away']['id']
            if team_b_id in [hid, aid]:
                return f
        return None

    def _api_buscar_partido(self, equipo_a, equipo_b, liga=None):
        """Fallback: busca partido en API-Football (solo 2022-2024)."""
        team_a = self._api_buscar_equipo(equipo_a)
        team_b = self._api_buscar_equipo(equipo_b)
        if not team_a or not team_b:
            return None, "No se encontraron los equipos en API-Football"

        for season in [2024, 2023, 2022]:
            fixture = self._api_buscar_fixture(team_a['id'], team_b['id'], liga, season)
            if fixture:
                return self._api_fixture_a_resultado(fixture), None

        # Buscar por fecha (próximos 30 días) — solo funciona en plan de pago
        hoy = datetime.now().strftime('%Y-%m-%d')
        futuro = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        params = {'team': team_a['id'], 'from': hoy, 'to': futuro}
        if liga and liga in LIGAS_IDS_API:
            params['league'] = LIGAS_IDS_API[liga]
        fixtures = self._api_request("fixtures", params)
        if 'response' in fixtures and fixtures['response']:
            for f in fixtures['response']:
                if team_b['id'] in [f['teams']['home']['id'], f['teams']['away']['id']]:
                    return self._api_fixture_a_resultado(f), None

        return None, f"No se encontró partido entre {equipo_a} y {equipo_b}"

    def _api_fixture_a_resultado(self, fixture):
        """Convierte un fixture de API-Football al formato unificado."""
        return {
            'fuente': 'api-football',
            'metadata': {
                'equipo_a': fixture['teams']['home']['name'],
                'equipo_b': fixture['teams']['away']['name'],
                'competicion': fixture['league']['name'],
                'fecha': fixture['fixture']['date'],
                'estadio': fixture['fixture'].get('venue', {}).get('name', ''),
                'arbitro': fixture['fixture'].get('referee', '') or '',
            },
            'alineaciones': {
                'confirmadas': False,
                'formacion_a': '',
                'formacion_b': '',
                'titulares_a': [],
                'titulares_b': [],
                'bajas_a': [],
                'bajas_b': [],
            },
            'estadisticas': {'equipo_a': {}, 'equipo_b': {}},
            'forma': {'forma_a': [], 'forma_b': [], 'detalle_a': [], 'detalle_b': []},
            'h2h': {'historial': [], 'resumen': {}},
            'corners': {'promedio_total_a': None, 'promedio_total_b': None},
            'tarjetas': {'promedio_amarillas_a': None, 'promedio_amarillas_b': None, 'arbitro_promedio': None},
            'recomendaciones': [{
                'tipo': 'Datos limitados (fuente histórica)',
                'razon': 'API-Football solo tiene datos hasta 2024. Se recomienda usar Sofascore para partidos actuales.',
                'confianza': 'Baja',
                'cuota_tipica': 'N/A',
            }],
            'advertencia': 'Datos obtenidos de API-Football (histórico). Para la temporada actual usa Sofascore.',
        }

    # ── Método principal ───────────────────────────────────────────────────────

    def buscar_partido(self, equipo_a, equipo_b, liga=None):
        """
        1. Intenta Sofascore (datos actuales 2025-2026)
        2. Fallback a API-Football (datos históricos 2022-2024)
        """
        # Paso 1: Sofascore
        resultado = self.scraper.buscar_partido_sofascore(equipo_a, equipo_b, liga)
        if resultado:
            return resultado, None

        # Paso 2: API-Football (fallback)
        print("[app] Sofascore falló, intentando API-Football...")
        return self._api_buscar_partido(equipo_a, equipo_b, liga)


analizador = AnalizadorPartidos()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/analizar', methods=['POST'])
def analizar():
    data = request.json
    equipo_a = data.get('equipo_a', '').strip()
    equipo_b = data.get('equipo_b', '').strip()
    liga = data.get('liga', '').strip() or None

    if not equipo_a or not equipo_b:
        return jsonify({'error': 'Faltan equipos'}), 400

    resultado, error = analizador.buscar_partido(equipo_a, equipo_b, liga)

    if error:
        return jsonify({'error': error}), 404

    return jsonify({'encontrado': True, **resultado})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
