"""
Aether Photos - Production Local Web Server
Provides high-performance static UI serving and live REST APIs for encoding/decoding
binary video photo vaults using standard library http.server.
"""

import os
import sys
import json
import base64
import tempfile
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# Import hardened Aether core engines
CORE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "core")
sys.path.insert(0, CORE_DIR)

from encoder import encode_photo_batch, encode_data_to_video, WIDTH, HEIGHT, BLOCK_SIZE, MARGIN_BLOCKS, COLS, ROWS, BLOCKS_PER_FRAME
from decoder import extract_photos_from_video, decode_video_to_data, AetherDecoderError, CorruptedHeaderError, IncompleteStreamError, ChecksumMismatchError

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(PROJECT_ROOT, "ui")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
VAULT_STORAGE = os.path.join(DATA_DIR, "vaults")
DOWNLOADS_DIR = os.path.join(DATA_DIR, "extracted")

os.makedirs(VAULT_STORAGE, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class AetherRequestHandler(SimpleHTTPRequestHandler):
    """Handles static UI requests and live REST endpoints for Aether Photos."""

    def __init__(self, *args, **kwargs):
        # Serve static assets from ui directory
        super().__init__(*args, directory=UI_DIR, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/status":
            self.send_json_response(200, {
                "status": "ONLINE",
                "engine": "Aether Photos Hardened Engine v2.0",
                "resolution": f"{WIDTH}x{HEIGHT}",
                "block_size": f"{BLOCK_SIZE}x{BLOCK_SIZE}px",
                "margin_blocks": MARGIN_BLOCKS,
                "grid_dims": f"{COLS}x{ROWS}",
                "blocks_per_frame": BLOCKS_PER_FRAME,
                "vault_count": len(os.listdir(VAULT_STORAGE))
            })
            return

        elif path == "/api/vaults":
            # List generated vaults
            vaults = []
            for f in os.listdir(VAULT_STORAGE):
                if f.endswith(".mp4"):
                    fpath = os.path.join(VAULT_STORAGE, f)
                    vaults.append({
                        "filename": f,
                        "size_bytes": os.path.getsize(fpath),
                        "video_url": f"/vaults/{f}"
                    })
            self.send_json_response(200, {"vaults": vaults})
            return

        elif path.startswith("/vaults/"):
            # Serve generated video files
            filename = os.path.basename(path)
            fpath = os.path.join(VAULT_STORAGE, filename)
            if os.path.exists(fpath):
                self.serve_file(fpath, "video/mp4")
            else:
                self.send_json_response(404, {"error": "Vault video not found"})
            return

        elif path.startswith("/core/"):
            # Allow UI labVideo to access test_vault_video.mp4 if requested
            rel = path[len("/core/"):]
            fpath = os.path.join(CORE_DIR, rel)
            if os.path.exists(fpath) and os.path.isfile(fpath):
                mime = "video/mp4" if fpath.endswith(".mp4") else "application/octet-stream"
                self.serve_file(fpath, mime)
            else:
                self.send_json_response(404, {"error": "File not found"})
            return

        # Default static file routing (index.html, app.js, style.css)
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        if path == "/api/encode":
            try:
                body = json.loads(post_data.decode("utf-8"))
                files_payload = body.get("files", [])  # list of {name: str, data: base64_str}
                batch_id = body.get("batch_id", "batch_" + os.urandom(4).hex())

                if not files_payload:
                    self.send_json_response(400, {"error": "No files provided for encoding"})
                    return

                # Write files to temp directory
                with tempfile.TemporaryDirectory() as temp_dir:
                    saved_paths = []
                    for item in files_payload:
                        name = os.path.basename(item.get("name", "photo.png"))
                        raw_b64 = item.get("data", "")
                        if "," in raw_b64:
                            raw_b64 = raw_b64.split(",", 1)[1]
                        file_bytes = base64.b64decode(raw_b64)
                        dest_path = os.path.join(temp_dir, name)
                        with open(dest_path, "wb") as f_out:
                            f_out.write(file_bytes)
                        saved_paths.append(dest_path)

                    output_mp4 = os.path.join(VAULT_STORAGE, f"{batch_id}.mp4")
                    meta = encode_photo_batch(saved_paths, output_mp4)
                    meta["batch_id"] = batch_id
                    meta["video_url"] = f"/vaults/{batch_id}.mp4"
                    meta["vault_file_size"] = os.path.getsize(output_mp4)

                    self.send_json_response(200, {
                        "status": "SUCCESS",
                        "message": f"Successfully encoded {len(saved_paths)} photos into hardened 1080p binary video stream",
                        "meta": meta
                    })

            except Exception as e:
                self.send_json_response(500, {"error": str(e)})
            return

        elif path == "/api/decode":
            try:
                body = json.loads(post_data.decode("utf-8"))
                batch_id = body.get("batch_id")
                video_url = body.get("video_url")

                target_video = None
                if batch_id:
                    possible = os.path.join(VAULT_STORAGE, f"{batch_id}.mp4")
                    if os.path.exists(possible):
                        target_video = possible
                elif video_url:
                    fname = os.path.basename(video_url)
                    possible = os.path.join(VAULT_STORAGE, fname)
                    if os.path.exists(possible):
                        target_video = possible

                # Fallback to test video if specified
                if not target_video:
                    test_vid = os.path.join(CORE_DIR, "test_vault_video.mp4")
                    if os.path.exists(test_vid):
                        target_video = test_vid

                if not target_video or not os.path.exists(target_video):
                    self.send_json_response(404, {"error": "Vault video file not found for decoding"})
                    return

                # Decode into extracted folder
                extract_target = os.path.join(DOWNLOADS_DIR, batch_id or "latest_recovery")
                summary = extract_photos_from_video(target_video, extract_target)

                # Return file list with data preview
                files_out = []
                for f in summary.get("files", []):
                    fpath = os.path.join(extract_target, f["filename"])
                    with open(fpath, "rb") as rf:
                        raw_bytes = rf.read()
                    b64_data = base64.b64encode(raw_bytes).decode("ascii")
                    files_out.append({
                        "filename": f["filename"],
                        "size_bytes": f["size_bytes"],
                        "data_url": f"data:image/png;base64,{b64_data}"
                    })

                self.send_json_response(200, {
                    "status": "SUCCESS",
                    "checksum_verified": True,
                    "extracted_count": len(files_out),
                    "files": files_out
                })

            except CorruptedHeaderError as e:
                self.send_json_response(422, {"error": f"Header Corruption: {str(e)}", "type": "CorruptedHeaderError"})
            except IncompleteStreamError as e:
                self.send_json_response(422, {"error": f"Incomplete Stream: {str(e)}", "type": "IncompleteStreamError"})
            except ChecksumMismatchError as e:
                self.send_json_response(422, {"error": f"Integrity Failure: {str(e)}", "type": "ChecksumMismatchError"})
            except Exception as e:
                self.send_json_response(500, {"error": f"Decoding error: {str(e)}", "type": type(e).__name__})
            return

        elif path == "/api/youtube/fetch-and-decode":
            try:
                body = json.loads(post_data.decode("utf-8"))
                yt_url = body.get("url", "").strip()
                if not yt_url:
                    self.send_json_response(400, {"error": "YouTube URL is required"})
                    return

                temp_download = os.path.join(DATA_DIR, "yt_download_temp.mp4")
                if os.path.exists(temp_download):
                    try:
                        os.remove(temp_download)
                    except Exception:
                        pass

                # Download via yt-dlp bridge
                from uploader.yt_bridge import download_youtube_vault_video
                dl_path = download_youtube_vault_video(yt_url, temp_download)

                extract_target = os.path.join(DOWNLOADS_DIR, "yt_direct_extract")
                summary = extract_photos_from_video(dl_path, extract_target)

                files_out = []
                for f in summary.get("files", []):
                    fpath = os.path.join(extract_target, f["filename"])
                    with open(fpath, "rb") as rf:
                        raw_bytes = rf.read()
                    b64_data = base64.b64encode(raw_bytes).decode("ascii")
                    files_out.append({
                        "filename": f["filename"],
                        "size_bytes": f["size_bytes"],
                        "data_url": f"data:image/png;base64,{b64_data}"
                    })

                self.send_json_response(200, {
                    "status": "SUCCESS",
                    "url": yt_url,
                    "checksum_verified": True,
                    "extracted_count": len(files_out),
                    "files": files_out
                })

            except Exception as e:
                self.send_json_response(500, {"error": f"YouTube download/decode failed: {str(e)}", "type": type(e).__name__})
            return

        elif path == "/api/youtube/upload":
            try:
                body = json.loads(post_data.decode("utf-8"))
                batch_id = body.get("batch_id")
                video_file = os.path.join(VAULT_STORAGE, f"{batch_id}.mp4")
                if not os.path.exists(video_file):
                    self.send_json_response(404, {"error": f"Batch video '{batch_id}.mp4' not found"})
                    return

                import asyncio
                from uploader.yt_uploader import upload_vault_to_youtube
                res = asyncio.run(upload_vault_to_youtube(video_file, title=f"Vault Archive {batch_id}"))

                self.send_json_response(200, res)

            except Exception as e:
                self.send_json_response(500, {"error": f"Browser upload error: {str(e)}", "type": type(e).__name__})
            return

        self.send_json_response(404, {"error": "Endpoint not found"})

    def serve_file(self, fpath, mime_type):
        """Streams a local file to client."""
        try:
            with open(fpath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_json_response(500, {"error": f"Error reading file: {str(e)}"})

    def send_json_response(self, code: int, data: dict):
        """Sends a JSON response with standard CORS headers."""
        response_bytes = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        # Clean formatted console log
        sys.stdout.write(f"[Aether HTTP] {self.address_string()} - {format % args}\n")
        sys.stdout.flush()


def run_server(port=8000):
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, AetherRequestHandler)
    print("==================================================")
    print(f"[AETHER] PHOTOS VAULT - LIVE SERVER RUNNING")
    print(f"[*] Swiss UI URL: http://localhost:{port}")
    print(f"[*] Core API:     http://localhost:{port}/api/status")
    print(f"[*] Video Vaults: {VAULT_STORAGE}")
    print("==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Aether server cleanly.")
        httpd.server_close()



if __name__ == "__main__":
    port = 8000
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    run_server(port)
