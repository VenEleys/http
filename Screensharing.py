import mss
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO
from PIL import Image

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<img src="/s.jpg"><script>setInterval(()=>location.reload(),1000)</script>')
        else:
            with mss.mss() as sct:
                img = sct.grab(sct.monitors[1])
                buf = BytesIO()
                Image.frombytes('RGB', img.size, img.rgb).save(buf, 'JPEG')
                self.send_response(200)
                self.send_header('Content-type', 'image/jpeg')
                self.end_headers()
                self.wfile.write(buf.getvalue())

print("Threading...")
HTTPServer(('', 8000), Handler).serve_forever()