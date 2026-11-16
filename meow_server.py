"""
Meow Music helper server.

- Serves this folder on http://localhost:8000
- Redirects / (and any directory listing) straight to meow-music.html
- Adds /related?id=VIDEO_ID, which asks YouTube Music for that song's
  "radio" (up-next) queue via ytmusicapi. No account or key needed.

Setup (once):   pip install ytmusicapi
Run:            python meow_server.py
Keep it running while you listen.
"""
import json
import os
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = 8000
PAGE = "meow-music.html"
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

try:
    from ytmusicapi import YTMusic
    ytm = YTMusic()
except Exception as e:  # keeps the player working even if the library is missing
    ytm = None
    print("WARNING: ytmusicapi not available (%s). Run: pip install ytmusicapi" % e)


def to_seconds(t):
    if t.get("length_seconds"):
        return int(t["length_seconds"])
    parts = str(t.get("length") or "").split(":")
    try:
        secs = 0
        for p in parts:
            secs = secs * 60 + int(p)
        return secs
    except ValueError:
        return 0


def related(video_id):
    data = ytm.get_watch_playlist(videoId=video_id, radio=True, limit=25)
    out = []
    for t in data.get("tracks", []):
        vid = t.get("videoId")
        if not vid or vid == video_id:
            continue
        artists = ", ".join(a["name"] for a in (t.get("artists") or []) if a.get("name"))
        out.append({
            "id": vid,
            "title": t.get("title", ""),
            "artist": artists,
            "dur": to_seconds(t),
        })
    return out


class Handler(SimpleHTTPRequestHandler):
    def redirect(self):
        self.send_response(302)
        self.send_header("Location", "/" + PAGE)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def list_directory(self, path):  # never show "Directory listing for /"
        self.redirect()
        return None

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("", "/", "/index.html"):
            return self.redirect()
        if url.path == "/related":
            return self.handle_related(url)
        return super().do_GET()

    def handle_related(self, url):
        vid = (parse_qs(url.query).get("id") or [""])[0]
        status, body = 200, []
        if not ytm:
            status, body = 503, {"error": "ytmusicapi not installed"}
        elif len(vid) != 11:
            status, body = 400, {"error": "bad id"}
        else:
            try:
                body = related(vid)
            except Exception as e:
                status, body = 502, {"error": str(e)}
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass  # quiet


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = "http://localhost:%d/" % PORT
    print("Meow Music running at", url, "(Ctrl+C to stop)")
    threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye!")
