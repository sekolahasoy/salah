import os
import re
import uuid
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, after_this_request
from yt_dlp import YoutubeDL

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024  # 1 MB form payload limit


def sanitize_filename(name: str) -> str:
    """Keep filenames safe and readable."""
    name = re.sub(r"[^\w\s.-]", "", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:150] if name else "download"


def get_video_info(url: str) -> dict:
    """Extract metadata without downloading."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info


def download_with_ytdlp(url: str, mode: str) -> tuple[str, str]:
    """
    Download content based on mode.
    Returns: (saved_filename, message)
    """
    info = get_video_info(url)
    title = sanitize_filename(info.get("title", "youtube_download"))
    task_id = uuid.uuid4().hex[:8]
    base_output = str(DOWNLOAD_DIR / f"{title}_{task_id}.%(ext)s")

    if mode == "mp4":
        ydl_opts = {
            "outtmpl": base_output,
            "format": "bv*+ba/b",
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }

    elif mode == "mp3":
        ydl_opts = {
            "outtmpl": base_output,
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }

    elif mode == "subtitle":
        # Downloads subtitle file only if available
        ydl_opts = {
            "outtmpl": base_output,
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["id", "en", "all"],
            "subtitlesformat": "srt/vtt/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }

    elif mode == "thumbnail":
        ydl_opts = {
            "outtmpl": base_output,
            "skip_download": True,
            "writethumbnail": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }

    else:
        raise ValueError("Invalid download mode.")

    before = set(os.listdir(DOWNLOAD_DIR))

    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    after = set(os.listdir(DOWNLOAD_DIR))
    new_files = sorted(list(after - before), key=lambda x: os.path.getmtime(DOWNLOAD_DIR / x), reverse=True)

    if not new_files:
        raise RuntimeError("No file was produced. The media may be unavailable or blocked.")

    saved_file = new_files[0]
    return saved_file, f"{mode.upper()} downloaded successfully."


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


@app.route("/download", methods=["POST"])
def download():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    mode = (data.get("mode") or "").strip().lower()

    if not url:
        return jsonify({"success": False, "error": "URL is required."}), 400

    if mode not in {"mp3", "mp4", "subtitle", "thumbnail"}:
        return jsonify({"success": False, "error": "Invalid download option."}), 400

    try:
        filename, message = download_with_ytdlp(url, mode)
        return jsonify({
            "success": True,
            "message": message,
            "filename": filename,
            "download_url": f"/file/{filename}"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/file/<path:filename>")
def serve_file(filename):
    file_path = DOWNLOAD_DIR / filename

    @after_this_request
    def remove_file(response):
        try:
            os.remove(file_path)
        except Exception:
            pass
        return response

    return send_file(file_path, as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
