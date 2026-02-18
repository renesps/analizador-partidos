from flask import Flask, render_template, request, jsonify
import cloudscraper

app = Flask(__name__)

# cloudscraper bypasea el challenge de Cloudflare que usa Sofascore
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'android', 'mobile': True}
)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/sf')
def proxy():
    """Proxy para Sofascore usando cloudscraper para bypass de Cloudflare."""
    path = request.args.get('path', '')
    if not path or not path.startswith('/'):
        return jsonify({'error': 'path invalido'}), 400

    url = 'https://api.sofascore.com/api/v1' + path
    try:
        r = scraper.get(url, timeout=10)
        return app.response_class(
            response=r.content,
            status=r.status_code,
            mimetype='application/json'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 502

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
