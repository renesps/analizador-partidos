"""
Modulo de scraping para datos de partidos de futbol.
Fuentes: Sofascore API no oficial, con fallback a API-Football.
Uso personal/educativo solamente.
"""

import requests
import time
import random
import json
import re
from datetime import datetime, timedelta
from functools import wraps

# ── User-Agents para rotación ──────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# ── Mapeo de ligas a IDs de Sofascore ─────────────────────────────────────────
SOFASCORE_LEAGUE_IDS = {
    'Premier League':            17,
    'La Liga':                   8,
    'Serie A':                   23,
    'Bundesliga':                35,
    'Ligue 1':                   34,
    'Champions League':          7,
    'Primeira Liga':             238,
    'Liga Portugal':             238,
    'Copa Libertadores':         384,
    'Libertadores':              384,
    'Copa Sudamericana':         480,
    'Sudamericana':              480,
    'Super Lig':                 52,
    'Süper Lig':                 52,
    'Liga Profesional Argentina': 406,
    'Liga Argentina':            406,
}

# Delay mínimo entre requests a Sofascore (en segundos)
MIN_DELAY = 1.5
MAX_DELAY = 3.0


def _retry(max_attempts=3, base_delay=2.0):
    """Decorador de reintentos con backoff exponencial."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    result = func(*args, **kwargs)
                    if result is not None:
                        return result
                except requests.exceptions.Timeout:
                    pass
                except requests.exceptions.ConnectionError:
                    pass
                except Exception:
                    pass
                if attempt < max_attempts - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


class ScraperDeportivo:
    """
    Scraper de datos de partidos de fútbol usando la API no oficial de Sofascore.
    Solo para uso personal/educativo.
    """

    def __init__(self):
        self.session = requests.Session()
        self._rotate_headers()
        self._last_request_time = 0
        self._cache = {}

    # ── Gestión de sesión ──────────────────────────────────────────────────────

    def _rotate_headers(self):
        ua = random.choice(USER_AGENTS)
        self.session.headers.update({
            'User-Agent': ua,
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://www.sofascore.com',
            'Referer': 'https://www.sofascore.com/',
            'Cache-Control': 'no-cache',
        })

    def _wait(self):
        """Respeta rate limit mínimo entre requests."""
        elapsed = time.time() - self._last_request_time
        wait = random.uniform(MIN_DELAY, MAX_DELAY) - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_time = time.time()

    # ── Request base ───────────────────────────────────────────────────────────

    def _get(self, url, params=None, timeout=15):
        """Realiza GET con manejo de errores, rate limiting y rotación de UA."""
        self._wait()
        self._rotate_headers()
        try:
            r = self.session.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(10)
                return self._get(url, params, timeout)
            return None
        except Exception:
            return None

    # ── Cache ──────────────────────────────────────────────────────────────────

    def _cache_get(self, key):
        entry = self._cache.get(key)
        if entry and (time.time() - entry['ts']) < 600:
            return entry['data']
        return None

    def _cache_set(self, key, data):
        self._cache[key] = {'data': data, 'ts': time.time()}

    # ── Búsqueda de equipo ─────────────────────────────────────────────────────

    @_retry(max_attempts=3)
    def buscar_equipo_sofascore(self, nombre):
        """Busca un equipo en Sofascore y retorna su ID y nombre oficial."""
        cache_key = f"team_{nombre}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        url = "https://api.sofascore.com/api/v1/search/all"
        data = self._get(url, params={'q': nombre})

        if not data or 'results' not in data:
            return None

        for item in data['results']:
            if item.get('type') == 'team':
                entity = item.get('entity', {})
                result = {
                    'id': entity.get('id'),
                    'nombre': entity.get('name'),
                    'slug': entity.get('slug', ''),
                }
                self._cache_set(cache_key, result)
                return result

        return None

    # ── Próximos partidos de un equipo ─────────────────────────────────────────

    @_retry(max_attempts=3)
    def _proximos_eventos_equipo(self, team_id, pagina=0):
        """Retorna los próximos eventos de un equipo (paginado)."""
        url = f"https://api.sofascore.com/api/v1/team/{team_id}/events/next/{pagina}"
        return self._get(url)

    @_retry(max_attempts=3)
    def _ultimos_eventos_equipo(self, team_id, pagina=0):
        """Retorna los últimos eventos de un equipo (paginado)."""
        url = f"https://api.sofascore.com/api/v1/team/{team_id}/events/last/{pagina}"
        return self._get(url)

    # ── Buscar partido entre dos equipos ──────────────────────────────────────

    def buscar_partido_sofascore(self, equipo_a, equipo_b, liga=None):
        """
        Busca el partido entre dos equipos en Sofascore.
        Retorna un dict con todos los datos disponibles o None.
        """
        print(f"[Sofascore] Buscando: {equipo_a} vs {equipo_b}")

        team_a = self.buscar_equipo_sofascore(equipo_a)
        team_b = self.buscar_equipo_sofascore(equipo_b)

        if not team_a or not team_b:
            print(f"[Sofascore] No se encontraron equipos: {team_a}, {team_b}")
            return None

        print(f"[Sofascore] Equipo A: {team_a['nombre']} (id={team_a['id']})")
        print(f"[Sofascore] Equipo B: {team_b['nombre']} (id={team_b['id']})")

        # Buscar en próximos partidos del equipo A (páginas 0 y 1)
        evento = None
        for pagina in [0, 1]:
            data = self._proximos_eventos_equipo(team_a['id'], pagina)
            if not data or 'events' not in data:
                continue
            for ev in data['events']:
                home_id = ev.get('homeTeam', {}).get('id')
                away_id = ev.get('awayTeam', {}).get('id')
                if team_b['id'] in [home_id, away_id]:
                    evento = ev
                    break
            if evento:
                break

        if not evento:
            print("[Sofascore] Partido no encontrado en próximos eventos")
            return None

        event_id = evento['id']
        print(f"[Sofascore] Evento encontrado: id={event_id}")

        # Recolectar datos en paralelo (secuencialmente por rate limit)
        resultado = self._construir_resultado(evento, event_id, team_a, team_b)
        return resultado

    # ── Construcción del resultado ─────────────────────────────────────────────

    def _construir_resultado(self, evento, event_id, team_a, team_b):
        """Ensambla el dict de resultado con todos los datos del partido."""

        # Metadata básica
        ts = evento.get('startTimestamp', 0)
        fecha_dt = datetime.utcfromtimestamp(ts) if ts else None
        fecha_str = fecha_dt.strftime('%Y-%m-%dT%H:%M:%S+00:00') if fecha_dt else None

        resultado = {
            'fuente': 'sofascore',
            'metadata': {
                'equipo_a': evento.get('homeTeam', {}).get('name', team_a['nombre']),
                'equipo_b': evento.get('awayTeam', {}).get('name', team_b['nombre']),
                'competicion': evento.get('tournament', {}).get('name', ''),
                'fecha': fecha_str,
                'estadio': evento.get('venue', {}).get('stadium', {}).get('name', ''),
                'arbitro': '',
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
            'estadisticas': {
                'equipo_a': {},
                'equipo_b': {},
            },
            'forma': {
                'forma_a': [],
                'forma_b': [],
                'detalle_a': [],
                'detalle_b': [],
            },
            'h2h': {
                'historial': [],
                'resumen': {},
            },
            'corners': {
                'promedio_total_a': None,
                'promedio_total_b': None,
            },
            'tarjetas': {
                'promedio_amarillas_a': None,
                'promedio_amarillas_b': None,
                'arbitro_promedio': None,
            },
            'recomendaciones': [],
        }

        # Alineaciones
        lineups = self._get_lineups(event_id)
        if lineups:
            resultado['alineaciones'] = self._parsear_alineaciones(lineups)

        # Forma reciente (últimos 5 partidos de cada equipo)
        forma_a, stats_a = self._forma_y_stats(team_a['id'], 'A')
        forma_b, stats_b = self._forma_y_stats(team_b['id'], 'B')
        resultado['forma']['forma_a'] = forma_a.get('forma', [])
        resultado['forma']['detalle_a'] = forma_a.get('detalle', [])
        resultado['forma']['forma_b'] = forma_b.get('forma', [])
        resultado['forma']['detalle_b'] = forma_b.get('detalle', [])

        # Estadísticas de temporada
        if stats_a:
            resultado['estadisticas']['equipo_a'] = stats_a
        if stats_b:
            resultado['estadisticas']['equipo_b'] = stats_b

        # Corners y tarjetas (calculados desde últimos partidos)
        corners_a = self._promedios_corners_tarjetas(team_a['id'], 'home')
        corners_b = self._promedios_corners_tarjetas(team_b['id'], 'away')
        resultado['corners']['promedio_total_a'] = corners_a.get('corners')
        resultado['corners']['promedio_total_b'] = corners_b.get('corners')
        resultado['tarjetas']['promedio_amarillas_a'] = corners_a.get('amarillas')
        resultado['tarjetas']['promedio_amarillas_b'] = corners_b.get('amarillas')

        # H2H
        h2h_data = self._get_h2h(event_id)
        if h2h_data:
            resultado['h2h'] = self._parsear_h2h(h2h_data, team_a['nombre'], team_b['nombre'])

        # Árbitro desde prefetch
        prefetch = self._get_prefetch(event_id)
        if prefetch:
            arbitro = self._extraer_arbitro(prefetch)
            if arbitro:
                resultado['metadata']['arbitro'] = arbitro

        # Recomendaciones
        resultado['recomendaciones'] = self._generar_recomendaciones(resultado)

        return resultado

    # ── Alineaciones ───────────────────────────────────────────────────────────

    @_retry(max_attempts=3)
    def _get_lineups(self, event_id):
        url = f"https://api.sofascore.com/api/v1/event/{event_id}/lineups"
        return self._get(url)

    def _parsear_alineaciones(self, data):
        alineaciones = {
            'confirmadas': data.get('confirmed', False),
            'formacion_a': '',
            'formacion_b': '',
            'titulares_a': [],
            'titulares_b': [],
            'bajas_a': [],
            'bajas_b': [],
        }

        for lado, key in [('home', 'A'), ('away', 'B')]:
            equipo = data.get(lado, {})
            formacion = equipo.get('formation', '')
            jugadores = []
            for p in equipo.get('players', []):
                jugador = p.get('player', {})
                jugadores.append({
                    'nombre': jugador.get('name', ''),
                    'posicion': p.get('position', ''),
                    'numero': p.get('shirtNumber', ''),
                    'capitan': p.get('captain', False),
                    'suplente': p.get('substitute', False),
                })
            titulares = [j for j in jugadores if not j['suplente']]

            if key == 'A':
                alineaciones['formacion_a'] = formacion
                alineaciones['titulares_a'] = titulares
            else:
                alineaciones['formacion_b'] = formacion
                alineaciones['titulares_b'] = titulares

        return alineaciones

    # ── Forma reciente y estadísticas ──────────────────────────────────────────

    def _forma_y_stats(self, team_id, label):
        """Obtiene forma de los últimos 5 partidos y calcula stats básicas."""
        forma = {'forma': [], 'detalle': []}
        stats = {}

        data = self._ultimos_eventos_equipo(team_id, 0)
        if not data or 'events' not in data:
            return forma, stats

        partidos = [e for e in data['events'] if e.get('status', {}).get('code') == 100]
        partidos = partidos[-5:]  # últimos 5

        goles_favor = []
        goles_contra = []
        corners_total = []
        amarillas = []

        for ev in partidos:
            home_id = ev.get('homeTeam', {}).get('id')
            es_local = (home_id == team_id)
            score_home = ev.get('homeScore', {}).get('current', 0) or 0
            score_away = ev.get('awayScore', {}).get('current', 0) or 0

            gf = score_home if es_local else score_away
            gc = score_away if es_local else score_home
            goles_favor.append(gf)
            goles_contra.append(gc)

            if gf > gc:
                forma['forma'].append('V')
            elif gf == gc:
                forma['forma'].append('E')
            else:
                forma['forma'].append('D')

            rival = ev.get('awayTeam', {}).get('name') if es_local else ev.get('homeTeam', {}).get('name')
            ts = ev.get('startTimestamp', 0)
            fecha = datetime.utcfromtimestamp(ts).strftime('%d/%m') if ts else ''
            forma['detalle'].append({
                'rival': rival,
                'resultado': f"{gf}-{gc}",
                'fecha': fecha,
                'local': es_local,
            })

        if goles_favor:
            n = len(goles_favor)
            stats = {
                'goles_marcados': sum(goles_favor),
                'goles_recibidos': sum(goles_contra),
                'promedio_gf': round(sum(goles_favor) / n, 2),
                'promedio_gc': round(sum(goles_contra) / n, 2),
                'clean_sheets': sum(1 for g in goles_contra if g == 0),
                'partidos_analizados': n,
            }

        return forma, stats

    # ── Promedios de corners y tarjetas ───────────────────────────────────────

    def _promedios_corners_tarjetas(self, team_id, rol='home', n_partidos=10):
        """
        Calcula promedios de corners y tarjetas de los últimos n_partidos.
        Obtiene estadísticas individuales de cada partido.
        """
        corners_list = []
        amarillas_list = []

        # Últimos partidos (dos páginas para tener ~10)
        eventos = []
        for pagina in [0, 1]:
            data = self._ultimos_eventos_equipo(team_id, pagina)
            if data and 'events' in data:
                terminados = [e for e in data['events'] if e.get('status', {}).get('code') == 100]
                eventos.extend(terminados)
            if len(eventos) >= n_partidos:
                break

        eventos = eventos[-n_partidos:]

        for ev in eventos:
            eid = ev.get('id')
            if not eid:
                continue
            stats = self._get_event_stats(eid)
            if not stats:
                continue

            home_id = ev.get('homeTeam', {}).get('id')
            es_local = (home_id == team_id)
            lado = 'home' if es_local else 'away'

            for grupo in stats:
                for item in grupo.get('groups', []):
                    for stat in item.get('statisticsItems', []):
                        nombre = stat.get('name', '').lower()
                        valor_raw = stat.get(lado, '0') or '0'
                        try:
                            valor = float(str(valor_raw).replace(',', '.'))
                        except ValueError:
                            continue

                        if 'corner' in nombre:
                            corners_list.append(valor)
                        if 'yellow' in nombre or 'amarill' in nombre:
                            amarillas_list.append(valor)

        resultado = {}
        if corners_list:
            resultado['corners'] = round(sum(corners_list) / len(corners_list), 1)
        if amarillas_list:
            resultado['amarillas'] = round(sum(amarillas_list) / len(amarillas_list), 1)

        return resultado

    @_retry(max_attempts=2)
    def _get_event_stats(self, event_id):
        url = f"https://api.sofascore.com/api/v1/event/{event_id}/statistics"
        data = self._get(url)
        if data and 'statistics' in data:
            return data['statistics']
        return None

    # ── H2H ───────────────────────────────────────────────────────────────────

    @_retry(max_attempts=3)
    def _get_h2h(self, event_id):
        url = f"https://api.sofascore.com/api/v1/event/{event_id}/h2h"
        return self._get(url)

    def _parsear_h2h(self, data, nombre_a, nombre_b):
        historial = []
        victorias_a = 0
        victorias_b = 0
        empates = 0

        eventos = data.get('events', [])[:10]

        for ev in eventos:
            home = ev.get('homeTeam', {}).get('name', '')
            away = ev.get('awayTeam', {}).get('name', '')
            sh = ev.get('homeScore', {}).get('current', 0) or 0
            sa = ev.get('awayScore', {}).get('current', 0) or 0
            ts = ev.get('startTimestamp', 0)
            fecha = datetime.utcfromtimestamp(ts).strftime('%d/%m/%Y') if ts else ''
            comp = ev.get('tournament', {}).get('name', '')

            historial.append({
                'local': home,
                'visitante': away,
                'resultado': f"{sh}-{sa}",
                'fecha': fecha,
                'competicion': comp,
            })

            if sh > sa:
                if nombre_a.lower() in home.lower():
                    victorias_a += 1
                else:
                    victorias_b += 1
            elif sh < sa:
                if nombre_a.lower() in away.lower():
                    victorias_a += 1
                else:
                    victorias_b += 1
            else:
                empates += 1

        return {
            'historial': historial,
            'resumen': {
                'victorias_a': victorias_a,
                'victorias_b': victorias_b,
                'empates': empates,
                'total': len(historial),
            },
        }

    # ── Prefetch / árbitro ────────────────────────────────────────────────────

    @_retry(max_attempts=2)
    def _get_prefetch(self, event_id):
        url = f"https://api.sofascore.com/api/v1/event/{event_id}"
        return self._get(url)

    def _extraer_arbitro(self, data):
        evento = data.get('event', {})
        referee = evento.get('referee', {})
        return referee.get('name', '')

    # ── Recomendaciones de apuestas ───────────────────────────────────────────

    def _generar_recomendaciones(self, resultado):
        """
        Genera recomendaciones de apuestas con cuota ~1.80 basadas en datos.
        AVISO: Solo orientativo. Las apuestas conllevan riesgo de pérdida.
        """
        recomendaciones = []
        forma_a = resultado['forma'].get('forma_a', [])
        forma_b = resultado['forma'].get('forma_b', [])
        stats_a = resultado['estadisticas'].get('equipo_a', {})
        stats_b = resultado['estadisticas'].get('equipo_b', {})
        corners_a = resultado['corners'].get('promedio_total_a')
        corners_b = resultado['corners'].get('promedio_total_b')
        h2h_resumen = resultado['h2h'].get('resumen', {})

        # 1. Ambos anotan (BTTS)
        goles_recibidos_a = stats_a.get('promedio_gc', 0)
        goles_favor_b = stats_b.get('promedio_gf', 0)
        if goles_recibidos_a and goles_favor_b:
            if goles_recibidos_a > 0.8 and goles_favor_b > 0.8:
                recomendaciones.append({
                    'tipo': 'Ambos Equipos Marcan (SI)',
                    'razon': f"Local recibe {goles_recibidos_a:.1f} goles/partido, visitante marca {goles_favor_b:.1f}",
                    'confianza': 'Media',
                    'cuota_tipica': '1.75-1.90',
                })

        # 2. Más de X corners
        if corners_a and corners_b:
            total_corners = corners_a + corners_b
            if total_corners > 9:
                recomendaciones.append({
                    'tipo': f'Más de 9.5 corners',
                    'razon': f"Promedio combinado: {total_corners:.1f} corners por partido",
                    'confianza': 'Media-Alta' if total_corners > 10.5 else 'Media',
                    'cuota_tipica': '1.75-1.85',
                })

        # 3. Forma del equipo local
        victorias_a = forma_a.count('V')
        if victorias_a >= 3:
            recomendaciones.append({
                'tipo': 'Victoria Local',
                'razon': f"{resultado['metadata']['equipo_a']} ganó {victorias_a} de sus últimos {len(forma_a)} partidos",
                'confianza': 'Media' if victorias_a == 3 else 'Media-Alta',
                'cuota_tipica': '1.70-1.90',
            })

        # 4. Más de 2.5 goles
        gf_a = stats_a.get('promedio_gf', 0)
        gf_b = stats_b.get('promedio_gf', 0)
        if gf_a and gf_b and (gf_a + gf_b) > 2.8:
            recomendaciones.append({
                'tipo': 'Más de 2.5 goles',
                'razon': f"Promedios ofensivos: {gf_a:.1f} + {gf_b:.1f} = {gf_a+gf_b:.1f} goles/partido",
                'confianza': 'Media',
                'cuota_tipica': '1.75-1.85',
            })

        # 5. H2H dominancia
        total_h2h = h2h_resumen.get('total', 0)
        victorias_h2h_a = h2h_resumen.get('victorias_a', 0)
        if total_h2h >= 5 and victorias_h2h_a / total_h2h >= 0.6:
            recomendaciones.append({
                'tipo': 'Ventaja histórica Local',
                'razon': f"{resultado['metadata']['equipo_a']} ganó {victorias_h2h_a}/{total_h2h} enfrentamientos directos",
                'confianza': 'Media',
                'cuota_tipica': '1.75-1.90',
            })

        if not recomendaciones:
            recomendaciones.append({
                'tipo': 'Sin recomendación clara',
                'razon': 'Datos insuficientes o partido muy equilibrado',
                'confianza': 'Baja',
                'cuota_tipica': 'N/A',
            })

        return recomendaciones


# ── Función utilitaria de alto nivel ──────────────────────────────────────────

def analizar_partido(equipo_a, equipo_b, liga=None):
    """
    Función principal: busca y analiza un partido.
    Retorna (dict_resultado, error_str).
    """
    scraper = ScraperDeportivo()
    resultado = scraper.buscar_partido_sofascore(equipo_a, equipo_b, liga)
    if resultado:
        return resultado, None
    return None, f"No se encontró el partido {equipo_a} vs {equipo_b} en Sofascore"
