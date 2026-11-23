"""Servidor local da interface com proxy para a API FastAPI na porta 8011.
Uso: python llm_frontend_5511.py [diretorio_frontend]
"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import sys

FRONTEND = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent / 'frontend'
HOST = '127.0.0.1'
PORT = 5511
API_URL = 'http://127.0.0.1:8011/api/chat'

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND), **kwargs)

    def do_POST(self):
        if self.path.split('?', 1)[0] != '/analise-cabelo-api/api/chat':
            self.send_error(404, 'Rota nao encontrada')
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 25 * 1024 * 1024:
                self.send_error(413, 'Arquivo muito grande ou vazio')
                return
            data = self.rfile.read(length)
            headers = {'Content-Type': self.headers.get('Content-Type', 'application/octet-stream')}
            request = Request(API_URL, data=data, headers=headers, method='POST')
            try:
                with urlopen(request, timeout=120) as resp:
                    status = resp.status
                    body = resp.read()
                    content_type = resp.headers.get('Content-Type', 'application/json')
            except HTTPError as err:
                status = err.code
                body = err.read()
                content_type = err.headers.get('Content-Type', 'application/json')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
        except (URLError, TimeoutError, ConnectionError):
            body = b'{"detail":"API local 8011 indisponivel. Inicie o backend."}'
            self.send_response(502)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as err:
            self.send_error(500, 'Erro no proxy local')
            print(f'Erro de proxy: {type(err).__name__}: {err}', file=sys.stderr)

if __name__ == '__main__':
    if not FRONTEND.is_dir():
        sys.exit(f'Pasta do frontend nao encontrada: {FRONTEND}')
    print('SITE LOCAL: http://127.0.0.1:5511/', flush=True)
    print('API LOCAL:  http://127.0.0.1:8011/', flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
