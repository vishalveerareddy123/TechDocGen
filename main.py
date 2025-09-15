from flask import Flask, request, jsonify
import requests
import time
import tempfile
import os
import filetype
import json
import logging
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from flask_cors import CORS
app = Flask(__name__)
app.logger.setLevel(logging.DEBUG)  # Enable detailed logging
CORS(app)
# Load from environment variables (set these via export or .env)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not set in environment")

UPLOAD_START_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"
GENERATE_CONTENT_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

def get_mime_type(file_path):
    kind = filetype.guess(file_path)
    return kind.mime if kind else "application/octet-stream"

def create_session_with_retries():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

@app.route('/upload-video', methods=['POST'])
@cross_origin(origins=["http://localhost:3000"], methods=["POST", "OPTIONS"], allow_headers=["Content-Type", "Authorization"])
def upload_video():
 
    if 'video' not in request.files:
        return jsonify({'error': 'No video file part'}), 400
    video = request.files['video']
    if video.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    # Save to temp file
    temp_filepath = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            video.save(tmp_file.name)
            temp_filepath = tmp_file.name

        mime_type = get_mime_type(temp_filepath)
        num_bytes = os.path.getsize(temp_filepath)
        display_name = video.filename

        session = create_session_with_retries()

        # Step 1: Start Resumable Upload session
        headers_start = {
            "x-goog-api-key": GEMINI_API_KEY,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(num_bytes),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json",
        }
        json_body = {"file": {"display_name": display_name}}
        start_resp = session.post(UPLOAD_START_URL, headers=headers_start, json=json_body, verify=True, timeout=30)
        start_resp.raise_for_status()
        upload_url = start_resp.headers.get('x-goog-upload-url')
        if not upload_url:
            raise ValueError('No upload URL returned')

        # Step 2: Upload file data (streamed)
        headers_upload = {
            "Content-Length": str(num_bytes),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize"
        }
        with open(temp_filepath, 'rb') as f:
            upload_resp = session.post(upload_url, headers=headers_upload, data=f, verify=True, timeout=(30, 300))  # Connect timeout, read timeout
        upload_resp.raise_for_status()

        # Parse file_uri
        file_info = upload_resp.json()
        file_uri = file_info.get('file', {}).get('uri', '')
        if not file_uri:
            raise ValueError('No file URI returned')
        file_name = file_uri.split('/')[-1]

        # Step 3: Polling for processing status
        status_url = f"https://generativelanguage.googleapis.com/v1beta/files/{file_name}?key={GEMINI_API_KEY}"
        max_attempts = 60
        for attempt in range(max_attempts):
            status_resp = session.get(status_url, verify=True, timeout=30)
            status_resp.raise_for_status()
            status = status_resp.json().get("state", "")
            if status == "ACTIVE":
                break
            elif status == "FAILED":
                raise ValueError('File processing failed')
            time.sleep(5)
        else:
            raise TimeoutError('File processing timed out')

        # Step 4: Generate content
        content_prompt = (
            "Create a simple technical documentation page based on this video. "
            "Keep it under 500 words, use easy language for beginners (noobs), explain any tech terms simply, and structure it in markdown with:\n"
            "- Title\n"
            "- Short intro (what this doc covers)\n"
            "- Step-by-step guide or key concepts from the video\n"
            "- Simple visuals descriptions\n"
            "- Quick tips for new users"
            "- Try to focus on pointer if the user is pointing to something in the video\n"
            "- Try to focus on the text if the user is writing something in the video\n"
            "DON'T include any code or words like Noobs or beginners or similar words."
        )
        generation_payload = {
            "contents": [{
                "parts": [
                    {"file_data": {"mime_type": mime_type, "file_uri": file_uri}},
                    {"text": content_prompt}
                ]
            }]
        }
        generate_headers = {
            "x-goog-api-key": GEMINI_API_KEY,
            "Content-Type": "application/json"
        }
        gen_resp = session.post(GENERATE_CONTENT_URL, headers=generate_headers, json=generation_payload, verify=True, timeout=30)
        gen_resp.raise_for_status()

        gen_data = gen_resp.json()
        generated_text = ""
        try:
            candidates = gen_data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                for part in parts:
                    generated_text += part.get("text", "")
            if not generated_text:
                generated_text = "No content generated"
        except Exception as e:
            app.logger.error(f"Parsing error: {str(e)}")
            generated_text = "Failed to parse generated content"

        return jsonify({'generated_documentation': generated_text})

    except requests.RequestException as e:
        app.logger.error(f"Request error: {str(e)}")
        return jsonify({'error': 'Upload or generation failed', 'detail': str(e)}), 500
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        return jsonify({'error': 'Internal server error', 'detail': str(e)}), 500
    finally:
        if temp_filepath and os.path.exists(temp_filepath):
            os.unlink(temp_filepath)

@app.route('/', methods=['GET'])
def generate():
    return jsonify({'message': 'Generate documentation'})

if __name__ == '__main__':
    app.run(debug=True)
