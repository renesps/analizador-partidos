from flask import Flask, render_template, request, jsonify
import requests

app = Flask(__name__)

# Headers que simulan un browser real para que Sofascore no bloquee
SF_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'es-ES,es;q=0.9',
    'Referer': 'https://www.sofascore.com/',
    'Origin': 'https://www.sofascore.com',
    'Cache-Control': 'no-cache',
}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/sf')
def proxy():
    """Proxy para Sofascore: el browser llama a /sf?path=/search/all?q=Milan
       y este endpoint reenvía la request a Sofascore con headers de browser real."""
    path = request.args.get('path', '')
    if not path or not path.startswith('/'):
        return jsonify({'error': 'path invalido'}), 400

    url = 'https://api.sofascore.com/api/v1' + path
    try:
        r = requests.get(url, headers=SF_HEADERS, timeout=10)
        # Devolvemos el JSON tal cual, con los mismos headers de tipo
        return app.response_class(
            response=r.content,
            status=r.status_code,
            mimetype='application/json'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 502

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
