import os
import re
import time
import json
import wave
import base64
import requests
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, send_file, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')

# --- Gemini TTS 設定 ---
API_KEY = os.environ.get("GEMINI_API_KEY")
TTS_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# 出力フォーマット
OUTPUT_SAMPLING_RATE = 44100

VOICE_ID_man = 0
VOICE_ID_woman = 1

def clean_text(text):
    """テキストをクリーニング"""
    text = re.sub(r'^セリフ:\s*', '', text)
    return text.strip()

def get_text_file_path():
    return os.path.join(os.path.dirname(__file__), "text.txt")

def get_output_directory():
    output_dir = os.environ.get('AUDIO_OUTPUT_DIR', os.path.join(os.path.dirname(__file__), 'audio_output'))
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def generate_filename():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"voice_dialogue_{timestamp}.wav"

def combine_wav_files(wav_files, output_path):
    """複数のWAVファイルを結合"""
    if not wav_files:
        raise ValueError("wav_files is empty")
    with wave.open(wav_files[0], 'rb') as first_file:
        params = first_file.getparams()
        n_channels = first_file.getnchannels()
        sample_width = first_file.getsampwidth()
        frame_rate = first_file.getframerate()

    with wave.open(output_path, 'wb') as output_file:
        output_file.setparams(params)
        for i, wav_file in enumerate(wav_files):
            with wave.open(wav_file, 'rb') as infile:
                frames = infile.readframes(infile.getnframes())
                output_file.writeframes(frames)
                if i != len(wav_files) - 1:
                    silence_duration = 0.5
                    silence_frames = int(silence_duration * frame_rate)
                    silence_data = b'\x00' * (silence_frames * n_channels * sample_width)
                    output_file.writeframes(silence_data)

def synthesize_text_with_gemini(text):
    """
    Gemini AI Studio TTS を呼び出して音声を生成する
    """
    headers = {"Content-Type": "application/json", "X-goog-api-key": API_KEY}
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {"responseMimeType": "audio/wav"}
    }
    try:
        r = requests.post(TTS_URL, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        audio_b64 = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        audio_bytes = base64.b64decode(audio_b64)
    except Exception as e:
        print(f"Gemini TTS failed: {e}")
        return None

    temp_filename = f"temp_gemini_{int(time.time()*1000)}.wav"
    with open(temp_filename, "wb") as out_f:
        out_f.write(audio_bytes)
    return temp_filename

def synthesize_dialogue(lines):
    temp_files = []
    for idx, line in enumerate(lines):
        cleaned = clean_text(line["text"])
        if not cleaned:
            continue
        print(f"Synthesizing line {idx}: {cleaned}")
        tmp = synthesize_text_with_gemini(cleaned)
        if tmp:
            temp_files.append(tmp)
        else:
            print(f"Failed to synthesize line {idx}")

    if not temp_files:
        return None, "音声ファイルが生成できませんでした（Gemini TTS エラー）"

    output_dir = get_output_directory()
    output_filename = generate_filename()
    output_path = os.path.join(output_dir, output_filename)
    combine_wav_files(temp_files, output_path)

    for t in temp_files:
        try:
            os.remove(t)
        except Exception:
            pass

    return output_path, None

def parse_text_content(text_content):
    """text.txt を行データに変換"""
    lines = []
    current_speaker = None
    current_text = []

    for raw in text_content.splitlines():
        text = raw.strip()
        if not text:
            continue
        speaker_match = re.match(r'\[(男性|女性)\]', text)
        if speaker_match:
            if current_speaker is not None and current_text:
                speaker_id = VOICE_ID_man if current_speaker == "男性" else VOICE_ID_woman
                lines.append({"text": " ".join(current_text), "id": speaker_id})
                current_text = []
            current_speaker = speaker_match.group(1)
            continue

        if current_speaker is not None:
            current_text.append(text)

    if current_speaker is not None and current_text:
        speaker_id = VOICE_ID_man if current_speaker == "男性" else VOICE_ID_woman
        lines.append({"text": " ".join(current_text), "id": speaker_id})

    return lines

@app.route("/")
def index():
    try:
        file_path = get_text_file_path()
        if not os.path.exists(file_path):
            return render_template("index.html", error="同じ階層にtext.txtが見つかりません")
        with open(file_path, 'r', encoding='utf-8') as f:
            text_content = f.read()
        lines = parse_text_content(text_content)
        if not lines:
            return render_template("index.html", error="有効な会話データが見つかりませんでした")
        return render_template("index.html", lines=lines)
    except Exception as e:
        return render_template("index.html", error=f"ファイルの処理中にエラーが発生しました: {str(e)}")

@app.route("/synthesize", methods=["POST"])
def synthesize():
    try:
        file_path = get_text_file_path()
        if not os.path.exists(file_path):
            return {"error": f"テキストファイルが見つかりません: {file_path}"}, 400
        with open(file_path, 'r', encoding='utf-8') as f:
            text_content = f.read()
        lines = parse_text_content(text_content)
        if not lines:
            return {"error": "合成するデータがありません。text.txtの形式を確認してください。"}, 400

        output_path, error = synthesize_dialogue(lines)
        if error:
            return {"error": error}, 500
        return {"success": True, "file_path": output_path}
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return {"error": f"予期せぬエラーが発生しました: {e}"}, 500

@app.route("/audio/<path:filename>")
def get_audio(filename):
    output_dir = get_output_directory()
    fp = os.path.join(output_dir, filename)
    if not os.path.exists(fp):
        return "Not found", 404
    return send_file(fp, mimetype="audio/wav")

if __name__ == "__main__":
    os.makedirs("templates", exist_ok=True)
    with open("templates/index.html", "w", encoding="utf-8") as f:
        f.write("""<!DOCTYPE html>
<html>
<head>
    <title>音声合成アプリ (Gemini TTS)</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        .dialogue-line { margin: 10px 0; padding: 10px; border: 1px solid #ccc; }
        .controls { margin: 20px 0; }
        button { padding: 10px 20px; background: #4CAF50; color: white; border: none; cursor: pointer; margin: 5px; }
        button:hover { background: #45a049; }
        #status { margin: 10px 0; padding: 10px; }
        .success { background: #dff0d8; color: #3c763d; }
        .error { background: #f2dede; color: #a94442; }
    </style>
</head>
<body>
    <h1>音声合成アプリ (Gemini TTS)</h1>
    <div id="status"></div>
    <div class="controls">
        <button onclick="synthesize()" id="synthesizeButton">音声を合成</button>
    </div>
    <div id="dialogue"></div>

    <script>
        let currentLines = {{ lines|tojson|safe if lines else '[]' }};
        function showStatus(message, isError = false) {
            const status = document.getElementById('status');
            status.textContent = message;
            status.className = isError ? 'error' : 'success';
        }
        function updateDialogueDisplay() {
            const dialogueDiv = document.getElementById('dialogue');
            dialogueDiv.innerHTML = currentLines.map(line => `
                <div class="dialogue-line">
                    <p>テキスト: ${line.text}</p>
                    <p>話者: ${line.id === 0 ? "男性" : "女性"}</p>
                </div>
            `).join('');
        }
        window.onload = function() {
            {% if error %}
                showStatus('{{ error }}', true);
            {% else %}
                updateDialogueDisplay();
                {% if lines %}
                    showStatus('text.txtを読み込みました！');
                {% endif %}
            {% endif %}
        };
        function synthesize() {
            if (currentLines.length === 0) {
                showStatus('合成するデータがありません', true);
                return;
            }
            showStatus('音声を合成中...');
            document.getElementById('synthesizeButton').disabled = true;
            fetch('/synthesize', { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                document.getElementById('synthesizeButton').disabled = false;
                if (data.error) {
                    showStatus('エラー: ' + data.error, true);
                } else {
                    showStatus('音声の合成が完了しました！');
                    const audio = new Audio('/audio/' + data.file_path.split('/').pop());
                    audio.play();
                }
            })
            .catch(error => {
                document.getElementById('synthesizeButton').disabled = false;
                showStatus('エラーが発生しました: ' + error, true);
            });
        }
    </script>
</body>
</html>""")
    app.run(host='0.0.0.0', port=8001, debug=True)
