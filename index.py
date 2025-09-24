import os
import re
import time
from datetime import datetime
from flask import Flask, render_template, send_file
from gtts import gTTS
from pydub import AudioSegment

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')

VOICE_ID_MAN = 0
VOICE_ID_WOMAN = 1

OUTPUT_DIR = os.environ.get('AUDIO_OUTPUT_DIR', 'audio_output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ----------------------------
# ユーティリティ関数
# ----------------------------
def clean_text(text):
    return re.sub(r'^セリフ:\s*', '', text).strip()

def get_text_file_path():
    return os.path.join(os.path.dirname(__file__), "text.txt")

def generate_filename():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"voice_dialogue_{timestamp}.mp3"

def synthesize_gtts_pseudo_voice(text, speaker, output_path):
    """
    gTTSで音声生成 → pydubで擬似的に男性/女性音声に加工
    """
    # gTTSで生成
    temp_file = f"temp_{int(time.time()*1000)}.mp3"
    tts = gTTS(text=text, lang='ja')
    tts.save(temp_file)

    # pydubで読み込み
    sound = AudioSegment.from_file(temp_file)

    # 男性/女性っぽく加工
    if speaker == VOICE_ID_MAN:
        # ピッチ低め・少し遅く
        sound = sound._spawn(sound.raw_data, overrides={"frame_rate": int(sound.frame_rate * 0.9)})
        sound = sound.speedup(playback_speed=0.95)
    else:
        # ピッチ高め・少し早く
        sound = sound._spawn(sound.raw_data, overrides={"frame_rate": int(sound.frame_rate * 1.1)})
        sound = sound.speedup(playback_speed=1.05)

    # 保存
    sound.export(output_path, format="mp3")

    # 一時ファイル削除
    if os.path.exists(temp_file):
        os.remove(temp_file)

    return output_path

def combine_audio_files(audio_files, output_path):
    if not audio_files:
        return None

    combined = AudioSegment.empty()
    for audio_file in audio_files:
        audio = AudioSegment.from_file(audio_file)
        combined += audio
        combined += AudioSegment.silent(duration=500)  # セリフ間0.5秒無音

    combined.export(output_path, format="mp3")
    return output_path

def parse_text_content(text_content):
    """text.txtを行データに変換"""
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
                speaker_id = VOICE_ID_MAN if current_speaker == "男性" else VOICE_ID_WOMAN
                lines.append({"text": " ".join(current_text), "id": speaker_id})
                current_text = []
            current_speaker = speaker_match.group(1)
            continue
        if current_speaker is not None:
            current_text.append(text)

    if current_speaker is not None and current_text:
        speaker_id = VOICE_ID_MAN if current_speaker == "男性" else VOICE_ID_WOMAN
        lines.append({"text": " ".join(current_text), "id": speaker_id})

    return lines

# ----------------------------
# ルート
# ----------------------------
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

        # 各行の音声生成
        temp_files = []
        for line in lines:
            cleaned_text = clean_text(line["text"])
            print(f"音声生成中: {cleaned_text} (話者: {'男性' if line['id']==VOICE_ID_MAN else '女性'})")
            temp_path = os.path.join(OUTPUT_DIR, f"temp_{int(time.time()*1000)}.mp3")
            synthesize_gtts_pseudo_voice(cleaned_text, line["id"], temp_path)
            temp_files.append(temp_path)

        # 結合
        output_filename = generate_filename()
        final_path = os.path.join(OUTPUT_DIR, output_filename)
        combine_audio_files(temp_files, final_path)

        # 一時ファイル削除
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)

        return {"success": True, "file_path": final_path}
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
<meta charset="utf-8">
<title>音声合成アプリ</title>
<style>
body { font-family: Arial; max-width: 800px; margin: 0 auto; padding:20px; }
.dialogue-line { margin:10px 0; padding:10px; border:1px solid #ccc; }
.controls { margin:20px 0; }
button { padding:10px 20px; background:#4CAF50; color:white; border:none; cursor:pointer; margin:5px; }
button:hover { background:#45a049; }
#status { margin:10px 0; padding:10px; }
.success { background:#dff0d8; color:#3c763d; }
.error { background:#f2dede; color:#a94442; }
</style>
</head>
<body>
<h1>音声合成アプリ (擬似男女)</h1>
<div id="status"></div>
<div class="controls">
<button onclick="synthesize()" id="synthesizeButton">音声を合成</button>
</div>
<div id="dialogue"></div>
<script>
let currentLines = {{ lines|tojson|safe if lines else '[]' }};
function showStatus(msg,isError=false){ const s=document.getElementById('status'); s.textContent=msg; s.className=isError?'error':'success'; }
function updateDialogueDisplay(){
  const d=document.getElementById('dialogue');
  d.innerHTML=currentLines.map(l=>`<div class="dialogue-line"><p>テキスト: ${l.text}</p><p>話者: ${l.id===0?'男性':'女性'}</p></div>`).join('');
}
window.onload=function(){ updateDialogueDisplay(); if(currentLines.length>0) showStatus('text.txt読み込み完了'); }
function synthesize(){
  if(currentLines.length===0){ showStatus('合成データなし',true); return; }
  showStatus('音声生成中...');
  document.getElementById('synthesizeButton').disabled=true;
  fetch('/synthesize',{method:'POST'}).then(r=>r.json()).then(d=>{
    document.getElementById('synthesizeButton').disabled=false;
    if(d.error){ showStatus('エラー: '+d.error,true); return; }
    showStatus('音声生成完了！');
    const audio=new Audio('/audio/'+d.file_path.split('/').pop()); audio.play();
  }).catch(e=>{ document.getElementById('synthesizeButton').disabled=false; showStatus('エラー: '+e,true); });
}
</script>
</body>
</html>""")
    app.run(host='0.0.0.0', port=8001, debug=True)
