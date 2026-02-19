from flask import Flask, render_template, request, jsonify
import os, requests

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
    # Pasar la key al template para que el browser llame a OpenRouter directamente
    # Esto evita el timeout de 30s de Render free en llamadas largas a Kimi
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
