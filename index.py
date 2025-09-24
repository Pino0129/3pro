import os
import re
import time
from datetime import datetime
from flask import Flask, render_template, request, send_file
from gtts import gTTS

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')

VOICE_ID_man = 0
VOICE_ID_woman = 1

# 保存ディレクトリ
OUTPUT_DIR = os.environ.get('AUDIO_OUTPUT_DIR', 'audio_output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

def clean_text(text):
    text = re.sub(r'^セリフ:\s*', '', text)
    return text.strip()

def get_text_file_path():
    return os.path.join(os.path.dirname(__file__), "text.txt")

def generate_filename():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"voice_dialogue_{timestamp}.mp3"

def synthesize_text_gtts(text):
    """gTTS で音声を生成"""
    try:
        tts = gTTS(text=text, lang="ja")
        temp_filename = f"temp_{int(time.time()*1000)}.mp3"
        temp_filepath = os.path.join(OUTPUT_DIR, temp_filename)
        tts.save(temp_filepath)
        return temp_filepath
    except Exception as e:
        print(f"gTTS synth failed: {e}")
        return None

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
            return render_template("index.html", error="text.txtが見つかりません")
        with open(file_path, 'r', encoding='utf-8') as f:
            text_content = f.read()
        lines = parse_text_content(text_content)
        return render_template("index.html", lines=lines)
    except Exception as e:
        return render_template("index.html", error=f"エラー: {e}")

@app.route("/synthesize", methods=["POST"])
def synthesize():
    try:
        file_path = get_text_file_path()
        if not os.path.exists(file_path):
            return {"error": "text.txtがありません"}, 400
        with open(file_path, 'r', encoding='utf-8') as f:
            text_content = f.read()
        lines = parse_text_content(text_content)
        if not lines:
            return {"error": "合成するデータがありません"}, 400

        # 複数行を連結して gTTS で生成（簡易版）
        combined_text = "。".join(clean_text(line["text"]) for line in lines)
        audio_path = synthesize_text_gtts(combined_text)
        if not audio_path:
            return {"error": "音声生成に失敗しました"}, 500

        return {"success": True, "file_path": audio_path}
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return {"error": f"予期せぬエラー: {e}"}, 500

@app.route("/audio/<path:filename>")
def get_audio(filename):
    fp = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(fp):
        return "Not found", 404
    return send_file(fp, mimetype="audio/mpeg")

if __name__ == "__main__":
    os.makedirs("templates", exist_ok=True)
    with open("templates/index.html", "w", encoding="utf-8") as f:
        f.write("""<!DOCTYPE html>
<html>
<head>
    <title>音声合成アプリ (gTTS)</title>
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
    <h1>音声合成アプリ (gTTS)</h1>
    <div id="status"></div>
    <div class="controls">
        <button onclick="synthesize()" id="synthesizeButton">音声を合成</button>
    </div>
    <div id="dialogue"></div>

    <script>
        let currentLines = {{ lines|tojson|safe if lines else '[]' }};
        function showStatus(msg, isError=false) {
            const status = document.getElementById('status');
            status.textContent = msg;
            status.className = isError ? 'error' : 'success';
        }
        function updateDialogueDisplay() {
            const div = document.getElementById('dialogue');
            div.innerHTML = currentLines.map(line => `
                <div class="dialogue-line">
                    <p>テキスト: ${line.text}</p>
                    <p>話者: ${line.id===0?"男性":"女性"}</p>
                </div>`).join('');
        }
        window.onload = function() {
            updateDialogueDisplay();
            if(currentLines.length>0) showStatus('text.txtを読み込みました！');
        }
        function synthesize() {
            if(currentLines.length===0) { showStatus('合成データなし',true); return; }
            showStatus('音声生成中...');
            document.getElementById('synthesizeButton').disabled=true;
            fetch('/synthesize',{method:'POST'})
            .then(r=>r.json())
            .then(data=>{
                document.getElementById('synthesizeButton').disabled=false;
                if(data.error){ showStatus('エラー: '+data.error,true); return; }
                showStatus('音声生成完了！');
                const audio = new Audio('/audio/'+data.file_path.split('/').pop());
                audio.play();
            }).catch(e=>{
                document.getElementById('synthesizeButton').disabled=false;
                showStatus('エラー: '+e,true);
            });
        }
    </script>
</body>
</html>""")
    app.run(host='0.0.0.0', port=8001, debug=True)
