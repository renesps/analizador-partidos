"""
Script de prueba para el modulo de scraping.
Ejecutar con: python test_scraping.py [caso]

Casos disponibles:
  milan        - AC Milan vs Como (Serie A, feb 2026)
  madrid       - Real Madrid vs Barcelona (La Liga)
  boca         - Boca Juniors vs River Plate (Argentina)
  champions    - PSG vs Arsenal (Champions League)
  api          - Prueba directa de endpoints de Sofascore
  todos        - Ejecuta todos los casos

Ejemplo:
  python test_scraping.py milan
  python test_scraping.py todos
"""

import sys
import json
import time
from scraping_module import ScraperDeportivo, analizar_partido

# ── Utilidades de display ──────────────────────────────────────────────────────

def separador(titulo):
    print("\n" + "="*60)
    print(f"  {titulo}")
    print("="*60)

def mostrar_resultado(resultado):
    if not resultado:
        print("  [ERROR] No se obtuvo resultado")
        return

    m = resultado.get('metadata', {})
    fo = resultado.get('forma', {})
    est = resultado.get('estadisticas', {})
    al = resultado.get('alineaciones', {})
    h2h = resultado.get('h2h', {})
    cor = resultado.get('corners', {})
    tar = resultado.get('tarjetas', {})
    recs = resultado.get('recomendaciones', [])

    print(f"\n  FUENTE: {resultado.get('fuente', '?').upper()}")
    print(f"\n  PARTIDO: {m.get('equipo_a')} vs {m.get('equipo_b')}")
    print(f"  Fecha:   {m.get('fecha', '—')}")
    print(f"  Liga:    {m.get('competicion', '—')}")
    print(f"  Estadio: {m.get('estadio', '—')}")
    print(f"  Árbitro: {m.get('arbitro', '—')}")

    print(f"\n  FORMA RECIENTE:")
    print(f"    {m.get('equipo_a')}: {' '.join(fo.get('forma_a', [])) or 'Sin datos'}")
    print(f"    {m.get('equipo_b')}: {' '.join(fo.get('forma_b', [])) or 'Sin datos'}")

    if fo.get('detalle_a'):
        print(f"\n  ÚLTIMOS PARTIDOS {m.get('equipo_a')}:")
        for d in fo['detalle_a']:
            loc = 'LOCAL' if d.get('local') else 'VISITA'
            print(f"    {d.get('fecha','?')} [{loc}] vs {d.get('rival','?')} → {d.get('resultado','?')}")

    if fo.get('detalle_b'):
        print(f"\n  ÚLTIMOS PARTIDOS {m.get('equipo_b')}:")
        for d in fo['detalle_b']:
            loc = 'LOCAL' if d.get('local') else 'VISITA'
            print(f"    {d.get('fecha','?')} [{loc}] vs {d.get('rival','?')} → {d.get('resultado','?')}")

    stA = est.get('equipo_a', {})
    stB = est.get('equipo_b', {})
    if stA or stB:
        print(f"\n  ESTADÍSTICAS (últimos ~5 partidos):")
        print(f"    {'Métrica':<22} {m.get('equipo_a','A'):<20} {m.get('equipo_b','B'):<20}")
        print(f"    {'-'*60}")
        for k, label in [
            ('goles_marcados', 'Goles marcados'),
            ('goles_recibidos', 'Goles recibidos'),
            ('promedio_gf', 'Promedio GF'),
            ('promedio_gc', 'Promedio GC'),
            ('clean_sheets', 'Clean sheets'),
        ]:
            va = stA.get(k, '—')
            vb = stB.get(k, '—')
            print(f"    {label:<22} {str(va):<20} {str(vb):<20}")

    print(f"\n  ALINEACIONES (confirmadas={al.get('confirmadas', False)}):")
    tit_a = al.get('titulares_a', [])
    tit_b = al.get('titulares_b', [])
    if tit_a:
        print(f"    {m.get('equipo_a')} ({al.get('formacion_a','?')}):")
        for j in tit_a[:11]:
            cap = ' [C]' if j.get('capitan') else ''
            print(f"      #{j.get('numero','?'):>2} {j.get('posicion','?'):>2}  {j.get('nombre','?')}{cap}")
    else:
        print(f"    {m.get('equipo_a')}: alineación no disponible aún")
    if tit_b:
        print(f"    {m.get('equipo_b')} ({al.get('formacion_b','?')}):")
        for j in tit_b[:11]:
            cap = ' [C]' if j.get('capitan') else ''
            print(f"      #{j.get('numero','?'):>2} {j.get('posicion','?'):>2}  {j.get('nombre','?')}{cap}")
    else:
        print(f"    {m.get('equipo_b')}: alineación no disponible aún")

    print(f"\n  CORNERS (promedio/partido):")
    print(f"    {m.get('equipo_a')}: {cor.get('promedio_total_a', '—')}")
    print(f"    {m.get('equipo_b')}: {cor.get('promedio_total_b', '—')}")
    ca = cor.get('promedio_total_a') or 0
    cb = cor.get('promedio_total_b') or 0
    if ca and cb:
        print(f"    Total combinado: {ca + cb:.1f}")

    print(f"\n  TARJETAS AMARILLAS (promedio/partido):")
    print(f"    {m.get('equipo_a')}: {tar.get('promedio_amarillas_a', '—')}")
    print(f"    {m.get('equipo_b')}: {tar.get('promedio_amarillas_b', '—')}")

    h2h_h = h2h.get('historial', [])
    h2h_r = h2h.get('resumen', {})
    if h2h_h:
        print(f"\n  H2H ({h2h_r.get('total',0)} partidos):")
        print(f"    {m.get('equipo_a')} {h2h_r.get('victorias_a',0)} - {h2h_r.get('empates',0)} E - {h2h_r.get('victorias_b',0)} {m.get('equipo_b')}")
        print(f"    Últimos resultados:")
        for p in h2h_h[:5]:
            print(f"      {p.get('fecha','?')} | {p.get('local','?')} {p.get('resultado','?')} {p.get('visitante','?')}")

    print(f"\n  RECOMENDACIONES:")
    for rec in recs:
        conf = rec.get('confianza', '?')
        print(f"    [{conf}] {rec.get('tipo','?')}")
        print(f"      Razón: {rec.get('razon','?')}")
        print(f"      Cuota: {rec.get('cuota_tipica','?')}")
        print()


# ── Casos de prueba ────────────────────────────────────────────────────────────

def caso_milan():
    separador("CASO 1: AC Milan vs Como (Serie A)")
    resultado, error = analizar_partido("AC Milan", "Como", "Serie A")
    if error:
        print(f"  Error: {error}")
    else:
        mostrar_resultado(resultado)

def caso_madrid():
    separador("CASO 2: Real Madrid vs Barcelona (La Liga)")
    resultado, error = analizar_partido("Real Madrid", "Barcelona", "La Liga")
    if error:
        print(f"  Error: {error}")
    else:
        mostrar_resultado(resultado)

def caso_boca():
    separador("CASO 3: Boca Juniors vs River Plate (Argentina)")
    resultado, error = analizar_partido("Boca Juniors", "River Plate", "Liga Profesional Argentina")
    if error:
        print(f"  Error: {error}")
    else:
        mostrar_resultado(resultado)

def caso_champions():
    separador("CASO 4: PSG vs Arsenal (Champions League)")
    resultado, error = analizar_partido("PSG", "Arsenal", "Champions League")
    if error:
        print(f"  Error: {error}")
    else:
        mostrar_resultado(resultado)

def caso_api_directa():
    """Prueba los endpoints de Sofascore directamente."""
    separador("CASO 5: Prueba directa de API Sofascore")
    scraper = ScraperDeportivo()

    print("\n  [1] Búsqueda de equipo: 'AC Milan'")
    team = scraper.buscar_equipo_sofascore("AC Milan")
    if team:
        print(f"      OK: id={team['id']}, nombre={team['nombre']}")
    else:
        print("      ERROR: equipo no encontrado")
        return

    print(f"\n  [2] Próximos eventos del equipo id={team['id']}")
    data = scraper._proximos_eventos_equipo(team['id'], 0)
    if data and 'events' in data:
        eventos = data['events'][:3]
        for ev in eventos:
            home = ev.get('homeTeam', {}).get('name', '?')
            away = ev.get('awayTeam', {}).get('name', '?')
            ts = ev.get('startTimestamp', 0)
            from datetime import datetime
            fecha = datetime.utcfromtimestamp(ts).strftime('%d/%m/%Y %H:%M') if ts else '?'
            print(f"      {fecha} | {home} vs {away} (id={ev.get('id')})")
    else:
        print("      ERROR: sin próximos eventos")

    print("\n  [3] Búsqueda de equipo: 'Como'")
    team_b = scraper.buscar_equipo_sofascore("Como")
    if team_b:
        print(f"      OK: id={team_b['id']}, nombre={team_b['nombre']}")
    else:
        print("      ERROR: equipo no encontrado")

    print()


# ── Main ───────────────────────────────────────────────────────────────────────

CASOS = {
    'milan':      caso_milan,
    'madrid':     caso_madrid,
    'boca':       caso_boca,
    'champions':  caso_champions,
    'api':        caso_api_directa,
}

if __name__ == '__main__':
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else 'milan'

    if arg == 'todos':
        for nombre, fn in CASOS.items():
            fn()
            print("\n  (esperando 3 segundos antes del siguiente caso...)")
            time.sleep(3)
    elif arg in CASOS:
        CASOS[arg]()
    else:
        print(f"Caso '{arg}' no reconocido.")
        print("Casos disponibles:", ', '.join(list(CASOS.keys()) + ['todos']))
        sys.exit(1)

    print("\n" + "="*60)
    print("  FIN DE PRUEBAS")
    print("="*60 + "\n")
