#!/usr/bin/env python3
"""
Video Editor — Нутра
Запуск: python3 app.py
"""
VERSION = "4.9"
import io, hashlib
import subprocess, sys, os, shutil, json, threading, uuid, time, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

JOBS = {}
UPLOAD_JOBS = {}  # job_id -> {status, links}
MASS_UPLOAD_JOBS = {}  # job_id -> {status, log, sets, total, done}
UPLOAD_DIR = os.path.expanduser("~/Desktop/VideoEditor_uploads")
OUTPUT_DIR = os.path.expanduser("~/Desktop/VideoEditor_output")
CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "client_secret.json")
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yt_token.json")
UPLOADS_TODAY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads_today.json")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ANTHROPIC_FALLBACK_KEY = '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'

def get_anthropic_key():
    _default = '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'
    key_file = os.path.join(BASE_DIR, 'anthropic_key.txt')
    if os.path.exists(key_file):
        k = open(key_file).read().strip()
        if k: return k
    return _default

# ── Multi-user auth ──────────────────────────────────────────────
USERS_FILE = os.path.join(BASE_DIR, 'users.json')
SESSIONS_FILE = os.path.join(BASE_DIR, 'sessions.json')

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f:
            return json.load(f)
    return {}  # empty = first launch, show setup screen

def is_first_launch():
    return not os.path.exists(USERS_FILE) or not load_users()

def save_users(u):
    with open(USERS_FILE, 'w') as f:
        json.dump(u, f, indent=2)

def load_sessions():
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE) as f:
                data = json.load(f)
            now = time.time()
            return {k: v for k, v in data.items() if v.get('exp', 0) > now}
        except Exception:
            return {}
    return {}

def save_sessions(s):
    with open(SESSIONS_FILE, 'w') as f:
        json.dump(s, f)

USERS = load_users()
SESSIONS = load_sessions()  # {session_id: {user, exp}}

def get_channels_file(user):
    return os.path.join(BASE_DIR, f'channels_{user}.json')

def load_channels(user='pavel'):
    f = get_channels_file(user)
    if os.path.exists(f):
        with open(f) as fp:
            return json.load(fp)
    return {}

def save_channels(user, channels):
    with open(get_channels_file(user), 'w') as f:
        json.dump(channels, f, ensure_ascii=False, indent=2)

ADMIN_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin — Video Editor</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f5f7;min-height:100vh;padding:40px 20px}
.wrap{max-width:600px;margin:0 auto}
h1{font-size:24px;font-weight:600;margin-bottom:8px}
.sub{color:#666;font-size:14px;margin-bottom:32px}
.card{background:#fff;border-radius:16px;padding:24px;margin-bottom:20px;border:1px solid #e5e5e5}
.card h2{font-size:16px;font-weight:600;margin-bottom:16px}
.row{display:flex;gap:10px;margin-bottom:12px}
input{flex:1;padding:10px 14px;border:1px solid #ddd;border-radius:10px;font-size:14px;outline:none}
input:focus{border-color:#4f46e5}
button{padding:10px 20px;background:#4f46e5;color:#fff;border:none;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer}
button:hover{background:#4338ca}
.btn-del{background:#fff;color:#e53e3e;border:1px solid #e53e3e;padding:6px 12px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer}
.btn-del:hover{background:#fff5f5}
.user-row{display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid #f0f0f0}
.user-row:last-child{border-bottom:none}
.user-name{font-size:14px;font-weight:500}
.msg{padding:10px 14px;border-radius:10px;font-size:13px;margin-top:12px;display:none}
.msg.ok{background:#e6fffa;color:#0f6e56;display:block}
.msg.err{background:#fff5f5;color:#e53e3e;display:block}
.back{display:inline-flex;align-items:center;gap:6px;color:#4f46e5;font-size:14px;text-decoration:none;margin-bottom:24px}
</style></head>
<body>
<div class="wrap">
  <a href="/" class="back">← Назад в панель</a>
  <h1>Управление пользователями</h1>
  <p class="sub">Добавляй и удаляй байеров. Пользователь pavel нельзя удалить.</p>

  <div class="card">
    <h2>Добавить пользователя</h2>
    <div class="row">
      <input id="uname" placeholder="Логин (например buyer1)" />
      <input id="upw" type="password" placeholder="Пароль" />
      <button onclick="addUser()">Добавить</button>
    </div>
    <div id="add-msg" class="msg"></div>
  </div>

  <div class="card">
    <h2>Текущие пользователи</h2>
    <div id="user-list">Загрузка...</div>
  </div>
</div>
<script>
async function loadUsers(){
  const r = await fetch('/admin/users');
  const d = await r.json();
  const el = document.getElementById('user-list');
  if(!d.users.length){el.innerHTML='<p style="color:#999;font-size:14px">Нет пользователей</p>';return}
  el.innerHTML = d.users.map(u=>`
    <div class="user-row">
      <span class="user-name">${u}</span>
      ${u==='pavel'?'<span style="font-size:12px;color:#999">владелец</span>':`<button class="btn-del" onclick="delUser('${u}')">Удалить</button>`}
    </div>`).join('');
}
async function addUser(){
  const u=document.getElementById('uname').value.trim();
  const p=document.getElementById('upw').value.trim();
  const msg=document.getElementById('add-msg');
  if(!u||!p){msg.className='msg err';msg.textContent='Заполни логин и пароль';return}
  const r=await fetch('/admin/add_user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
  const d=await r.json();
  if(d.ok){msg.className='msg ok';msg.textContent='✓ Пользователь добавлен';document.getElementById('uname').value='';document.getElementById('upw').value='';loadUsers();}
  else{msg.className='msg err';msg.textContent='Ошибка: '+d.error;}
}
async function delUser(u){
  if(!confirm('Удалить пользователя '+u+'?'))return;
  const r=await fetch('/admin/delete_user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u})});
  const d=await r.json();
  if(d.ok)loadUsers();
}
loadUsers();
</script>
</body></html>'''

LOGIN_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Вход — Video Editor</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{background:#0f0f1a;display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}
.card{background:#1a1a2e;border:1px solid #2a2a4a;border-radius:20px;padding:40px 36px;width:100%;max-width:360px;box-shadow:0 20px 60px rgba(0,0,0,.5);}
.logo{text-align:center;margin-bottom:28px;}
.logo-icon{font-size:48px;margin-bottom:8px;}
.logo h1{font-size:22px;font-weight:800;color:#fff;margin-bottom:4px;}
.logo p{font-size:13px;color:#666;}
label{display:block;font-size:12px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;}
input{width:100%;padding:12px 14px;background:#0f0f1a;border:1.5px solid #2a2a4a;border-radius:10px;color:#fff;font-size:14px;outline:none;transition:.2s;margin-bottom:16px;}
input:focus{border-color:#7c3aed;}
.btn{width:100%;padding:13px;background:linear-gradient(135deg,#7c3aed,#a855f7);border:none;border-radius:12px;color:#fff;font-size:15px;font-weight:700;cursor:pointer;transition:.2s;margin-top:4px;}
.btn:hover{opacity:.9;transform:translateY(-1px);}
.err{background:#3a1515;border:1px solid #7f1d1d;color:#fca5a5;border-radius:8px;padding:10px 14px;font-size:13px;margin-bottom:16px;display:none;}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <div class="logo-icon">🎬</div>
    <h1>Video Editor</h1>
    <p>Введите данные для входа</p>
  </div>
  <div class="err" id="err">Неверный логин или пароль</div>
  <form onsubmit="login(event)">
    <label>Логин</label>
    <input type="text" id="u" autocomplete="username" required>
    <label>Пароль</label>
    <input type="password" id="p" autocomplete="current-password" required>
    <button class="btn" type="submit">Войти →</button>
  </form>
</div>
<script>
async function login(e){
  e.preventDefault();
  const r = await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({u:document.getElementById('u').value,p:document.getElementById('p').value})});
  const d = await r.json();
  if(d.ok) window.location.href = '/';
  else { document.getElementById('err').style.display='block'; }
}
</script>
</body></html>'''

SETUP_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Настройка — Video Editor</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;}
body{background:#0f0f1a;display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}
.card{background:#1a1a2e;border:1px solid #2a2a4a;border-radius:20px;padding:40px 36px;width:100%;max-width:380px;box-shadow:0 20px 60px rgba(0,0,0,.5);}
.logo{text-align:center;margin-bottom:28px;}
.logo-icon{font-size:48px;margin-bottom:8px;}
.logo h1{font-size:22px;font-weight:800;color:#fff;margin-bottom:4px;}
.logo p{font-size:13px;color:#666;}
label{display:block;font-size:12px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;}
input{width:100%;padding:12px 14px;background:#0f0f1a;border:1.5px solid #2a2a4a;border-radius:10px;color:#fff;font-size:14px;outline:none;transition:.2s;margin-bottom:16px;}
input:focus{border-color:#7c3aed;}
.btn{width:100%;padding:13px;background:linear-gradient(135deg,#7c3aed,#a855f7);border:none;border-radius:12px;color:#fff;font-size:15px;font-weight:700;cursor:pointer;transition:.2s;margin-top:4px;}
.btn:hover{opacity:.9;transform:translateY(-1px);}
.err{background:#3a1515;border:1px solid #7f1d1d;color:#fca5a5;border-radius:8px;padding:10px 14px;font-size:13px;margin-bottom:16px;display:none;}
.hint{font-size:12px;color:#555;margin-top:12px;text-align:center;}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <div class="logo-icon">🎬</div>
    <h1>Video Editor</h1>
    <p>Первый запуск — создайте аккаунт</p>
  </div>
  <div class="err" id="err"></div>
  <form onsubmit="setup(event)">
    <label>Придумайте логин</label>
    <input type="text" id="u" placeholder="например: buyer1" autocomplete="username" required>
    <label>Придумайте пароль</label>
    <input type="password" id="p" placeholder="минимум 4 символа" autocomplete="new-password" required>
    <button class="btn" type="submit">Создать и войти →</button>
  </form>
  <p class="hint">Запомните логин и пароль — они нужны для входа</p>
</div>
<script>
async function setup(e){
  e.preventDefault();
  const u=document.getElementById('u').value.trim();
  const p=document.getElementById('p').value;
  const err=document.getElementById('err');
  if(u.length<2){err.style.display='block';err.textContent='Логин слишком короткий';return;}
  if(p.length<4){err.style.display='block';err.textContent='Пароль минимум 4 символа';return;}
  const r=await fetch('/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({u,p})});
  const d=await r.json();
  if(d.ok) window.location.href='/';
  else{err.style.display='block';err.textContent=d.error||'Ошибка';}
}
</script>
</body></html>'''

def load_uploads_today():
    if os.path.exists(UPLOADS_TODAY_FILE):
        with open(UPLOADS_TODAY_FILE) as f:
            data = json.load(f)
        today = time.strftime('%Y-%m-%d')
        if data.get('date') != today:
            return {'date': today, 'counts': {}}
        return data
    return {'date': time.strftime('%Y-%m-%d'), 'counts': {}}

def save_uploads_today(data):
    with open(UPLOADS_TODAY_FILE, 'w') as f:
        json.dump(data, f)

# ── Per-user API projects ─────────────────────────────────────────
def get_projects_file(user):
    return os.path.join(BASE_DIR, f'projects_{user}.json')

def load_projects(user):
    f = get_projects_file(user)
    if os.path.exists(f):
        with open(f) as fp:
            return json.load(fp)
    return {}

def save_projects(user, projects):
    with open(get_projects_file(user), 'w') as f:
        json.dump(projects, f, ensure_ascii=False, indent=2)

def get_project_uploads_file(user):
    return os.path.join(BASE_DIR, f'proj_uploads_{user}.json')

def load_project_uploads(user):
    f = get_project_uploads_file(user)
    if os.path.exists(f):
        with open(f) as fp:
            data = json.load(fp)
        today = time.strftime('%Y-%m-%d')
        if data.get('date') != today:
            return {'date': today, 'counts': {}}
        return data
    return {'date': time.strftime('%Y-%m-%d'), 'counts': {}}

def save_project_uploads(user, data):
    with open(get_project_uploads_file(user), 'w') as f:
        json.dump(data, f)

def get_best_project_secret(user):
    """Return path to client_secret.json with most remaining quota today."""
    projects = load_projects(user)
    if not projects:
        # fallback to global client_secret.json
        return CREDENTIALS_FILE
    uploads = load_project_uploads(user)
    counts = uploads.get('counts', {})
    best_proj = None
    best_count = 9999
    for pid, pinfo in projects.items():
        used = counts.get(pid, 0)
        if used < 100 and used < best_count:
            best_count = used
            best_proj = pid
    if best_proj:
        return projects[best_proj]['file']
    return None  # all exhausted

def increment_project_upload(user, proj_id):
    uploads = load_project_uploads(user)
    uploads['counts'][proj_id] = uploads['counts'].get(proj_id, 0) + 1
    save_project_uploads(user, uploads)

def get_proj_id_for_secret(secret_file, user):
    projects = load_projects(user)
    for pid, pinfo in projects.items():
        if pinfo.get('file') == secret_file:
            return pid
    # fallback: first available project
    if projects:
        return next(iter(projects))
    return None

def get_best_channel(user='pavel'):
    channels = load_channels(user)
    if not channels:
        return None, None
    today_data = load_uploads_today()
    counts = today_data.get('counts', {})
    best = None
    best_count = 999
    for ch_id, ch_info in channels.items():
        count = counts.get(ch_id, 0)
        if count < 10 and count < best_count:
            best = ch_id
            best_count = count
    return best, channels.get(best)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def even(n):
    return int(n // 2) * 2

def get_video_info(path):
    r = subprocess.run(['ffprobe','-v','quiet','-print_format','json','-show_streams', path], capture_output=True, text=True)
    info = json.loads(r.stdout)
    vs = next((s for s in info['streams'] if s['codec_type']=='video'), None)
    has_audio = any(s['codec_type']=='audio' for s in info['streams'])
    w = int(vs['width']) if vs else 1280
    h = int(vs['height']) if vs else 720
    return w, h, has_audio

def run_ff(cmd, job_id):
    JOBS[job_id]['log'].append('▶ ' + ' '.join(str(c) for c in cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        JOBS[job_id]['log'].append('❌ ' + r.stderr[-1000:])
        raise Exception(r.stderr[-500:])
    return r

def process_video(job_id, params):
    try:
        JOBS[job_id]['status'] = 'running'
        log = JOBS[job_id]['log']
        video = params['video']
        audio = params.get('audio')
        tail_img = params.get('tail_img')
        vol = float(params.get('vol', 0.05))
        tail_min = int(params.get('tail_min', 3))
        use_voice = params.get('use_voice') and audio and os.path.exists(str(audio))
        use_tail = params.get('use_tail') and tail_img and os.path.exists(str(tail_img))
        use_overlay = params.get('use_overlay')
        overlay_txt = params.get('overlay_txt', '')
        overlay_size = int(params.get('overlay_size', 36))
        bar_pct = int(params.get('bar_pct', 20))
        formats = params.get('formats', ['9:16','1:1','16:9'])
        vid_title = params.get('vid_title', 'Video')

        tmp = os.path.join(OUTPUT_DIR, job_id, 'tmp')
        out_dir = os.path.join(OUTPUT_DIR, job_id)
        os.makedirs(tmp, exist_ok=True)

        src_w, src_h, has_audio = get_video_info(video)
        log.append(f'📐 Исходный размер: {src_w}x{src_h}')
        work = os.path.join(tmp, 'norm.mp4')

        log.append('⏳ Нормализуем видео...')
        if has_audio:
            run_ff(['ffmpeg','-y','-i',video,'-vf','fps=25,setsar=1',
                '-c:v','libx264','-profile:v','baseline','-crf','18','-preset','fast','-pix_fmt','yuv420p',
                '-c:a','aac','-b:a','128k','-ar','44100','-ac','2', work], job_id)
        else:
            run_ff(['ffmpeg','-y','-i',video,'-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100',
                '-vf','fps=25,setsar=1','-c:v','libx264','-profile:v','baseline','-crf','18','-preset','fast','-pix_fmt','yuv420p',
                '-c:a','aac','-b:a','128k','-ar','44100','-ac','2','-shortest', work], job_id)
        log.append('✅ Нормализация готова')

        if use_voice:
            log.append('⏳ Добавляем белый голос...')
            voiced = os.path.join(tmp, 'voiced.mp4')
            run_ff(['ffmpeg','-y','-i',work,'-i',audio,
                '-filter_complex',
                f'[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume=2.0[a0];'
                f'[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume={vol:.3f}[a1];'
                f'[a0][a1]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]',
                '-map','0:v','-map','[aout]','-c:v','copy','-c:a','aac','-b:a','128k', voiced], job_id)
            work = voiced
            log.append('✅ Белый голос добавлен')

        if use_overlay:
            log.append('⏳ Добавляем полосу поверх субтитров...')
            overlaid = os.path.join(tmp, 'overlaid.mp4')
            safe_txt = ''.join(c for c in overlay_txt if c.isalnum() or c in ' .-_!')
            bar_color = params.get('bar_color', '#000000').lstrip('#')
            txt_color = params.get('txt_color', '#ffffff').lstrip('#')
            bar_h_px = int(src_h * bar_pct / 100)
            bar_y_px = src_h - bar_h_px
            txt_y_px = bar_y_px + (bar_h_px - overlay_size) // 2
            has_drawtext = bool(subprocess.run(
                ['ffmpeg', '-filters'], capture_output=True, text=True
            ).stdout.__contains__('drawtext') or subprocess.run(
                ['ffmpeg', '-filters'], capture_output=True, text=True
            ).stderr.__contains__('drawtext'))
            if safe_txt and has_drawtext:
                vf = (f"drawbox=x=0:y={bar_y_px}:w=iw:h={bar_h_px}:color=0x{bar_color}:t=fill,"
                      f"drawtext=text='{safe_txt}':fontsize={overlay_size}:fontcolor=0x{txt_color}:x=(w-text_w)/2:y={txt_y_px}")
            else:
                vf = f"drawbox=x=0:y={bar_y_px}:w=iw:h={bar_h_px}:color=0x{bar_color}:t=fill"
            run_ff(['ffmpeg','-y','-i',work,'-vf',vf,
                '-c:v','libx264','-profile:v','baseline','-crf','18','-preset','fast','-pix_fmt','yuv420p',
                '-c:a','copy', overlaid], job_id)
            work = overlaid
            log.append('✅ Полоса добавлена')

        # Шумы для уникальности видео
        use_noise = params.get('use_noise', False)
        noise_strength = float(params.get('noise_strength', 3))
        if use_noise:
            log.append(f'⏳ Добавляем шумы (сила: {int(noise_strength)})...')
            noised = os.path.join(tmp, 'noised.mp4')
            run_ff(['ffmpeg','-y','-i',work,
                '-vf', f'noise=alls={noise_strength:.0f}:allf=t+u',
                '-c:v','libx264','-profile:v','baseline','-crf','18','-preset','fast','-pix_fmt','yuv420p',
                '-c:a','copy', noised], job_id)
            work = noised
            log.append('✅ Шумы добавлены')

        if use_tail:
            tail_is_video = tail_img and any(tail_img.lower().endswith(x) for x in ['.mp4','.mov','.avi','.mkv'])
            tail_vol = float(params.get('tail_vol', 1.0))
            log.append(f'⏳ Создаём хвост ({tail_min} мин)...')
            tail_v = os.path.join(tmp, 'tail_v.mp4')
            if tail_is_video:
                if use_voice and audio and os.path.exists(str(audio)):
                    # Видео хвост: смешиваем аудио видео + белый голос параллельно
                    run_ff(['ffmpeg','-y','-stream_loop','-1','-i',tail_img,
                        '-stream_loop','-1','-i',audio,
                        '-filter_complex',
                        f'[0:v]scale={src_w}:{src_h}:force_original_aspect_ratio=decrease,'
                        f'pad={src_w}:{src_h}:(ow-iw)/2:(oh-ih)/2:color=black,fps=25,setsar=1[v];'
                        f'[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[va];'
                        f'[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume={tail_vol:.3f}[wa];'
                        f'[va][wa]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]',
                        '-map','[v]','-map','[aout]',
                        '-t',str(tail_min*60),
                        '-c:v','libx264','-profile:v','baseline','-crf','28','-preset','fast','-pix_fmt','yuv420p',
                        '-c:a','aac','-b:a','128k','-ar','44100','-ac','2', tail_v], job_id)
                else:
                    run_ff(['ffmpeg','-y','-stream_loop','-1','-i',tail_img,
                        '-t',str(tail_min*60),
                        '-vf',f'scale={src_w}:{src_h}:force_original_aspect_ratio=decrease,'
                              f'pad={src_w}:{src_h}:(ow-iw)/2:(oh-ih)/2:color=black,fps=25,setsar=1',
                        '-c:v','libx264','-profile:v','baseline','-crf','28','-preset','fast','-pix_fmt','yuv420p',
                        '-c:a','aac','-b:a','128k','-ar','44100','-ac','2', tail_v], job_id)
            else:
                # Фото хвост
                tail_jpg = os.path.join(tmp, 'tail.jpg')
                run_ff(['ffmpeg','-y','-i',tail_img, tail_jpg], job_id)
                if use_voice and audio and os.path.exists(str(audio)):
                    # Фото хвост: белый голос идёт параллельно (фото без своего аудио — просто берём голос)
                    run_ff(['ffmpeg','-y','-loop','1','-i',tail_jpg,
                        '-stream_loop','-1','-i',audio,
                        '-filter_complex',
                        f'[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,volume={tail_vol:.3f}[aout]',
                        '-map','0:v','-map','[aout]',
                        '-t',str(tail_min*60),
                        '-vf',f'scale={src_w}:{src_h}:force_original_aspect_ratio=decrease,'
                              f'pad={src_w}:{src_h}:(ow-iw)/2:(oh-ih)/2:color=black,fps=25,setsar=1',
                        '-c:v','libx264','-profile:v','baseline','-tune','stillimage',
                        '-crf','28','-preset','fast','-pix_fmt','yuv420p',
                        '-c:a','aac','-b:a','128k','-ar','44100','-ac','2', tail_v], job_id)
                else:
                    run_ff(['ffmpeg','-y','-loop','1','-i',tail_jpg,
                        '-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=44100',
                        '-t',str(tail_min*60),
                        '-vf',f'scale={src_w}:{src_h}:force_original_aspect_ratio=decrease,'
                              f'pad={src_w}:{src_h}:(ow-iw)/2:(oh-ih)/2:color=black,fps=25,setsar=1',
                        '-c:v','libx264','-profile:v','baseline','-tune','stillimage',
                        '-crf','28','-preset','fast','-pix_fmt','yuv420p',
                        '-c:a','aac','-b:a','32k','-ar','44100','-ac','2', tail_v], job_id)
            # Усиливаем громкость оригинала перед склейкой с хвостом
            work_loud = os.path.join(tmp, 'work_loud.mp4')
            run_ff(['ffmpeg','-y','-i',work,
                '-af','volume=2.0',
                '-map','0:v','-map','0:a','-c:v','copy','-c:a','aac','-b:a','128k', work_loud], job_id)
            work = work_loud
            merged = os.path.join(tmp, 'merged.mp4')
            concat_f = os.path.join(tmp, 'concat.txt')
            with open(concat_f,'w') as f:
                f.write(f"file '{work}'\nfile '{tail_v}'\n")
            run_ff(['ffmpeg','-y','-f','concat','-safe','0','-i',concat_f,'-c','copy', merged], job_id)
            work = merged
            log.append('✅ Хвост добавлен')

        log.append('⏳ Экспортируем форматы...')
        output_files = []
        fmt_labels = {'9:16':'9x16','1:1':'1x1','16:9':'16x9'}
        import random as _random
        for fmt in formats:
            rw, rh = map(int, fmt.split(':'))
            ratio = rw/rh
            if ratio >= 1:
                cw, ch = 640, even(int(640/ratio))
            else:
                ch, cw = 640, even(int(640*ratio))
            vf = (f'scale={cw}:{ch}:force_original_aspect_ratio=decrease,'
                  f'pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1')
            label = fmt_labels.get(fmt, fmt.replace(':','x'))
            out_name = f'video_{label}.mp4'
            out_file = os.path.join(out_dir, out_name)
            # Уникализация аудио + видео
            pitch = 1.0 + _random.uniform(-0.015, 0.015)
            tempo = round(1.0 / pitch, 6)
            abitrate = _random.choice(['112k', '128k', '160k', '192k'])
            # EQ: случайные срезы на низких и высоких
            hp_freq = _random.randint(18, 35)
            lp_freq = _random.randint(14000, 18000)
            eq_freq = _random.randint(200, 4000)
            eq_gain = _random.uniform(-2.5, 2.5)
            eq_bw = _random.uniform(0.8, 2.0)
            # Реверб (очень маленький)
            reverb_delay = _random.randint(20, 60)
            reverb_decay = _random.uniform(0.08, 0.18)
            reverb_mix = _random.uniform(0.04, 0.10)
            # Стерео
            stereo_width = _random.uniform(0.92, 1.08)
            af = (
                f'asetrate=44100*{pitch:.6f},aresample=44100,'
                f'atempo={tempo:.6f},'
                f'highpass=f={hp_freq},'
                f'lowpass=f={lp_freq},'
                f'equalizer=f={eq_freq}:width_type=o:width={eq_bw:.2f}:g={eq_gain:.2f},'
                f'aecho=0.8:{reverb_mix:.3f}:{reverb_delay}:{reverb_decay:.3f},'
                f'aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo'
            )
            # Видео: micro-crop + цвет
            crop_l = _random.randint(0, 3)
            crop_r = _random.randint(0, 3)
            crop_t = _random.randint(0, 3)
            crop_b = _random.randint(0, 3)
            bright = _random.uniform(-0.02, 0.02)
            sat = _random.uniform(0.96, 1.04)
            gamma = _random.uniform(0.97, 1.03)
            crf = _random.randint(20, 25)
            keyint = _random.randint(48, 72)
            vf_unique = (
                f'{vf},'
                f'crop=iw-{crop_l+crop_r}:ih-{crop_t+crop_b}:{crop_l}:{crop_t},'
                f'scale={cw}:{ch}:force_original_aspect_ratio=decrease,'
                f'pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:color=black,'
                f'eq=brightness={bright:.4f}:saturation={sat:.4f}:gamma={gamma:.4f},'
                f'setsar=1'
            )
            log.append(f'🛡️ Уникализация [{fmt}]: питч {pitch:.4f}x · EQ {eq_freq}Hz·{eq_gain:.1f}dB · реверб {reverb_delay}ms · crop {crop_l}/{crop_r}/{crop_t}/{crop_b} · {abitrate}')
            run_ff(['ffmpeg','-y','-i',work,'-vf',vf_unique,
                '-c:v','libx264','-profile:v','baseline',f'-crf',str(crf),'-preset','fast','-pix_fmt','yuv420p',
                f'-g',str(keyint),'-keyint_min',str(keyint//2),
                '-af', af, '-c:a','aac','-b:a', abitrate,
                '-map_metadata','-1','-fflags','+bitexact','-flags:v','+bitexact','-flags:a','+bitexact',
                out_file], job_id)
            size_mb = round(os.path.getsize(out_file)/1024/1024, 1)
            log.append(f'✅ {fmt} готов ({cw}x{ch}, {size_mb}MB)')
            output_files.append({'name': out_name, 'path': out_file, 'size': size_mb, 'fmt': fmt, 'title': f'{vid_title} [{fmt}]'})

        shutil.rmtree(tmp, ignore_errors=True)
        JOBS[job_id]['files'] = output_files
        JOBS[job_id]['status'] = 'done'
        log.append('🎉 Всё готово! Можешь скачать или загрузить на YouTube.')
    except Exception as e:
        JOBS[job_id]['status'] = 'error'
        JOBS[job_id]['log'].append(f'❌ Ошибка: {str(e)}')

def get_youtube_service(token_file=None, proxy=''):
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    import httplib2
    SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
    if token_file is None:
        token_file = TOKEN_FILE
    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, 'w') as f:
            f.write(creds.to_json())
    if proxy:
        from urllib.parse import urlparse as _up
        parsed = _up(proxy)
        proxy_url = proxy
        os.environ['HTTPS_PROXY'] = proxy_url
        os.environ['HTTP_PROXY'] = proxy_url
        print(f'[PROXY] Using proxy: {parsed.hostname}:{parsed.port}')
        svc = build('youtube', 'v3', credentials=creds)
        return svc
    # No proxy — show real IP
    try:
        import urllib.request as _ur
        real_ip = _ur.urlopen('https://api.ipify.org', timeout=5).read().decode().strip()
        print(f'[NO PROXY] Upload IP: {real_ip}')
    except Exception:
        pass
    return build('youtube', 'v3', credentials=creds)

CHANNEL_AUTH_FLOWS = {}  # job_id -> flow (waiting for code)

def add_channel_auth(job_id, user='pavel', is_local=True, proxy='', login_hint=''):
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow, Flow
        from googleapiclient.discovery import build
        SCOPES = [
            'https://www.googleapis.com/auth/youtube.upload',
            'https://www.googleapis.com/auth/youtube.readonly',
        ]
        UPLOAD_JOBS[job_id]['status'] = 'running'

        secret_file = get_best_project_secret(user) or CREDENTIALS_FILE
        if is_local:
            # Pavel on localhost — fully automatic
            UPLOAD_JOBS[job_id]['log'].append('🔐 Открываем браузер для авторизации...')
            flow = InstalledAppFlow.from_client_secrets_file(secret_file, SCOPES)
            creds = flow.run_local_server(port=0)
        else:
            # Remote user — generate URL, wait for manual code
            flow = InstalledAppFlow.from_client_secrets_file(secret_file, SCOPES)
            flow.redirect_uri = 'http://localhost:63241'
            auth_kwargs = dict(prompt='consent', access_type='offline', include_granted_scopes='false')
            if login_hint:
                auth_kwargs['login_hint'] = login_hint
            auth_url, _ = flow.authorization_url(**auth_kwargs)
            # Remove PKCE params that some accounts don't support
            from urllib.parse import urlparse as _up2, urlencode, parse_qs, urlunparse
            _p = _up2(auth_url)
            _qs = parse_qs(_p.query, keep_blank_values=True)
            _qs.pop('code_challenge', None)
            _qs.pop('code_challenge_method', None)
            _flat = {k: v[0] for k, v in _qs.items()}
            auth_url = urlunparse((_p.scheme, _p.netloc, _p.path, _p.params, urlencode(_flat), _p.fragment))
            flow.code_verifier = None
            UPLOAD_JOBS[job_id]['auth_url'] = auth_url
            UPLOAD_JOBS[job_id]['log'].append(f'🔗 AUTH URL: {auth_url}')
            UPLOAD_JOBS[job_id]['log'].append('🔗 Открой ссылку и авторизуйся')
            UPLOAD_JOBS[job_id]['status'] = 'waiting_code'
            CHANNEL_AUTH_FLOWS[job_id] = {'flow': flow, 'user': user, 'scopes': SCOPES, 'proxy': proxy, 'secret_file': secret_file}
            return  # Will resume in /add_channel_code

        creds = _finish_channel_auth(job_id, creds, user, proxy, secret_file)
    except Exception as e:
        UPLOAD_JOBS[job_id]['status'] = 'error'
        UPLOAD_JOBS[job_id]['log'].append(f'❌ Ошибка: {str(e)}')

def _finish_channel_auth(job_id, creds, user, proxy='', secret_file=None):
    from googleapiclient.discovery import build
    yt = build('youtube', 'v3', credentials=creds)
    ch_id = None
    ch_name = None
    try:
        ch_resp = yt.channels().list(part='snippet', mine=True).execute()
        if ch_resp.get('items'):
            ch = ch_resp['items'][0]
            ch_id = ch['id']
            ch_name = ch['snippet']['title']
            UPLOAD_JOBS[job_id]['log'].append(f'📺 Канал: {ch_name}')
    except Exception as e:
        UPLOAD_JOBS[job_id]['log'].append(f'⚠️ Не удалось получить имя канала: {e}')
    if not ch_id:
        try:
            from googleapiclient.discovery import build as _gbuild
            oauth2 = _gbuild('oauth2', 'v2', credentials=creds)
            info = oauth2.userinfo().get().execute()
            email = info.get('email', '')
            ch_name = email or f'Канал {len(load_channels(user))+1}'
            ch_id = 'ch_' + hashlib.md5(email.encode()).hexdigest()[:8] if email else 'ch_' + hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
            UPLOAD_JOBS[job_id]['log'].append(f'📧 Аккаунт: {email}')
        except Exception:
            ch_id = 'ch_' + hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
            ch_name = f'Канал {len(load_channels(user))+1}'
    token_file = os.path.join(BASE_DIR, f'token_{user}_{ch_id}.json')
    with open(token_file, 'w') as f:
        f.write(creds.to_json())
    proj_id = get_proj_id_for_secret(secret_file, user)
    channels = load_channels(user)
    channels[ch_id] = {'name': ch_name, 'token_file': token_file, 'project_id': proj_id, 'proxy': proxy}
    save_channels(user, channels)
    if proxy:
        UPLOAD_JOBS[job_id]['log'].append(f'🔒 Прокси сохранён: {proxy.split("@")[-1] if "@" in proxy else proxy}')
    UPLOAD_JOBS[job_id]['status'] = 'done'
    UPLOAD_JOBS[job_id]['log'].append(f'✅ Канал добавлен: {ch_name}')
    UPLOAD_JOBS[job_id]['channel'] = {'id': ch_id, 'name': ch_name}
    return creds

def upload_to_youtube(upload_job_id, files, title, description, privacy, channel_id='auto', user='pavel'):
    try:
        from googleapiclient.http import MediaFileUpload
        UPLOAD_JOBS[upload_job_id]['status'] = 'running'
        log = UPLOAD_JOBS[upload_job_id]['log']

        # Выбираем канал
        if channel_id and channel_id != 'auto':
            channels = load_channels(user)
            ch_info = channels.get(channel_id)
            ch_id = channel_id
            if not ch_info:
                raise Exception(f'Канал {channel_id} не найден')
            log.append(f'📺 Выбран канал: {ch_info["name"]}')
        else:
            ch_id, ch_info = get_best_channel(user)
        if not ch_id:
            # Fallback to old single token
            if os.path.exists(TOKEN_FILE):
                ch_info = {'name': 'Основной канал', 'token_file': TOKEN_FILE}
                ch_id = 'default'
                log.append('📺 Используем основной канал')
            else:
                raise Exception('Нет доступных каналов. Добавь хотя бы один канал через кнопку + Добавить канал.')

        log.append(f'📺 Используем канал: {ch_info["name"]}')
        ch_proxy = ch_info.get('proxy', '')
        if ch_proxy:
            log.append(f'🔒 Прокси: {ch_proxy.split("@")[-1] if "@" in ch_proxy else ch_proxy}')
        log.append('🔐 Авторизуемся...')
        yt = get_youtube_service(ch_info['token_file'], proxy=ch_proxy)
        log.append('✅ Авторизация прошла')

        links = []
        today_data = load_uploads_today()
        for f in files:
            fpath = f['path']
            ftitle = f.get('title', title)
            log.append(f"⏳ Загружаем {f['fmt']} ({f['size']}MB)...")
            body = {
                'snippet': {'title': ftitle, 'description': description, 'tags': [], 'categoryId': '22'},
                'status': {'privacyStatus': privacy}
            }
            media = MediaFileUpload(fpath, mimetype='video/mp4', resumable=True, chunksize=1024*1024*5)
            req = yt.videos().insert(part='snippet,status', body=body, media_body=media)
            response = None
            while response is None:
                status, response = req.next_chunk()
                if status:
                    pct = int(status.progress()*100)
                    log[-1] = f"⏳ Загружаем {f['fmt']} — {pct}%..."
            vid_id = response['id']
            link = f"https://youtu.be/{vid_id}"
            links.append({'fmt': f['fmt'], 'link': link, 'title': ftitle})
            log.append(f"✅ {f['fmt']} → {link}")
            # Обновляем счётчик каналов
            today_data['counts'][ch_id] = today_data['counts'].get(ch_id, 0) + 1
            save_uploads_today(today_data)
            # Обновляем счётчик проектов
            proj_id = ch_info.get('project_id')
            if proj_id:
                increment_project_upload(user, proj_id)

        UPLOAD_JOBS[upload_job_id]['links'] = links
        UPLOAD_JOBS[upload_job_id]['status'] = 'done'
        log.append('🎉 Все видео загружены на YouTube!')
    except Exception as e:
        UPLOAD_JOBS[upload_job_id]['status'] = 'error'
        UPLOAD_JOBS[upload_job_id]['log'].append(f'❌ Ошибка: {str(e)}')

def auto_convert_and_upload(job_id, src_video, n_sets, category, privacy, user):
    from googleapiclient.http import MediaFileUpload
    job = MASS_UPLOAD_JOBS[job_id]
    job['status'] = 'running'
    log = job['log']
    try:
        tmp_dir = os.path.join(OUTPUT_DIR, job_id, 'tmp')
        os.makedirs(tmp_dir, exist_ok=True)
        formats = [('9:16', 9/16, 'Shorts'), ('1:1', 1.0, 'Feed'), ('16:9', 16/9, 'YouTube')]
        converted = {}

        log.append('⏳ Конвертируем в 3 формата...')
        def even(n): return n if n % 2 == 0 else n + 1
        for fmt_name, ratio, label in formats:
            if ratio < 1:
                cw, ch = even(int(640 * ratio)), 640
            elif ratio == 1:
                cw, ch = 640, 640
            else:
                cw, ch = 640, even(int(640 / ratio))
            vf = (f'scale={cw}:{ch}:force_original_aspect_ratio=decrease,'
                  f'pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1')
            out = os.path.join(tmp_dir, f'{fmt_name.replace(":","x")}.mp4')
            import subprocess as _sp
            r = _sp.run(['ffmpeg','-y','-i',src_video,'-vf',vf,
                    '-c:v','libx264','-profile:v','baseline','-crf','22','-preset','fast',
                    '-pix_fmt','yuv420p','-c:a','aac','-b:a','128k', out],
                    capture_output=True, text=True)
            if r.returncode != 0:
                raise Exception(f'ffmpeg ошибка для {fmt_name}: {r.stderr[-500:]}')
            converted[fmt_name] = out
            log.append(f'  ✅ {fmt_name} ({label}) готов')

        all_channels = load_channels(user)
        ordered = [(k,v) for k,v in all_channels.items() if not v.get('last_error')]
        if not ordered:
            ordered = list(all_channels.items())
        n_sets = int(n_sets) if n_sets else len(ordered)
        total = n_sets * 3
        job['total'] = total
        job['done'] = 0

        ch_iter = iter(ordered)
        sets_done = 0
        while sets_done < n_sets:
            try:
                ch_id, ch_info = next(ch_iter)
            except StopIteration:
                log.append('⚠ Закончились доступные каналы')
                break
            ch_proxy = ch_info.get('proxy', '')
            log.append(f'📦 Набор {sets_done+1}/{n_sets} → канал: {ch_info["name"]}' + (' 🔒 прокси' if ch_proxy else ''))
            try:
                yt = get_youtube_service(ch_info['token_file'], proxy=ch_proxy)
            except Exception as _auth_err:
                log.append(f'  ❌ Ошибка авторизации: {_auth_err} — пропускаем канал')
                channels = load_channels(user); channels[ch_id]['last_error'] = 'Ошибка авторизации'; save_channels(user, channels)
                continue
            if not ch_proxy:
                os.environ.pop('HTTPS_PROXY', None)
                os.environ.pop('HTTP_PROXY', None)

            # Generate unique title+description via AI (same as /ai_generate)
            unique_title = f'{category} — видео {sets_done+1}'
            unique_desc = ''
            try:
                import urllib.request as _ur2, json as _json2, random as _r2
                _seed2 = _r2.randint(10000, 99999)
                _prompt2 = (
                    f"You are a YouTube lifestyle vlogger. Session: {_seed2}.\n"
                    "Write a YouTube title and description IN ENGLISH ONLY for a personal lifestyle video about daily habits and wellness.\n\n"
                    "RULES:\n"
                    "- Write ONLY about daily habits, routines, personal experience — NOT about any disease or condition\n"
                    "- FORBIDDEN words (any of these = instant rejection): diabetes, blood sugar, prostate, parasite, cancer, cholesterol, pressure, weight, fat, slim, diet, sugar, insulin, glucose, secret, hidden, truth, reveals, doctor, cure, treat, heal, natural, remedy, medication, drug, clinical, proven, guaranteed, miracle, control, manage, reverse, eliminate, boost\n"
                    "- Style: personal story, first-person, curious, conversational\n"
                    "- Title: max 60 chars, must feel like a real person sharing their experience\n"
                    "- Description: 2 short sentences, no health claims, no promises\n\n"
                    "WRITE titles like these (copy this exact tone):\n"
                    "TITLE: I tried waking up at 5am for 30 days — here's what happened\n"
                    "TITLE: The one thing I stopped doing that changed my mornings\n"
                    "TITLE: My honest 60-day habit experiment results\n"
                    "TITLE: What I learned after changing my evening routine\n\n"
                    "Respond EXACTLY in this format:\n"
                    "TITLE: [title here]\n"
                    "DESCRIPTION: [description here]"
                )
                _key2 = get_anthropic_key()
                if _key2:
                    import requests as _req_lib
                    _resp2 = _req_lib.post('https://api.anthropic.com/v1/messages',
                        json={'model':'claude-haiku-4-5-20251001','max_tokens':300,
                              'messages':[{'role':'user','content':_prompt2}]},
                        headers={'x-api-key':_key2,'anthropic-version':'2023-06-01'},
                        timeout=20)
                    _text2 = _resp2.json()['content'][0]['text']
                    log.append(f'  🤖 AI: {_text2[:80]}')
                    _tm = __import__('re').search(r'TITLE:\s*(.+)', _text2)
                    _dm = __import__('re').search(r'DESCRIPTION:\s*([\s\S]+)', _text2)
                    if _tm: unique_title = _tm.group(1).strip()
                    if _dm: unique_desc = _dm.group(1).strip()
                    log.append(f'  ✅ Заголовок: {unique_title}')
            except Exception as _e2:
                import traceback as _tb
                log.append(f'  ⚠ AI ошибка: {type(_e2).__name__}: {_e2}')

            set_links = []
            today_data = load_uploads_today()
            ch_error = None

            def _gen_ai_title(log_ref):
                _t, _d = f'Lifestyle video', ''
                try:
                    import requests as _rq, random as _rnd, re as _re
                    _s = _rnd.randint(10000,99999)
                    _p = (
                        f"You are a YouTube lifestyle vlogger. Session: {_s}.\n"
                        "Write a YouTube title and description IN ENGLISH ONLY about daily habits and personal experience.\n\n"
                        "MANDATORY RULES:\n"
                        "- NEVER mention: health, disease, diabetes, blood sugar, prostate, cancer, weight, fat, cholesterol, pressure, parasites, vision, memory, joints, stomach, pain, cure, treat, heal, secret, hidden, doctor, natural, remedy, medication, drug, miracle, guaranteed, manage, reverse, eliminate, boost, control\n"
                        "- Write about: morning routines, habits, productivity, sleep, energy, mindset, lifestyle experiments\n"
                        "- Style: first-person, personal story, conversational\n"
                        "- Title: max 60 chars\n"
                        "- Description: 2 sentences, friendly, no health claims\n\n"
                        "EXAMPLES:\n"
                        "TITLE: I tried waking up at 5am for 30 days\n"
                        "TITLE: The one habit I stopped that changed everything\n"
                        "TITLE: My honest results after 60 days of this routine\n\n"
                        "Respond EXACTLY:\n"
                        "TITLE: [title]\n"
                        "DESCRIPTION: [description]"
                    )
                    _key = get_anthropic_key()
                    if _key:
                        _r = _rq.post('https://api.anthropic.com/v1/messages',
                            json={'model':'claude-haiku-4-5-20251001','max_tokens':300,
                                  'messages':[{'role':'user','content':_p}]},
                            headers={'x-api-key':_key,'anthropic-version':'2023-06-01'}, timeout=20)
                        _txt = _r.json()['content'][0]['text']
                        _tm = _re.search(r'TITLE:\s*(.+)', _txt)
                        _dm = _re.search(r'DESCRIPTION:\s*([\s\S]+)', _txt)
                        if _tm: _t = _tm.group(1).strip()
                        if _dm: _d = _dm.group(1).strip()
                except Exception as _e:
                    log_ref.append(f'  ⚠ AI: {_e}')
                return _t, _d

            for fmt_name, _, label in formats:
                fpath = converted[fmt_name]
                fmt_title, fmt_desc = _gen_ai_title(log)
                log.append(f'  🤖 {fmt_name}: {fmt_title}')
                log.append(f'  ⏳ Загружаем {fmt_name}...')
                try:
                    body = {
                        'snippet': {'title': fmt_title, 'description': fmt_desc, 'tags': [], 'categoryId': '22'},
                        'status': {'privacyStatus': privacy}
                    }
                    media = MediaFileUpload(fpath, mimetype='video/mp4', resumable=True, chunksize=1024*1024*5)
                    req = yt.videos().insert(part='snippet,status', body=body, media_body=media)
                    response = None
                    while response is None:
                        status_obj, response = req.next_chunk()
                        if status_obj:
                            pct = int(status_obj.progress() * 100)
                            log[-1] = f'  ⏳ {fmt_name} — {pct}%...'
                    vid_id = response['id']
                    link = f'https://youtu.be/{vid_id}'
                    set_links.append({'fmt': fmt_name, 'link': link})
                    log[-1] = f'  ✅ {fmt_name} → {link}'
                    today_data['counts'][ch_id] = today_data['counts'].get(ch_id, 0) + 1
                    save_uploads_today(today_data)
                    proj_id = ch_info.get('project_id')
                    if proj_id:
                        increment_project_upload(user, proj_id)
                    job['done'] += 1
                except Exception as _upload_err:
                    err_msg = str(_upload_err)[:80]
                    log[-1] = f'  ❌ {fmt_name} ошибка: {err_msg}'
                    ch_error = err_msg
                    job['done'] += 1
            if ch_error:
                channels = load_channels(user); channels[ch_id]['last_error'] = ch_error; save_channels(user, channels)
                log.append(f'  ⚠ Канал {ch_info["name"]} помечен с ошибкой, следующий запуск пропустит его')
            else:
                channels = load_channels(user)
                if channels.get(ch_id, {}).get('last_error'):
                    channels[ch_id].pop('last_error', None); save_channels(user, channels)
            job['sets'].append({'set_idx': sets_done+1, 'channel': ch_info['name'], 'links': set_links})
            sets_done += 1

        job['status'] = 'done'
        log.append(f'🎉 Готово! {n_sets} аккаунтов × 3 формата = {total} видео загружено!')
    except Exception as e:
        job['status'] = 'error'
        log.append(f'❌ Ошибка: {str(e)}')


def ready_upload_to_youtube(job_id, ready_files, n_sets, category, privacy, user):
    """Upload already-converted videos directly to YouTube without re-encoding."""
    from googleapiclient.http import MediaFileUpload
    job = MASS_UPLOAD_JOBS[job_id]
    job['status'] = 'running'
    log = job['log']
    try:
        total = n_sets * len(ready_files)
        job['total'] = total
        job['done'] = 0
        for i in range(n_sets):
            ch_id, ch_info = get_best_channel(user)
            if not ch_id:
                raise Exception('Нет доступных каналов (все лимиты исчерпаны)')
            ch_proxy = ch_info.get('proxy', '')
            log.append(f'📦 Аккаунт {i+1}/{n_sets} → {ch_info["name"]}' + (' 🔒' if ch_proxy else ''))
            yt = get_youtube_service(ch_info['token_file'], proxy=ch_proxy)
            if not ch_proxy:
                os.environ.pop('HTTPS_PROXY', None)
                os.environ.pop('HTTP_PROXY', None)
            set_links = []
            today_data = load_uploads_today()
            # Generate unique title via AI
            title_ai = f'{category} — видео {i+1}'
            desc_ai = ''
            try:
                import urllib.request as _ur2, json as _json2, random as _r2
                _seed2 = _r2.randint(10000, 99999)
                _prompt2 = (
                    f"You are a YouTube lifestyle vlogger. Session: {_seed2}.\n"
                    "Write a YouTube title and description IN ENGLISH ONLY for a personal lifestyle video about daily habits and wellness.\n\n"
                    "RULES:\n"
                    "- Write ONLY about daily habits, routines, personal experience — NOT about any disease or condition\n"
                    "- FORBIDDEN words (any of these = instant rejection): diabetes, blood sugar, prostate, parasite, cancer, cholesterol, pressure, weight, fat, slim, diet, sugar, insulin, glucose, secret, hidden, truth, reveals, doctor, cure, treat, heal, natural, remedy, medication, drug, clinical, proven, guaranteed, miracle, control, manage, reverse, eliminate, boost\n"
                    "- Style: personal story, first-person, curious, conversational\n"
                    "- Title: max 60 chars, must feel like a real person sharing their experience\n"
                    "- Description: 2 short sentences, no health claims, no promises\n\n"
                    "WRITE titles like these (copy this exact tone):\n"
                    "TITLE: I tried waking up at 5am for 30 days — here's what happened\n"
                    "TITLE: The one thing I stopped doing that changed my mornings\n"
                    "TITLE: My honest 60-day habit experiment results\n"
                    "TITLE: What I learned after changing my evening routine\n\n"
                    "Respond EXACTLY in this format:\n"
                    "TITLE: [title here]\n"
                    "DESCRIPTION: [description here]"
                )
                _key2 = get_anthropic_key()
                if _key2:
                    import requests as _req_lib
                    _resp2 = _req_lib.post('https://api.anthropic.com/v1/messages',
                        json={'model':'claude-haiku-4-5-20251001','max_tokens':300,
                              'messages':[{'role':'user','content':_prompt2}]},
                        headers={'x-api-key':_key2,'anthropic-version':'2023-06-01'},
                        timeout=20)
                    _text2 = _resp2.json()['content'][0]['text']
                    log.append(f'  🤖 AI: {_text2[:80]}')
                    _tm = __import__('re').search(r'TITLE:\s*(.+)', _text2)
                    _dm = __import__('re').search(r'DESCRIPTION:\s*([\s\S]+)', _text2)
                    if _tm: title_ai = _tm.group(1).strip()
                    if _dm: desc_ai = _dm.group(1).strip()
                    log.append(f'  ✅ Заголовок: {title_ai}')
            except Exception as _e2:
                log.append(f'  ⚠ AI ошибка: {type(_e2).__name__}: {_e2}')
            for rf in ready_files:
                fpath = rf['path']
                fmt = rf['fmt']
                log.append(f'  ⏳ Загружаем {fmt}...')
                body = {
                    'snippet': {'title': title_ai, 'description': desc_ai, 'tags': [], 'categoryId': '22'},
                    'status': {'privacyStatus': privacy}
                }
                media = MediaFileUpload(fpath, mimetype='video/mp4', resumable=True, chunksize=1024*1024*5)
                req = yt.videos().insert(part='snippet,status', body=body, media_body=media)
                response = None
                while response is None:
                    status_obj, response = req.next_chunk()
                    if status_obj:
                        pct = int(status_obj.progress()*100)
                        log[-1] = f'  ⏳ {fmt} — {pct}%...'
                vid_id = response['id']
                link = f'https://youtu.be/{vid_id}'
                set_links.append({'fmt': fmt, 'link': link})
                log[-1] = f'  ✅ {fmt} → {link}'
                today_data['counts'][ch_id] = today_data['counts'].get(ch_id, 0) + 1
                save_uploads_today(today_data)
                proj_id = ch_info.get('project_id')
                if proj_id:
                    increment_project_upload(user, proj_id)
                job['done'] += 1
            job['sets'].append({'set_idx': i+1, 'channel': ch_info['name'], 'links': set_links})
        job['status'] = 'done'
        log.append(f'🎉 Готово! {n_sets} аккаунтов × {len(ready_files)} форматов = {total} видео!')
    except Exception as e:
        job['status'] = 'error'
        log.append(f'❌ Ошибка: {str(e)}')


def mass_upload_to_youtube(job_id, files, n_sets, title, description, privacy, user):
    from googleapiclient.http import MediaFileUpload
    job = MASS_UPLOAD_JOBS[job_id]
    job['status'] = 'running'
    log = job['log']
    try:
        total = n_sets * len(files)
        job['total'] = total
        job['done'] = 0
        for i in range(n_sets):
            ch_id, ch_info = get_best_channel(user)
            if not ch_id:
                raise Exception(f'Нет доступных каналов (все лимиты исчерпаны)')
            ch_proxy = ch_info.get('proxy', '')
            log.append(f'📦 Набор {i+1}/{n_sets} → канал: {ch_info["name"]}' + (f' 🔒 прокси' if ch_proxy else ''))
            yt = get_youtube_service(ch_info['token_file'], proxy=ch_proxy)
            if not ch_proxy:
                os.environ.pop('HTTPS_PROXY', None)
                os.environ.pop('HTTP_PROXY', None)
            set_links = []
            today_data = load_uploads_today()
            for f in files:
                fpath = f['path']
                ftitle = f.get('title', title)
                log.append(f'  ⏳ Загружаем {f["fmt"]}...')
                body = {
                    'snippet': {'title': ftitle, 'description': description, 'tags': [], 'categoryId': '22'},
                    'status': {'privacyStatus': privacy}
                }
                media = MediaFileUpload(fpath, mimetype='video/mp4', resumable=True, chunksize=1024*1024*5)
                req = yt.videos().insert(part='snippet,status', body=body, media_body=media)
                response = None
                while response is None:
                    status_obj, response = req.next_chunk()
                    if status_obj:
                        pct = int(status_obj.progress()*100)
                        log[-1] = f'  ⏳ {f["fmt"]} — {pct}%...'
                vid_id = response['id']
                link = f'https://youtu.be/{vid_id}'
                set_links.append({'fmt': f['fmt'], 'link': link})
                log[-1] = f'  ✅ {f["fmt"]} → {link}'
                today_data['counts'][ch_id] = today_data['counts'].get(ch_id, 0) + 1
                save_uploads_today(today_data)
                proj_id = ch_info.get('project_id')
                if proj_id:
                    increment_project_upload(user, proj_id)
                job['done'] += 1
            job['sets'].append({'set_idx': i+1, 'channel': ch_info['name'], 'links': set_links})
        job['status'] = 'done'
        log.append(f'🎉 Готово! {n_sets} наборов × {len(files)} форматов = {total} видео загружено!')
    except Exception as e:
        job['status'] = 'error'
        log.append(f'❌ Ошибка: {str(e)}')

HTML = r"""<!DOCTYPE html>
<html lang="ru" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Video Editor — Нутра</title>
<style>
:root{
  --bg:#f0f2ff;--bg2:#e8eaff;--surface:#ffffff;--surface2:#f7f8ff;
  --border:#e0e3ff;--border2:#c7ccf5;
  --text:#1a1a2e;--text2:#5a5f7d;--text3:#9098c0;
  --accent1:#6c63ff;--accent2:#ff6584;--accent3:#43e97b;--accent4:#fa8231;
  --accent1d:#5a52e0;--accent2d:#e0506e;
  --grad1:linear-gradient(135deg,#6c63ff,#a855f7);
  --grad2:linear-gradient(135deg,#f093fb,#f5576c);
  --grad3:linear-gradient(135deg,#43e97b,#38f9d7);
  --grad4:linear-gradient(135deg,#fa8231,#f7b733);
  --grad5:linear-gradient(135deg,#4facfe,#00f2fe);
  --shadow:0 2px 12px rgba(108,99,255,.10);
  --shadow2:0 4px 24px rgba(108,99,255,.18);
  --card-border:1px solid var(--border);
  --input-bg:#f7f8ff;--input-border:#d0d5f5;
  --log-bg:#1a1a2e;--log-text:#7eff7e;
  --toggle-off:#d0d5f5;--toggle-on:var(--accent1);
}
[data-theme="dark"]{
  --bg:#0f0f1a;--bg2:#141428;--surface:#1a1a2e;--surface2:#20203a;
  --border:#2a2a4a;--border2:#3a3a5a;
  --text:#e8eaff;--text2:#9098c0;--text3:#5a5f7d;
  --shadow:0 2px 12px rgba(0,0,0,.4);
  --shadow2:0 4px 24px rgba(108,99,255,.3);
  --card-border:1px solid var(--border);
  --input-bg:#20203a;--input-border:#3a3a5a;
  --toggle-off:#3a3a5a;
}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;padding:2rem 1rem;transition:background .3s,color .3s;}
.wrap{max-width:700px;margin:0 auto;}

/* Header */
.header{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;}
h1{font-size:24px;font-weight:800;background:var(--grad1);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}
.sub{font-size:13px;color:var(--text3);margin-bottom:24px;}

/* Theme toggle */
.theme-btn{display:flex;align-items:center;gap:6px;padding:8px 14px;border:var(--card-border);border-radius:20px;background:var(--surface);cursor:pointer;font-size:13px;font-weight:600;color:var(--text2);transition:.2s;box-shadow:var(--shadow);}
.theme-btn:hover{border-color:var(--accent1);color:var(--accent1);}

/* Cards */
.card{background:var(--surface);border:var(--card-border);border-radius:16px;padding:20px;margin-bottom:14px;box-shadow:var(--shadow);transition:background .3s,border .3s;}
.card:hover{box-shadow:var(--shadow2);}
.card-title{font-size:11px;font-weight:800;color:var(--text3);text-transform:uppercase;letter-spacing:.08em;margin-bottom:14px;display:flex;align-items:center;gap:6px;}
.card-title-accent{display:inline-block;width:3px;height:14px;border-radius:2px;background:var(--grad1);}

/* Drop zones */
.drop{border:2px dashed var(--border2);border-radius:12px;padding:24px;text-align:center;cursor:pointer;transition:.2s;background:var(--surface2);}
.drop:hover,.drop.drag{background:var(--bg2);border-color:var(--accent1);}
.drop.ok{border-color:#43e97b;background:rgba(67,233,123,.08);}
.drop-icon{font-size:28px;margin-bottom:6px;}
.drop-text{font-size:13px;color:var(--text3);}
.drop-text.ok{color:#22c55e;font-weight:600;}

/* Toggles */
.toggle-row{display:flex;align-items:center;justify-content:space-between;}
.toggle-label{font-size:14px;font-weight:600;color:var(--text);}
.switch{position:relative;width:46px;height:26px;cursor:pointer;}
.switch input{opacity:0;width:0;height:0;}
.slider{position:absolute;inset:0;background:var(--toggle-off);border-radius:26px;transition:.25s;}
.slider:before{content:'';position:absolute;width:20px;height:20px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.25s;box-shadow:0 1px 4px rgba(0,0,0,.2);}
input:checked+.slider{background:var(--grad1);}
input:checked+.slider:before{transform:translateX(20px);}

/* Extra panels */
.extra{margin-top:14px;display:none;}
.extra.show{display:block;}
.row{display:flex;align-items:center;gap:10px;margin-top:10px;}
.row label{font-size:13px;color:var(--text2);white-space:nowrap;}
input[type=range]{flex:1;accent-color:var(--accent1);cursor:pointer;}
.val{font-size:13px;font-weight:700;min-width:48px;text-align:right;color:var(--accent1);}
input[type=text],textarea{width:100%;padding:10px 14px;border:1.5px solid var(--input-border);border-radius:10px;font-size:14px;margin-top:8px;background:var(--input-bg);color:var(--text);transition:.2s;outline:none;}
input[type=text]:focus,textarea:focus{border-color:var(--accent1);box-shadow:0 0 0 3px rgba(108,99,255,.15);}

/* Format buttons */
.fmt-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;}
.fmt-btn{border:2px solid var(--border);border-radius:12px;padding:16px 8px;text-align:center;cursor:pointer;user-select:none;transition:.2s;background:var(--surface2);}
.fmt-btn.on{border-color:var(--accent1);background:rgba(108,99,255,.08);}
.fmt-btn.on .fmt-ratio{background:var(--grad1);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}
.fmt-ratio{font-size:22px;font-weight:800;display:block;margin-bottom:3px;color:var(--text);}
.fmt-name{font-size:11px;color:var(--text3);}

/* Main buttons */
.btn{width:100%;padding:15px;font-size:16px;font-weight:800;border-radius:14px;background:var(--grad1);color:#fff;border:none;cursor:pointer;margin-top:6px;transition:.2s;letter-spacing:.02em;box-shadow:0 4px 15px rgba(108,99,255,.35);}
.btn:disabled{opacity:.35;cursor:not-allowed;box-shadow:none;}
.btn:not(:disabled):hover{transform:translateY(-1px);box-shadow:0 6px 20px rgba(108,99,255,.45);}
.btn:not(:disabled):active{transform:translateY(0);}
.btn-yt{background:var(--grad2);box-shadow:0 4px 15px rgba(245,87,108,.35);}
.btn-yt:not(:disabled):hover{box-shadow:0 6px 20px rgba(245,87,108,.5);}
.btn-green{background:var(--grad3);box-shadow:0 4px 15px rgba(67,233,123,.3);}

/* Progress */
.progress{display:none;margin-top:16px;}
.prog-bar-wrap{background:var(--border);border-radius:8px;height:8px;margin-bottom:12px;overflow:hidden;}
.prog-bar{height:8px;border-radius:8px;background:var(--grad1);width:0%;transition:width .4s;}
.log{background:#0d0d1a;color:#7eff7e;border-radius:12px;padding:14px;font-size:12px;font-family:monospace;max-height:200px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;border:1px solid #2a2a4a;}

/* Downloads */
.downloads{display:none;flex-direction:column;gap:10px;margin-top:16px;}
.dl-btn{display:flex;align-items:center;gap:12px;padding:14px 16px;background:var(--surface);border:var(--card-border);border-radius:14px;text-decoration:none;color:var(--text);font-size:14px;font-weight:600;transition:.2s;box-shadow:var(--shadow);}
.dl-btn:hover{border-color:var(--accent1);transform:translateX(3px);box-shadow:var(--shadow2);}
.dl-badge{background:var(--grad1);color:#fff;font-size:11px;font-weight:700;padding:4px 10px;border-radius:8px;}

/* YouTube section */
.yt-section{display:none;margin-top:16px;}
.yt-card{background:var(--surface);border:2px solid rgba(255,101,132,.4);border-radius:16px;padding:20px;box-shadow:0 4px 20px rgba(255,101,132,.1);}
.yt-title{font-size:15px;font-weight:800;background:var(--grad2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:14px;}
.yt-links{display:flex;flex-direction:column;gap:8px;margin-top:14px;}
.yt-link{display:flex;align-items:center;gap:10px;padding:12px 14px;background:rgba(255,101,132,.07);border:1px solid rgba(255,101,132,.3);border-radius:10px;text-decoration:none;color:#f5576c;font-size:13px;font-weight:600;}
.yt-link:hover{background:rgba(255,101,132,.14);}
.yt-log{background:#0d0d1a;color:#ff9999;border-radius:10px;padding:12px;font-size:11px;font-family:monospace;max-height:140px;overflow-y:auto;white-space:pre-wrap;margin-top:10px;border:1px solid #2a2a4a;}
.up-progress-bar{height:6px;background:var(--border);border-radius:3px;margin:8px 0;}
.up-progress-fill{height:100%;border-radius:3px;background:linear-gradient(90deg,#4f46e5,#7c3aed);transition:width .3s;}
.mass-result-table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px;}
.mass-result-table th{background:var(--surface2);padding:7px 9px;text-align:left;font-weight:700;border:1px solid var(--border);color:var(--text2);font-size:11px;}
.mass-result-table td{padding:7px 9px;border:1px solid var(--border);vertical-align:middle;}
.fmt-tag{display:inline-block;padding:2px 7px;border-radius:5px;font-size:10px;font-weight:800;text-decoration:none;}
.fmt-tag-916{background:#ede9fe;color:#7c3aed;}
.fmt-tag-11{background:#fef3c7;color:#d97706;}
.fmt-tag-169{background:#dbeafe;color:#1d4ed8;}

/* Privacy */
.privacy-row{display:flex;gap:8px;margin-top:10px;}
.privacy-btn{flex:1;padding:9px;border:1.5px solid var(--border);border-radius:10px;font-size:13px;text-align:center;cursor:pointer;background:var(--surface2);color:var(--text2);transition:.2s;font-weight:600;}
.privacy-btn.on{border-color:var(--accent1);background:rgba(108,99,255,.1);color:var(--accent1);}

/* Tabs */
.tabs{display:flex;gap:4px;margin-bottom:24px;background:var(--surface);border-radius:14px;padding:5px;box-shadow:var(--shadow);overflow-x:auto;}
.tab-btn{padding:9px 16px;font-size:13px;font-weight:700;border:none;background:none;cursor:pointer;color:var(--text3);border-radius:10px;transition:.2s;white-space:nowrap;}
.tab-btn.active{background:var(--grad1);color:#fff;box-shadow:0 2px 10px rgba(108,99,255,.3);}
.tab-pane{display:none;}
.tab-pane.active{display:block;}

/* Lang/cat buttons */
.lang-grid{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;}
.lang-btn{padding:7px 13px;border:1.5px solid var(--border);border-radius:20px;background:var(--surface2);font-size:12px;cursor:pointer;color:var(--text2);font-weight:600;transition:.2s;}
.lang-btn:hover{border-color:var(--accent1);color:var(--accent1);}
.lang-btn.on{background:var(--grad1);border-color:transparent;color:#fff;box-shadow:0 2px 8px rgba(108,99,255,.3);}

/* Result table */
.result-table{width:100%;border-collapse:collapse;margin-top:12px;font-size:13px;}
.result-table th{background:var(--surface2);padding:9px 12px;text-align:left;font-weight:700;border:1px solid var(--border);color:var(--text2);}
.result-table td{padding:9px 12px;border:1px solid var(--border);vertical-align:top;line-height:1.4;color:var(--text);}
.result-table tr:hover td{background:rgba(108,99,255,.04);}
.copy-btn{padding:5px 10px;font-size:11px;border:1.5px solid var(--border);border-radius:8px;background:var(--surface2);cursor:pointer;color:var(--text2);font-weight:600;transition:.2s;}
.copy-btn:hover{border-color:var(--accent1);color:var(--accent1);}

/* Info box */
.info{background:rgba(108,99,255,.07);border:1px solid rgba(108,99,255,.25);border-radius:12px;padding:13px 16px;font-size:13px;color:var(--accent1);margin-bottom:20px;line-height:1.6;display:flex;gap:8px;align-items:flex-start;}

/* AI result */
.ai-result{background:rgba(67,233,123,.07);border:1px solid rgba(67,233,123,.3);border-radius:12px;padding:14px;margin-top:10px;display:none;}
.ai-result-label{font-size:11px;font-weight:800;color:#22c55e;margin-bottom:5px;text-transform:uppercase;letter-spacing:.05em;}
.ai-result-text{font-size:13px;color:var(--text);line-height:1.5;}

/* AI buttons */
.btn-ai{width:100%;padding:12px;font-size:14px;font-weight:700;border-radius:12px;background:linear-gradient(135deg,#a855f7,#6c63ff);color:#fff;border:none;cursor:pointer;margin-top:8px;box-shadow:0 4px 14px rgba(168,85,247,.3);transition:.2s;}
.btn-ai:disabled{opacity:.4;}
.btn-ai:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 6px 18px rgba(168,85,247,.4);}

/* Colored topic chips */
.topic-chip{padding:7px 14px;border-radius:20px;font-size:13px;cursor:pointer;font-weight:700;border:none;transition:.2s;}
.topic-chip:hover{transform:scale(1.05);}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <div>
      <h1>🎬 Video Editor</h1>
      <p class="sub">Белый голос · Субтитры · Хвост · 3 формата · YouTube</p>
    </div>
    <div style="display:flex;gap:8px;align-items:center;">
      <span id="app-version" style="font-size:12px;font-weight:700;color:#7c3aed;background:rgba(124,58,237,0.1);padding:3px 8px;border-radius:6px;margin-right:8px;">v...</span>
      <button id="update-btn" onclick="checkUpdate()" style="padding:6px 14px;font-size:12px;font-weight:600;border:1.5px solid #10b981;border-radius:10px;background:transparent;cursor:pointer;color:#10b981;">🔄 Обновить</button>
      <button class="theme-btn" onclick="toggleTheme()" id="theme-btn">🌙 Тёмная</button>
    </div>
  </div>
  <div class="tabs" style="display:flex;align-items:center;gap:4px;">
    <button class="tab-btn active" onclick="switchTab('editor')">🎬 Редактор</button>
    <button class="tab-btn" onclick="switchTab('ads')">📢 Заголовки и описания</button>
    <button class="tab-btn" onclick="switchTab('upload')">📤 Загрузить на YouTube</button>
    <button class="tab-btn" onclick="switchTab('tasks')">📋 Таски</button>
    <button class="tab-btn" onclick="switchTab('binom')">📊 Binom</button>
    <div style="flex:1;"></div>
    <button onclick="addChannel()" style="padding:7px 14px;font-size:12px;font-weight:700;border:1.5px solid var(--accent1);border-radius:10px;background:transparent;cursor:pointer;color:var(--accent1);white-space:nowrap;">📺 + Канал</button>
  </div>
  <div id="tab-editor" class="tab-pane active">
  
  <div class="info"><span>⚡</span><span>Всё обрабатывается локально на твоём Mac. Готовые видео можно сразу загрузить на YouTube.</span></div>

  <div class="card">
    <div class="card-title">🎥 Креатив (видео)</div>
    <div class="drop" id="vdrop" onclick="pickFile('video')">
      <div class="drop-icon">📁</div>
      <div class="drop-text" id="vlbl">Нажми или перетащи MP4 / MOV</div>
    </div>
  </div>



  <div class="card">
    <div class="toggle-row">
      <span class="toggle-label">🔇 Белый голос</span>
      <label class="switch"><input type="checkbox" id="voice-on" onchange="toggle('voice-extra',this)"><span class="slider"></span></label>
    </div>
    <div class="extra" id="voice-extra">
      <div class="drop" id="adrop" onclick="pickFile('audio')" style="margin-top:12px;">
        <div class="drop-icon">🎙️</div>
        <div class="drop-text" id="albl">MP3 / WAV / M4A</div>
      </div>
      <div class="row">
        <label>Громкость:</label>
        <input type="range" id="vol" min="1" max="15" value="5" oninput="document.getElementById('vol-val').textContent=this.value+'%'">
        <span class="val" id="vol-val">5%</span>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="toggle-row">
      <span class="toggle-label">✍️ Закрыть субтитры полосой</span>
      <label class="switch"><input type="checkbox" id="overlay-on" onchange="toggle('overlay-extra',this)"><span class="slider"></span></label>
    </div>
    <div class="extra" id="overlay-extra">
      <div style="display:flex;gap:16px;align-items:flex-start;margin-top:12px;">
        <div style="flex:1;">
          <input type="text" id="overlay-txt" placeholder="Текст на полосе" value="JEST ROZWIAZANIE" oninput="updatePreview()">
          <div class="row">
            <label>Размер шрифта:</label>
            <input type="range" id="overlay-size" min="12" max="60" value="32" oninput="document.getElementById('overlay-size-val').textContent=this.value+'px';updatePreview()">
            <span class="val" id="overlay-size-val">32px</span>
          </div>
          <div class="row">
            <label>Высота полосы:</label>
            <input type="range" id="bar-pct" min="10" max="35" value="20" oninput="document.getElementById('bar-pct-val').textContent=this.value+'%';updatePreview()">
            <span class="val" id="bar-pct-val">20%</span>
          </div>
          <div class="row" style="margin-top:10px;">
            <label>Цвет полосы:</label>
            <input type="color" id="bar-color" value="#000000" oninput="updatePreview()" style="width:40px;height:32px;border:1px solid #e0e0e0;border-radius:8px;cursor:pointer;padding:2px;">
            <label style="margin-left:16px;">Цвет текста:</label>
            <input type="color" id="txt-color" value="#ffffff" oninput="updatePreview()" style="width:40px;height:32px;border:1px solid #e0e0e0;border-radius:8px;cursor:pointer;padding:2px;">
          </div>
        </div>
        <div style="flex-shrink:0;">
          <div style="font-size:11px;color:#999;text-align:center;margin-bottom:6px;">Превью</div>
          <canvas id="overlay-preview" width="160" height="284" style="border-radius:10px;border:1.5px solid #e5e5e5;display:block;background:#222;"></canvas>
        </div>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="toggle-row">
      <span class="toggle-label">🖼️ Хвост (фото в конце)</span>
      <label class="switch"><input type="checkbox" id="tail-on" onchange="toggle('tail-extra',this)"><span class="slider"></span></label>
    </div>
    <div class="extra" id="tail-extra">
      <div style="display:flex;gap:10px;margin-top:12px;margin-bottom:8px;">
        <div class="drop" id="idrop" onclick="pickFile('img')" style="flex:1;min-width:0;">
          <div class="drop-icon">🖼️</div>
          <div class="drop-text" id="ilbl">Фото JPG/PNG</div>
        </div>
        <div class="drop" id="tail-vdrop" onclick="pickFile('tail_video')" style="flex:1;min-width:0;">
          <div class="drop-icon">🎬</div>
          <div class="drop-text" id="tail-vlbl">Видео MP4/MOV</div>
        </div>
      </div>
      <div class="row">
        <label>Длительность:</label>
        <input type="range" id="tail-min" min="1" max="10" value="3" oninput="document.getElementById('tail-min-val').textContent=this.value+' мин'">
        <span class="val" id="tail-min-val">3 мин</span>
      </div>
      <div class="row">
        <label>Громкость голоса в хвосте:</label>
        <input type="range" id="tail-vol" min="0" max="200" value="100" oninput="document.getElementById('tail-vol-val').textContent=this.value+'%'">
        <span class="val" id="tail-vol-val">100%</span>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-title" style="display:flex;align-items:center;justify-content:space-between;">
      <span>🎲 Уникализация (шумы)</span>
      <label class="switch"><input type="checkbox" id="noise-on" onchange="document.getElementById('noise-extra').classList.toggle('show',this.checked)"><span class="slider"></span></label>
    </div>
    <div class="extra" id="noise-extra">
      <div class="row" style="margin-top:10px;">
        <label>Сила шума:</label>
        <input type="range" id="noise-strength" min="1" max="8" value="3" oninput="document.getElementById('noise-val').textContent=this.value">
        <span class="val" id="noise-val">3</span>
      </div>
      <div style="font-size:11px;color:#999;margin-top:6px;">1-3 почти незаметно · 4-6 лёгкое зерно · 7-8 заметно</div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">📐 Форматы экспорта</div>
    <div class="fmt-grid">
      <div class="fmt-btn on" id="fmt-916" onclick="toggleFmt(this,'9:16')"><span class="fmt-ratio">9:16</span><span class="fmt-name">Stories</span></div>
      <div class="fmt-btn on" id="fmt-11" onclick="toggleFmt(this,'1:1')"><span class="fmt-ratio">1:1</span><span class="fmt-name">Feed</span></div>
      <div class="fmt-btn on" id="fmt-169" onclick="toggleFmt(this,'16:9')"><span class="fmt-ratio">16:9</span><span class="fmt-name">YouTube</span></div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">🤖 AI — название и описание</div>
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;">
      <button onclick="setTopic(this)" class="topic-chip" style="background:linear-gradient(135deg,#a8edea,#fed6e3);color:#444;">🦴 Суставы</button>
      <button onclick="setTopic(this)" class="topic-chip" style="background:linear-gradient(135deg,#ff9a9e,#fecfef);color:#444;">🩸 Диабет</button>
      <button onclick="setTopic(this)" class="topic-chip" style="background:linear-gradient(135deg,#a18cd1,#fbc2eb);color:#444;">🫀 Гипертония</button>
      <button onclick="setTopic(this)" class="topic-chip" style="background:linear-gradient(135deg,#fddb92,#d1fdff);color:#444;">⚖️ Похудение</button>
      <button onclick="setTopic(this)" class="topic-chip" style="background:linear-gradient(135deg,#43e97b,#38f9d7);color:#444;">🦠 Паразиты</button>
      <button onclick="setTopic(this)" class="topic-chip" style="background:linear-gradient(135deg,#4facfe,#00f2fe);color:#444;">💊 Простатит</button>
      <button onclick="setTopic(this)" class="topic-chip" style="background:linear-gradient(135deg,#f093fb,#f5576c);color:#fff;">💪 Потенция</button>
      <button onclick="setTopic(this)" class="topic-chip" style="background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;">💧 Цистит</button>
    </div>
    <input type="text" id="ai-topic" placeholder="или введи свою тему..." style="width:100%;padding:9px 12px;border:1px solid #e0e0e0;border-radius:8px;font-size:14px;margin-bottom:8px;">
    <button class="btn-ai" id="ai-btn" onclick="generateMeta()">✨ Сгенерировать название и описание</button>
    <div class="ai-result" id="ai-result" style="margin-top:10px;">
      <div class="ai-result-label">📌 Название:</div>
      <div class="ai-result-text" id="ai-title-out"></div>
      <div class="ai-result-label" style="margin-top:8px;">📝 Описание:</div>
      <div class="ai-result-text" id="ai-desc-out"></div>
      <button class="btn-ai" onclick="applyMeta()" style="background:#16a34a;margin-top:8px;">✅ Применить</button>
    </div>
    <input type="text" id="vid-title" style="display:none;">
  </div>

  <button class="btn" id="go-btn" onclick="startJob()" disabled>▶ Собрать видео</button>

  <div class="progress" id="progress">
    <div class="prog-bar-wrap"><div class="prog-bar" id="prog-bar"></div></div>
    <div class="log" id="log-box"></div>
  </div>

  <div class="downloads" id="downloads"></div>

  <!-- YouTube секция -->
  <div class="yt-section" id="yt-section">
    <div class="yt-card">
      <div class="yt-title">🎬 Загрузить на YouTube</div>
      <div id="channels-section" style="margin-bottom:14px;">
        <div style="font-size:12px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">📺 Каналы</div>
        <div id="channels-list" style="display:flex;flex-direction:column;gap:8px;margin-bottom:10px;"></div>
        <button onclick="addChannel()" style="width:100%;padding:9px;font-size:13px;font-weight:600;border:2px dashed #e0e0e0;border-radius:10px;background:#fff;cursor:pointer;color:#666;">+ Добавить канал</button>
        <div id="add-ch-log" style="display:none;background:#1a1a1a;color:#7eff7e;border-radius:8px;padding:10px;font-size:12px;font-family:monospace;margin-top:8px;"></div>
      </div>
      <div style="margin-bottom:8px;"><div style="font-size:12px;color:#aaa;margin-bottom:4px;">Название:</div><input type="text" id="yt-title-show" placeholder="Название видео..." style="width:100%;padding:9px 12px;border:1px solid #fca5a5;border-radius:8px;font-size:14px;" oninput="document.getElementById('vid-title').value=this.value"></div>
      <div style="margin-bottom:10px;"><div style="font-size:12px;color:#aaa;margin-bottom:4px;">Описание:</div><textarea id="yt-desc" placeholder="Описание..." style="width:100%;padding:9px 12px;border:1px solid #fca5a5;border-radius:8px;font-size:14px;height:70px;resize:none;font-family:inherit;"></textarea></div>
      <div style="margin-bottom:14px;">
        <div style="font-size:12px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">📁 Загрузить готовое видео</div>
        <input type="file" id="ready-files" accept="video/mp4" multiple style="display:none;" onchange="handleReadyFiles(this)">
        <button onclick="document.getElementById('ready-files').click()" style="width:100%;padding:9px;font-size:13px;font-weight:600;border:2px dashed #e0e0e0;border-radius:10px;background:#fff;cursor:pointer;color:#666;margin-bottom:6px;">📂 Выбрать mp4 файлы</button>
        <div id="ready-files-list" style="font-size:12px;color:#16a34a;"></div>
      </div>
      <div style="font-size:13px;color:#666;margin-top:8px;">Приватность:</div>
      <div class="privacy-row">
        <div class="privacy-btn" id="priv-public" onclick="setPrivacy('public')">Публичное</div>
        <div class="privacy-btn on" id="priv-unlisted" onclick="setPrivacy('unlisted')">По ссылке</div>
        <div class="privacy-btn" id="priv-private" onclick="setPrivacy('private')">Приватное</div>
      </div>
      <button class="btn btn-yt" id="yt-btn" onclick="startUpload()" style="margin-top:14px;">▶ Загрузить на YouTube</button>
      <div class="yt-log" id="yt-log" style="display:none;"></div>
      <div class="yt-links" id="yt-links"></div>

      <!-- Массовая загрузка из готовых файлов -->
      <div style="margin-top:18px;padding-top:16px;border-top:1px solid #fca5a5;">
        <div style="font-size:13px;font-weight:800;color:#7c3aed;margin-bottom:10px;">🚀 Массовая загрузка</div>
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
          <span style="font-size:13px;font-weight:700;color:#555;">Кол-во аккаунтов:</span>
          <input type="number" id="build-mass-n" value="5" min="1" max="50" style="width:70px;padding:7px 10px;border:1.5px solid #d1d5db;border-radius:8px;font-size:15px;font-weight:800;text-align:center;" oninput="updateBuildMassInfo()">
          <span style="font-size:12px;color:#888;" id="build-mass-info">= 15 загрузок</span>
        </div>
        <button class="btn" id="build-mass-btn" onclick="startBuildMassUpload()" style="background:linear-gradient(135deg,#4f46e5,#7c3aed);width:100%;padding:12px;font-size:14px;">🚀 Запустить массовую загрузку</button>
        <div id="build-mass-progress-wrap" style="display:none;margin-top:10px;">
          <div class="up-progress-bar"><div class="up-progress-fill" id="build-mass-progress-fill" style="width:0%"></div></div>
          <div style="font-size:12px;color:#888;text-align:center;" id="build-mass-progress-text">0 / 0</div>
        </div>
        <div id="build-mass-log" style="display:none;background:#0d0d1a;color:#7eff7e;border-radius:8px;padding:10px;font-size:11px;font-family:monospace;max-height:120px;overflow-y:auto;white-space:pre-wrap;margin-top:8px;"></div>
        <div id="build-mass-result" style="margin-top:10px;display:none;">
          <div style="font-size:12px;font-weight:800;color:#333;margin-bottom:6px;">📋 Результаты:</div>
          <table class="mass-result-table" id="build-mass-result-table">
            <thead><tr><th>#</th><th>Канал</th><th>9:16</th><th>1:1</th><th>16:9</th></tr></thead>
            <tbody id="build-mass-result-body"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</div>

  <div id="tab-ads" class="tab-pane">
    <div class="card">
      <div class="card-title">🎯 Категория</div>
      <div class="lang-grid" id="cat-grid">
        <button class="lang-btn" onclick="setCat(this)" data-cat="Суставы">🦴 Суставы</button>
        <button class="lang-btn" onclick="setCat(this)" data-cat="Диабет">🩸 Диабет</button>
        <button class="lang-btn" onclick="setCat(this)" data-cat="Гипертония">🫀 Гипертония</button>
        <button class="lang-btn" onclick="setCat(this)" data-cat="Похудение">⚖️ Похудение</button>
        <button class="lang-btn" onclick="setCat(this)" data-cat="Паразиты">🦠 Паразиты</button>
        <button class="lang-btn" onclick="setCat(this)" data-cat="Простатит">💊 Простатит</button>
        <button class="lang-btn" onclick="setCat(this)" data-cat="Потенция">💪 Потенция</button>
        <button class="lang-btn" onclick="setCat(this)" data-cat="Цистит">💧 Цистит</button>
        <button class="lang-btn" onclick="setCat(this)" data-cat="Зрение">👁️ Зрение</button>
        <button class="lang-btn" onclick="setCat(this)" data-cat="Память">🧠 Память</button>
      </div>
    </div>
    <div class="card">
      <div class="card-title">🌍 Язык</div>
      <div class="lang-grid" id="lang-grid">
        <button class="lang-btn" onclick="setLang(this)" data-lang="Serbian">🇷🇸 Сербский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Slovenian">🇸🇮 Словенский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Bulgarian">🇧🇬 Болгарский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Croatian">🇭🇷 Хорватский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Bosnian">🇧🇦 Боснийский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="English">🇬🇧 Английский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="German">🇩🇪 Немецкий</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Polish">🇵🇱 Польский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Czech">🇨🇿 Чешский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Slovak">🇸🇰 Словацкий</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Hungarian">🇭🇺 Венгерский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Romanian">🇷🇴 Румынский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Greek">🇬🇷 Греческий</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Portuguese">🇵🇹 Португальский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Spanish">🇪🇸 Испанский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Italian">🇮🇹 Итальянский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="French">🇫🇷 Французский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Dutch">🇳🇱 Нидерландский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Swedish">🇸🇪 Шведский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Norwegian">🇳🇴 Норвежский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Danish">🇩🇰 Датский</button>
        <button class="lang-btn" onclick="setLang(this)" data-lang="Finnish">🇫🇮 Финский</button>
      </div>
    </div>
    <button class="btn" id="ads-btn" onclick="generateAds()">✨ Сгенерировать 15 заголовков и описаний</button>
    <div id="ads-result" style="display:none;margin-top:16px;">
      <div class="card">
        <div class="card-title">📌 Заголовки (до 39 символов)</div>
        <table class="result-table" id="titles-table">
          <tr><th>#</th><th>Заголовок</th><th>Перевод</th><th>Симв.</th><th></th></tr>
        </table>
      </div>
      <div class="card">
        <div class="card-title">📝 Описания (до 85 символов)</div>
        <table class="result-table" id="descs-table">
          <tr><th>#</th><th>Описание</th><th>Перевод</th><th>Симв.</th><th></th></tr>
        </table>
      </div>
    </div>
  </div>

</div>

  <div id="tab-upload" class="tab-pane">
  <style>
    .up-wrap{max-width:560px;margin:0 auto;}
    .up-section{background:var(--surface);border:var(--card-border);border-radius:16px;padding:18px;margin-bottom:14px;box-shadow:var(--shadow);}
    .up-section-title{font-size:13px;font-weight:800;color:var(--text2);text-transform:uppercase;letter-spacing:.06em;margin-bottom:14px;display:flex;align-items:center;gap:8px;}
    .up-fmt-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:14px;}
    .up-fmt-drop{border:2px dashed var(--border2,#d1d5db);border-radius:12px;padding:16px 8px;text-align:center;cursor:pointer;transition:.2s;background:var(--surface2);}
    .up-fmt-drop:hover{border-color:var(--accent1);background:var(--bg2);}
    .up-fmt-drop.ok{border-color:#22c55e;border-style:solid;background:rgba(34,197,94,.06);}
    .up-fmt-drop input{display:none;}
    .up-fmt-label{font-size:11px;font-weight:800;color:var(--text3);margin-bottom:4px;text-transform:uppercase;}
    .up-fmt-ratio{font-size:18px;font-weight:900;color:var(--text2);margin-bottom:4px;line-height:1;}
    .up-fmt-sub{font-size:10px;color:var(--text3);}
    .up-fmt-drop.ok .up-fmt-ratio{color:#16a34a;}
    .up-n-row{display:flex;align-items:center;gap:10px;margin-bottom:14px;}
    .up-n-row label{font-size:13px;font-weight:700;color:var(--text2);white-space:nowrap;}
    .up-n-input{width:80px;padding:9px 12px;border:1.5px solid var(--border2,#d1d5db);border-radius:10px;font-size:16px;font-weight:800;text-align:center;background:var(--input-bg);color:var(--text);}
    .up-n-info{font-size:12px;color:var(--text3);}
    .up-field{margin-bottom:10px;}
    .up-field label{display:block;font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px;}
    .up-field input,.up-field textarea{width:100%;padding:9px 12px;border:1.5px solid var(--border2,#d1d5db);border-radius:10px;font-size:14px;background:var(--input-bg);color:var(--text);box-sizing:border-box;font-family:inherit;}
    .up-field textarea{height:60px;resize:none;}
    .mass-result-table tr:nth-child(even) td{background:var(--surface2);}
  </style>
  <div class="up-wrap">

    <!-- Загрузить на YouTube -->
    <div class="up-section">
      <div class="up-section-title">🚀 Загрузить на YouTube</div>

      <!-- Mode switcher -->
      <div style="display:flex;gap:8px;margin-bottom:18px;">
        <button id="mode-auto-btn" onclick="setUploadMode('auto')" style="flex:1;padding:10px;border-radius:10px;border:2px solid #4f46e5;background:#4f46e5;color:#fff;font-weight:700;font-size:13px;cursor:pointer;">⚡ Авто (конвертация)</button>
        <button id="mode-ready-btn" onclick="setUploadMode('ready')" style="flex:1;padding:10px;border-radius:10px;border:2px solid #d1d5db;background:var(--surface2);color:var(--text3);font-weight:700;font-size:13px;cursor:pointer;">📁 Готовые видео</button>
      </div>

      <!-- AUTO MODE -->
      <div id="auto-mode-section">
      <!-- Video file -->
      <div class="up-field">
        <label>Видео файл</label>
        <input type="file" id="auto-video-input" accept="video/mp4,video/quicktime,.mp4,.mov" style="display:none;" onchange="autoVideoSelected(this)">
        <button id="auto-video-btn" onclick="document.getElementById('auto-video-input').click()" style="width:100%;padding:12px;font-size:13px;font-weight:600;border:2px dashed var(--border2,#d1d5db);border-radius:10px;background:var(--surface2);cursor:pointer;color:var(--text3);">📂 Выбрать видео (.mp4)</button>
        <div id="auto-video-name" style="font-size:12px;color:#16a34a;margin-top:6px;"></div>
      </div>

      <!-- Category -->
      <div class="up-field">
        <label>Тематика <span style="font-size:11px;color:var(--text3);font-weight:400;">(AI сгенерирует уникальный заголовок для каждого аккаунта)</span></label>
        <div style="display:flex;flex-wrap:wrap;gap:6px;" id="auto-cat-grid">
          <button class="lang-btn" onclick="setAutoCat(this)" data-cat="Суставы">🦴 Суставы</button>
          <button class="lang-btn" onclick="setAutoCat(this)" data-cat="Диабет">🩸 Диабет</button>
          <button class="lang-btn" onclick="setAutoCat(this)" data-cat="Гипертония">🫀 Гипертония</button>
          <button class="lang-btn" onclick="setAutoCat(this)" data-cat="Похудение">⚖️ Похудение</button>
          <button class="lang-btn" onclick="setAutoCat(this)" data-cat="Паразиты">🦠 Паразиты</button>
          <button class="lang-btn" onclick="setAutoCat(this)" data-cat="Простатит">💊 Простатит</button>
          <button class="lang-btn" onclick="setAutoCat(this)" data-cat="Потенция">💪 Потенция</button>
          <button class="lang-btn" onclick="setAutoCat(this)" data-cat="Цистит">💧 Цистит</button>
          <button class="lang-btn" onclick="setAutoCat(this)" data-cat="Зрение">👁️ Зрение</button>
          <button class="lang-btn" onclick="setAutoCat(this)" data-cat="Память">🧠 Память</button>
        </div>
        <div id="auto-cat-selected" style="font-size:12px;color:#4f46e5;margin-top:6px;"></div>
      </div>

      <!-- N accounts -->
      <div class="up-n-row">
        <label>Кол-во аккаунтов:</label>
        <input type="number" class="up-n-input" id="auto-n" value="3" min="1" max="50" oninput="updateAutoInfo()">
        <span class="up-n-info" id="auto-n-info">= 9 видео (3 формата × 3)</span>
      </div>

      <!-- Privacy -->
      <div style="margin-bottom:16px;">
        <div style="font-size:11px;color:var(--text3);font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">Приватность</div>
        <div class="privacy-row" style="margin:0;">
          <div class="privacy-btn" id="auto-priv-public" onclick="setAutoPrivacy('public')">Публичное</div>
          <div class="privacy-btn on" id="auto-priv-unlisted" onclick="setAutoPrivacy('unlisted')">По ссылке</div>
          <div class="privacy-btn" id="auto-priv-private" onclick="setAutoPrivacy('private')">Приватное</div>
        </div>
      </div>

<!-- AI Title block for auto mode -->
      <div style="margin-bottom:14px;">
        <button id="auto-gen-btn" onclick="generateAutoMeta()" style="width:100%;padding:10px;border-radius:10px;border:2px solid #4f46e5;background:var(--surface2);color:#4f46e5;font-weight:700;font-size:13px;cursor:pointer;margin-bottom:10px;">✨ Сгенерировать нейтральный заголовок (AI)</button>
        <div id="auto-ai-result" style="display:none;background:rgba(79,70,229,.06);border:1.5px solid rgba(79,70,229,.2);border-radius:10px;padding:12px;margin-bottom:10px;">
          <div style="font-size:11px;font-weight:700;color:#4f46e5;margin-bottom:4px;">ЗАГОЛОВОК:</div>
          <div id="auto-ai-title" style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:8px;"></div>
          <div style="font-size:11px;font-weight:700;color:#4f46e5;margin-bottom:4px;">ОПИСАНИЕ:</div>
          <div id="auto-ai-desc" style="font-size:13px;color:var(--text2);"></div>
        </div>
      </div>

      <button class="btn" id="auto-run-btn" onclick="if(this.dataset.running)return;this.dataset.running=1;startAutoUpload().finally(()=>delete this.dataset.running)" style="background:linear-gradient(135deg,#4f46e5,#7c3aed);width:100%;font-size:15px;padding:13px;" disabled>🚀 Запустить загрузку</button>

      <div id="auto-progress-wrap" style="display:none;margin-top:12px;">
        <div class="up-progress-bar"><div class="up-progress-fill" id="auto-progress-fill" style="width:0%"></div></div>
        <div style="font-size:12px;color:var(--text3);text-align:center;margin-top:4px;" id="auto-progress-text">0 / 0</div>
      </div>
      <div id="auto-log" style="display:none;background:#0d0d1a;color:#7eff7e;border-radius:10px;padding:10px;font-size:11px;font-family:monospace;max-height:160px;overflow-y:auto;white-space:pre-wrap;margin-top:10px;"></div>
      <div id="auto-result" style="margin-top:12px;display:none;">
        <div style="font-size:13px;font-weight:800;color:var(--text);margin-bottom:8px;">📋 Результаты:</div>
        <table class="mass-result-table" id="auto-result-table">
          <thead><tr><th>#</th><th>Канал</th><th>9:16</th><th>1:1</th><th>16:9</th></tr></thead>
          <tbody id="auto-result-body"></tbody>
        </table>
      </div>
      </div><!-- end auto-mode-section -->

      <!-- READY MODE -->
      <div id="ready-mode-section" style="display:none;">
        <div style="font-size:12px;color:var(--text3);margin-bottom:14px;">Загрузи готовые видео в нужных форматах. Можно загрузить только один формат или все три.</div>

        <!-- Drag & drop zone for all 3 at once -->
        <div id="ready-dropzone" ondragover="event.preventDefault();this.style.borderColor='#4f46e5'" ondragleave="this.style.borderColor='#d1d5db'" ondrop="readyDropAll(event)" style="border:2px dashed #d1d5db;border-radius:12px;padding:18px;text-align:center;margin-bottom:14px;cursor:pointer;background:var(--surface2);transition:border-color .2s;" onclick="document.getElementById('ready-all-input').click()">
          <input type="file" id="ready-all-input" accept="video/*" multiple style="display:none;" onchange="readyAllSelected(this)">
          <div style="font-size:22px;margin-bottom:4px;">📂</div>
          <div style="font-size:13px;font-weight:700;color:var(--text2);">Перетащи сюда все 3 видео сразу</div>
          <div style="font-size:11px;color:var(--text3);margin-top:2px;">или кликни чтобы выбрать — панель сама определит формат по разрешению</div>
        </div>

        <div style="display:flex;flex-direction:column;gap:10px;margin-bottom:14px;">
          <div style="display:flex;align-items:center;gap:10px;">
            <span style="width:60px;font-size:12px;font-weight:700;color:#4f46e5;">9:16</span>
            <input type="file" id="ready-916-input" accept="video/*" style="display:none;" onchange="readyFileSelected(this,'9:16')">
            <button onclick="document.getElementById('ready-916-input').click()" id="ready-916-btn" style="flex:1;padding:9px;border:2px dashed var(--border2,#d1d5db);border-radius:8px;background:var(--surface2);cursor:pointer;font-size:12px;color:var(--text3);">📂 Выбрать видео 9:16 (Shorts)</button>
            <span id="ready-916-name" style="font-size:11px;color:#16a34a;display:none;"></span>
          </div>
          <div style="display:flex;align-items:center;gap:10px;">
            <span style="width:60px;font-size:12px;font-weight:700;color:#4f46e5;">1:1</span>
            <input type="file" id="ready-11-input" accept="video/*" style="display:none;" onchange="readyFileSelected(this,'1:1')">
            <button onclick="document.getElementById('ready-11-input').click()" id="ready-11-btn" style="flex:1;padding:9px;border:2px dashed var(--border2,#d1d5db);border-radius:8px;background:var(--surface2);cursor:pointer;font-size:12px;color:var(--text3);">📂 Выбрать видео 1:1 (Feed)</button>
            <span id="ready-11-name" style="font-size:11px;color:#16a34a;display:none;"></span>
          </div>
          <div style="display:flex;align-items:center;gap:10px;">
            <span style="width:60px;font-size:12px;font-weight:700;color:#4f46e5;">16:9</span>
            <input type="file" id="ready-169-input" accept="video/*" style="display:none;" onchange="readyFileSelected(this,'16:9')">
            <button onclick="document.getElementById('ready-169-input').click()" id="ready-169-btn" style="flex:1;padding:9px;border:2px dashed var(--border2,#d1d5db);border-radius:8px;background:var(--surface2);cursor:pointer;font-size:12px;color:var(--text3);">📂 Выбрать видео 16:9 (YouTube)</button>
            <span id="ready-169-name" style="font-size:11px;color:#16a34a;display:none;"></span>
          </div>
        </div>

        <div class="up-field">
          <label>Тематика <span style="font-size:11px;color:var(--text3);font-weight:400;">(AI сгенерирует заголовок)</span></label>
          <div style="display:flex;flex-wrap:wrap;gap:6px;" id="ready-cat-grid">
            <button class="lang-btn" onclick="setReadyCat(this)" data-cat="Суставы">🦴 Суставы</button>
            <button class="lang-btn" onclick="setReadyCat(this)" data-cat="Диабет">🩸 Диабет</button>
            <button class="lang-btn" onclick="setReadyCat(this)" data-cat="Гипертония">🫀 Гипертония</button>
            <button class="lang-btn" onclick="setReadyCat(this)" data-cat="Похудение">⚖️ Похудение</button>
            <button class="lang-btn" onclick="setReadyCat(this)" data-cat="Паразиты">🦠 Паразиты</button>
            <button class="lang-btn" onclick="setReadyCat(this)" data-cat="Простатит">💊 Простатит</button>
            <button class="lang-btn" onclick="setReadyCat(this)" data-cat="Потенция">💪 Потенция</button>
            <button class="lang-btn" onclick="setReadyCat(this)" data-cat="Цистит">💧 Цистит</button>
            <button class="lang-btn" onclick="setReadyCat(this)" data-cat="Зрение">👁️ Зрение</button>
            <button class="lang-btn" onclick="setReadyCat(this)" data-cat="Память">🧠 Память</button>
          </div>
        </div>

        <div class="up-n-row" style="margin-bottom:12px;">
          <label>Кол-во аккаунтов:</label>
          <input type="number" class="up-n-input" id="ready-n" value="1" min="1" max="50" oninput="updateReadyInfo()">
          <span class="up-n-info" id="ready-n-info"></span>
        </div>

        <div style="margin-bottom:16px;">
          <div style="font-size:11px;color:var(--text3);font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">Приватность</div>
          <div class="privacy-row" style="margin:0;">
            <div class="privacy-btn" id="ready-priv-public" onclick="setReadyPrivacy('public')">Публичное</div>
            <div class="privacy-btn on" id="ready-priv-unlisted" onclick="setReadyPrivacy('unlisted')">По ссылке</div>
            <div class="privacy-btn" id="ready-priv-private" onclick="setReadyPrivacy('private')">Приватное</div>
          </div>
        </div>

        <!-- AI Title/Desc block -->
      <div style="margin-bottom:14px;">
        <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">Заголовок и описание</div>
        <button id="upload-gen-btn" onclick="generateUploadMeta()" style="width:100%;padding:10px;border-radius:10px;border:2px solid #4f46e5;background:var(--surface2);color:#4f46e5;font-weight:700;font-size:13px;cursor:pointer;margin-bottom:10px;">✨ Сгенерировать нейтральный заголовок (AI)</button>
        <div id="upload-ai-result" style="display:none;background:rgba(79,70,229,.06);border:1.5px solid rgba(79,70,229,.2);border-radius:10px;padding:12px;margin-bottom:10px;">
          <div style="font-size:11px;font-weight:700;color:#4f46e5;margin-bottom:4px;">ЗАГОЛОВОК:</div>
          <div id="upload-ai-title" style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:8px;"></div>
          <div style="font-size:11px;font-weight:700;color:#4f46e5;margin-bottom:4px;">ОПИСАНИЕ:</div>
          <div id="upload-ai-desc" style="font-size:13px;color:var(--text2);margin-bottom:10px;"></div>
          <button onclick="applyUploadMeta()" style="padding:7px 16px;background:#16a34a;color:#fff;border:none;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;">✅ Применить</button>
        </div>
        <div class="up-field">
          <label>Название</label>
          <input type="text" id="upload-title" placeholder="Название видео..." style="width:100%;padding:9px 12px;border:1.5px solid var(--border2,#d1d5db);border-radius:10px;font-size:14px;background:var(--input-bg);color:var(--text);box-sizing:border-box;">
        </div>
        <div class="up-field">
          <label>Описание</label>
          <textarea id="upload-desc" placeholder="Описание видео..." style="width:100%;padding:9px 12px;border:1.5px solid var(--border2,#d1d5db);border-radius:10px;font-size:13px;background:var(--input-bg);color:var(--text);box-sizing:border-box;height:70px;resize:none;font-family:inherit;"></textarea>
        </div>
      </div>

      <button class="btn" id="ready-run-btn" onclick="startReadyUpload()" style="background:linear-gradient(135deg,#16a34a,#15803d);width:100%;font-size:15px;padding:13px;" disabled>🚀 Загрузить на YouTube</button>

        <div id="ready-progress-wrap" style="display:none;margin-top:12px;">
          <div class="up-progress-bar"><div class="up-progress-fill" id="ready-progress-fill" style="width:0%"></div></div>
          <div style="font-size:12px;color:var(--text3);text-align:center;margin-top:4px;" id="ready-progress-text">0 / 0</div>
        </div>
        <div id="ready-log" style="display:none;background:#0d0d1a;color:#7eff7e;border-radius:10px;padding:10px;font-size:11px;font-family:monospace;max-height:160px;overflow-y:auto;white-space:pre-wrap;margin-top:10px;"></div>
        <div id="ready-result" style="margin-top:12px;display:none;">
          <div style="font-size:13px;font-weight:800;color:var(--text);margin-bottom:8px;">📋 Результаты:</div>
          <table class="mass-result-table" id="ready-result-table">
            <thead><tr><th>#</th><th>Канал</th><th>Формат</th><th>Ссылка</th></tr></thead>
            <tbody id="ready-result-body"></tbody>
          </table>
        </div>
      </div><!-- end ready-mode-section -->
    </div>

    <!-- Проекты и каналы -->
    <div class="up-section">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
        <div class="up-section-title" style="margin:0;">🔑 Проекты API</div>
        <label style="padding:6px 14px;font-size:12px;font-weight:700;background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#fff;border-radius:8px;cursor:pointer;white-space:nowrap;">
          + Добавить проект
          <input type="file" accept=".json" style="display:none;" onchange="addProject(this)">
        </label>
      </div>
      <div id="projects-list" style="display:flex;flex-direction:column;gap:8px;"></div>
      <div style="font-size:11px;color:var(--text3);margin-top:8px;">Каждый проект даёт 100 загрузок/день.</div>
    </div>

    <div class="up-section">
      <div class="up-section-title">📺 Мои каналы</div>
      <div id="channels-list-top" style="display:flex;flex-direction:column;gap:8px;"></div>
    </div>

  </div>
  </div>

</div>

  <div id="tab-prokla" class="tab-pane">
    <style>
      /* ── Prokla step cards ── */
      .pk-header{display:flex;align-items:center;gap:12px;margin-bottom:20px;}
      .pk-header-icon{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#f59e0b,#ef4444);display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;}
      .pk-header-text h2{font-size:20px;font-weight:800;background:linear-gradient(135deg,#f59e0b,#ef4444);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:2px;}
      .pk-header-text p{font-size:12px;color:var(--text3);}

      .pk-step{background:var(--surface);border:var(--card-border);border-radius:16px;padding:0;margin-bottom:12px;box-shadow:var(--shadow);overflow:hidden;transition:box-shadow .2s;}
      .pk-step:hover{box-shadow:var(--shadow2);}
      .pk-step-head{display:flex;align-items:center;gap:12px;padding:14px 18px;border-bottom:var(--card-border);}
      .pk-step-num{width:28px;height:28px;border-radius:50%;background:var(--grad1);color:#fff;font-size:12px;font-weight:800;display:flex;align-items:center;justify-content:center;flex-shrink:0;}
      .pk-step-num.orange{background:var(--grad4);}
      .pk-step-num.green{background:var(--grad3);}
      .pk-step-num.blue{background:var(--grad5);}
      .pk-step-num.pink{background:var(--grad2);}
      .pk-step-title{font-size:14px;font-weight:700;color:var(--text);}
      .pk-step-hint{font-size:11px;color:var(--text3);margin-left:auto;}
      .pk-step-body{padding:16px 18px;}

      .pk-drop{border:2px dashed var(--border2);border-radius:12px;padding:28px 20px;text-align:center;cursor:pointer;transition:.2s;background:var(--surface2);}
      .pk-drop:hover{border-color:var(--accent1);background:var(--bg2);}
      .pk-drop.ok{border-color:#22c55e;border-style:solid;background:rgba(67,233,123,.06);}
      .pk-drop-icon{font-size:36px;margin-bottom:8px;line-height:1;}
      .pk-drop-label{font-size:14px;font-weight:700;color:var(--text2);margin-bottom:3px;}
      .pk-drop-sub{font-size:12px;color:var(--text3);}
      .pk-drop.ok .pk-drop-label{color:#16a34a;}

      .pk-grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
      .pk-field{}
      .pk-field label{display:block;font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;}
      .pk-field input,.pk-field select{width:100%;padding:10px 13px;background:var(--input-bg);border:1.5px solid var(--input-border);border-radius:10px;color:var(--text);font-size:14px;outline:none;box-sizing:border-box;transition:.2s;font-family:inherit;}
      .pk-field input::placeholder{color:var(--text3);}
      .pk-field input:focus,.pk-field select:focus{border-color:var(--accent1);box-shadow:0 0 0 3px rgba(108,99,255,.12);}

      .pk-arrow{display:flex;align-items:center;gap:6px;}
      .pk-arrow-icon{font-size:18px;color:var(--text3);}

      .pk-price-result{background:linear-gradient(135deg,rgba(245,158,11,.1),rgba(239,68,68,.1));border:1.5px solid rgba(245,158,11,.3);border-radius:10px;padding:12px 16px;text-align:center;}
      .pk-price-result-label{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#d97706;margin-bottom:4px;}
      .pk-price-result-val{font-size:22px;font-weight:800;color:#d97706;}
      [data-theme="dark"] .pk-price-result-val{color:#fcd34d;}

      .pk-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;}
      .pk-chip{padding:5px 12px;background:var(--surface2);border:1.5px solid var(--border);border-radius:20px;font-size:12px;font-weight:600;cursor:pointer;color:var(--text2);transition:.15s;}
      .pk-chip:hover{border-color:var(--accent1);color:var(--accent1);}

      .pk-img-row{display:grid;grid-template-columns:1fr 120px;gap:12px;align-items:start;}
      .pk-img-preview{width:120px;height:120px;border-radius:12px;border:2px dashed var(--border2);background:var(--surface2);display:flex;align-items:center;justify-content:center;overflow:hidden;flex-shrink:0;}
      .pk-img-preview img{width:100%;height:100%;object-fit:cover;border-radius:10px;}
      .pk-img-preview-empty{font-size:32px;color:var(--text3);}

      .pk-phone-row{display:flex;gap:8px;align-items:flex-end;}
      .pk-phone-hint{font-size:10px;color:var(--text3);line-height:1.4;white-space:nowrap;}

      .pk-btn{width:100%;padding:16px;font-size:16px;font-weight:800;border:none;border-radius:14px;background:linear-gradient(135deg,#f59e0b,#ef4444);color:#fff;cursor:pointer;letter-spacing:.02em;transition:.2s;box-shadow:0 4px 16px rgba(239,68,68,.3);}
      .pk-btn:hover:not(:disabled){transform:translateY(-2px);box-shadow:0 8px 24px rgba(239,68,68,.4);}
      .pk-btn:active:not(:disabled){transform:translateY(0);}
      .pk-btn:disabled{opacity:.35;cursor:not-allowed;box-shadow:none;}
      .pk-log{background:#0d0d1a;color:#7eff7e;border-radius:12px;padding:14px;font-size:12px;font-family:monospace;margin-top:12px;white-space:pre-wrap;line-height:1.6;display:none;border:1px solid #2a2a4a;}

      .pk-divider{height:1px;background:var(--border);margin:14px 0;}
    </style>

    <!-- Header -->
    <div class="pk-header">
      <div class="pk-header-icon">🔧</div>
      <div class="pk-header-text">
        <h2>Редактор прокл</h2>
        <p>Загрузи ZIP → заполни поля → скачай готовую проклу</p>
      </div>
    </div>

    <!-- Step 1: ZIP -->
    <div class="pk-step">
      <div class="pk-step-head">
        <div class="pk-step-num">1</div>
        <div class="pk-step-title">ZIP файл прокла</div>
        <div class="pk-step-hint">обязательно</div>
      </div>
      <div class="pk-step-body">
        <div class="pk-drop" id="prokla-drop" onclick="document.getElementById('prokla-zip').click()">
          <div class="pk-drop-icon">🗜️</div>
          <div class="pk-drop-label" id="prokla-zip-lbl">Нажми или перетащи ZIP-архив</div>
          <div class="pk-drop-sub">Архив с index.html внутри</div>
        </div>
        <input type="file" id="prokla-zip" accept=".zip" style="display:none;" onchange="handleProklaZip(this)">
      </div>
    </div>

    <!-- Step 2: Name -->
    <div class="pk-step">
      <div class="pk-step-head">
        <div class="pk-step-num orange">2</div>
        <div class="pk-step-title">Название офера</div>
        <div class="pk-step-hint">обязательно</div>
      </div>
      <div class="pk-step-body">
        <div class="pk-grid2">
          <div class="pk-field">
            <label>Старое название (в прокле)</label>
            <input type="text" id="prokla-old-name" placeholder="Detox Now">
          </div>
          <div class="pk-field">
            <label>Новое название</label>
            <input type="text" id="prokla-new-name" placeholder="DiabetOver" oninput="checkProklaReady();calcOldPrice()">
          </div>
        </div>
        <div class="pk-chips" id="prokla-names-history"></div>
      </div>
    </div>

    <!-- Step 3: Price -->
    <div class="pk-step">
      <div class="pk-step-head">
        <div class="pk-step-num green">3</div>
        <div class="pk-step-title">Цены</div>
        <div class="pk-step-hint">необязательно</div>
      </div>
      <div class="pk-step-body">
        <div class="pk-grid2" style="margin-bottom:12px;">
          <div class="pk-field">
            <label>Новая цена</label>
            <input type="number" id="prokla-new-price" placeholder="1490" oninput="calcOldPrice()">
          </div>
          <div class="pk-field">
            <label>Скидка %</label>
            <input type="number" id="prokla-discount" placeholder="50" value="50" oninput="calcOldPrice()">
          </div>
        </div>
        <div class="pk-grid2">
          <div class="pk-field">
            <label>Валюта</label>
            <select id="prokla-currency" onchange="calcOldPrice()">
              <option value="RSD">RSD 🇷🇸 Сербия</option>
              <option value="HRK">HRK 🇭🇷 Хорватия</option>
              <option value="BAM">BAM 🇧🇦 Босния</option>
              <option value="BGN">BGN 🇧🇬 Болгария</option>
              <option value="PLN">PLN 🇵🇱 Польша</option>
              <option value="EUR">EUR 🇪🇺 Евро</option>
              <option value="CZK">CZK 🇨🇿 Чехия</option>
              <option value="HUF">HUF 🇭🇺 Венгрия</option>
              <option value="RON">RON 🇷🇴 Румыния</option>
              <option value="GEL">GEL 🇬🇪 Грузия</option>
              <option value="UAH">UAH 🇺🇦 Украина</option>
              <option value="NOK">NOK 🇳🇴 Норвегия</option>
              <option value="SEK">SEK 🇸🇪 Швеция</option>
              <option value="DKK">DKK 🇩🇰 Дания</option>
              <option value="GBP">GBP 🇬🇧 Англия</option>
            </select>
          </div>
          <div>
            <div class="pk-price-result">
              <div class="pk-price-result-label">Старая цена (авто)</div>
              <div class="pk-price-result-val" id="prokla-old-price-show">—</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Step 4: Phone -->
    <div class="pk-step">
      <div class="pk-step-head">
        <div class="pk-step-num blue">4</div>
        <div class="pk-step-title">Маска телефона</div>
        <div class="pk-step-hint">необязательно</div>
      </div>
      <div class="pk-step-body">
        <div class="pk-field" style="margin-bottom:10px;">
          <label>Страна</label>
          <select id="prokla-phone-country" onchange="selectPhoneMask(this)">
            <option value="">— Не менять маску —</option>
            <option value="(+381)099999999">🇷🇸 Сербия (+381)099999999</option>
            <option value="(+385)099999999">🇭🇷 Хорватия (+385)099999999</option>
            <option value="(+387)099999999">🇧🇦 Босния (+387)099999999</option>
            <option value="(+359)0999999999">🇧🇬 Болгария (+359)0999999999</option>
            <option value="(+48)999999999">🇵🇱 Польша (+48)999999999</option>
            <option value="(+49)99999999999">🇩🇪 Германия (+49)99999999999</option>
            <option value="(+43)9999999999">🇦🇹 Австрия (+43)9999999999</option>
            <option value="(+386)099999999">🇸🇮 Словения (+386)099999999</option>
            <option value="(+420)999999999">🇨🇿 Чехия (+420)999999999</option>
            <option value="(+421)999999999">🇸🇰 Словакия (+421)999999999</option>
            <option value="(+36)99999999">🇭🇺 Венгрия (+36)99999999</option>
            <option value="(+40)999999999">🇷🇴 Румыния (+40)999999999</option>
            <option value="(+30)9999999999">🇬🇷 Греция (+30)9999999999</option>
            <option value="(+351)999999999">🇵🇹 Португалия (+351)999999999</option>
            <option value="(+34)999999999">🇪🇸 Испания (+34)999999999</option>
            <option value="(+39)9999999999">🇮🇹 Италия (+39)9999999999</option>
            <option value="(+33)999999999">🇫🇷 Франция (+33)999999999</option>
            <option value="(+31)999999999">🇳🇱 Нидерланды (+31)999999999</option>
            <option value="(+46)99999999">🇸🇪 Швеция (+46)99999999</option>
            <option value="(+47)99999999">🇳🇴 Норвегия (+47)99999999</option>
            <option value="(+45)99999999">🇩🇰 Дания (+45)99999999</option>
            <option value="(+358)999999999">🇫🇮 Финляндия (+358)999999999</option>
            <option value="(+44)9999999999">🇬🇧 Англия (+44)9999999999</option>
            <option value="(+995)999999999">🇬🇪 Грузия (+995)999999999</option>
            <option value="(+380)99999999999">🇺🇦 Украина (+380)99999999999</option>
          </select>
        </div>
        <div class="pk-field">
          <label>Или введи вручную</label>
          <div class="pk-phone-row">
            <input type="text" id="prokla-phone-mask" placeholder="(+34)A99999999" style="flex:1;margin-top:0;">
            <div class="pk-phone-hint">9 = цифра<br>A = буква</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Step 5: Photo -->
    <div class="pk-step">
      <div class="pk-step-head">
        <div class="pk-step-num pink">5</div>
        <div class="pk-step-title">Фото нового офера</div>
        <div class="pk-step-hint">необязательно</div>
      </div>
      <div class="pk-step-body">
        <div class="pk-img-row">
          <div class="pk-drop" id="prokla-img-drop" onclick="document.getElementById('prokla-img').click()" style="padding:20px;">
            <div class="pk-drop-icon" id="prokla-img-icon">📷</div>
            <div class="pk-drop-label" id="prokla-img-lbl">Нажми для выбора фото</div>
            <div class="pk-drop-sub">JPG · PNG · WEBP</div>
          </div>
          <div class="pk-img-preview" id="prokla-img-preview">
            <div class="pk-img-preview-empty">🖼️</div>
          </div>
        </div>
        <input type="file" id="prokla-img" accept="image/*" style="display:none;" onchange="handleProklaImg(this)">

        <!-- Review photos options -->
        <div style="margin-top:14px;border-top:1px solid var(--border);padding-top:14px;">
          <div style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.07em;color:var(--text3);margin-bottom:10px;">📸 Фото в отзывах</div>
          <div style="display:flex;flex-direction:column;gap:8px;">
            <label style="display:flex;align-items:center;gap:10px;cursor:pointer;padding:10px 14px;border:1.5px solid var(--border);border-radius:10px;transition:.2s;" id="review-opt-replace-wrap">
              <input type="radio" name="review-photo-action" id="review-opt-replace" value="replace" onchange="updateReviewOpt()" style="accent-color:var(--accent1);width:16px;height:16px;cursor:pointer;">
              <div>
                <div style="font-size:13px;font-weight:700;color:var(--text);">🔄 Заменить фото в отзывах на новый офер</div>
                <div style="font-size:11px;color:var(--text3);margin-top:2px;">Все фото внутри блоков отзывов заменятся на загруженное фото</div>
              </div>
            </label>
            <label style="display:flex;align-items:center;gap:10px;cursor:pointer;padding:10px 14px;border:1.5px solid var(--border);border-radius:10px;transition:.2s;" id="review-opt-delete-wrap">
              <input type="radio" name="review-photo-action" id="review-opt-delete" value="delete" onchange="updateReviewOpt()" style="accent-color:var(--accent2);width:16px;height:16px;cursor:pointer;">
              <div>
                <div style="font-size:13px;font-weight:700;color:var(--text);">🗑️ Удалить фото из отзывов</div>
                <div style="font-size:11px;color:var(--text3);margin-top:2px;">Убирает все изображения внутри блоков комментариев и отзывов</div>
              </div>
            </label>
            <label style="display:flex;align-items:center;gap:10px;cursor:pointer;padding:10px 14px;border:1.5px solid var(--border);border-radius:10px;transition:.2s;" id="review-opt-none-wrap">
              <input type="radio" name="review-photo-action" id="review-opt-none" value="none" onchange="updateReviewOpt()" checked style="accent-color:var(--text3);width:16px;height:16px;cursor:pointer;">
              <div>
                <div style="font-size:13px;font-weight:700;color:var(--text);">⏭️ Не трогать фото в отзывах</div>
                <div style="font-size:11px;color:var(--text3);margin-top:2px;">Оставить как есть</div>
              </div>
            </label>
          </div>
        </div>
      </div>
    </div>

    <!-- Analysis result panel -->
    <div id="prokla-analysis" style="display:none;background:var(--surface2);border:1.5px solid var(--accent3);border-radius:12px;padding:16px;margin-bottom:12px;">
      <div style="font-size:12px;font-weight:800;color:var(--accent3);text-transform:uppercase;letter-spacing:.07em;margin-bottom:12px;">🔍 Найдено в прокле</div>
      <div style="display:flex;flex-wrap:wrap;gap:10px;" id="prokla-found-items"></div>
    </div>

    <!-- Go button -->
    <button class="pk-btn" id="prokla-btn" onclick="processProkla()" disabled>🚀 Применить и скачать ZIP</button>
    <div class="pk-log" id="prokla-log"></div>

    <!-- Preview section -->
    <div id="prokla-preview-section" style="display:none;margin-top:20px;">
      <style>
        .pk-preview-wrap{background:var(--surface);border:var(--card-border);border-radius:16px;padding:20px;box-shadow:var(--shadow);}
        .pk-preview-title{font-size:13px;font-weight:800;color:var(--text2);text-transform:uppercase;letter-spacing:.07em;margin-bottom:16px;display:flex;align-items:center;gap:8px;}
        .pk-preview-phones{display:flex;gap:20px;justify-content:center;flex-wrap:wrap;}
        .pk-phone-wrap{display:flex;flex-direction:column;align-items:center;gap:8px;}
        .pk-phone-label{font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.06em;}
        .pk-phone{width:220px;height:420px;border-radius:28px;border:6px solid var(--text);background:#000;overflow:hidden;position:relative;box-shadow:0 12px 40px rgba(0,0,0,.3);flex-shrink:0;}
        .pk-phone::before{content:'';position:absolute;top:10px;left:50%;transform:translateX(-50%);width:60px;height:5px;background:var(--text);border-radius:3px;z-index:10;}
        .pk-phone iframe{width:100%;height:100%;border:none;background:#fff;}
        .pk-phone-btn-row{display:flex;gap:8px;margin-top:4px;}
        .pk-phone-btn{padding:5px 12px;font-size:11px;font-weight:700;border:1.5px solid var(--border);border-radius:8px;background:var(--surface2);cursor:pointer;color:var(--text2);transition:.15s;}
        .pk-phone-btn:hover{border-color:var(--accent1);color:var(--accent1);}
        .pk-phone-btn.reload{border-color:var(--accent3);}
      </style>
      <div class="pk-preview-wrap">
        <div class="pk-preview-title">👁️ Превью прокла <span id="pk-vsl-badge" style="display:none;background:linear-gradient(135deg,#f59e0b,#ef4444);color:#fff;font-size:10px;padding:2px 8px;border-radius:10px;text-transform:uppercase;">VSL</span></div>
        <div class="pk-preview-phones" id="pk-preview-phones"></div>
      </div>
    </div>

  </div>

  <!-- TASKS TAB -->
  <div id="tab-tasks" class="tab-pane">
  <style>
    .tk-wrap{max-width:700px;margin:0 auto;padding:20px 0;}
    .tk-step{background:var(--surface);border:var(--card-border);border-radius:16px;padding:24px;margin-bottom:16px;box-shadow:var(--shadow);display:none;}
    .tk-step.active{display:block;}
    .tk-step-num{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;background:var(--grad1);color:#fff;font-size:12px;font-weight:800;margin-right:10px;flex-shrink:0;}
    .tk-step-title{font-size:15px;font-weight:800;color:var(--text);display:flex;align-items:center;margin-bottom:18px;}
    .tk-label{font-size:12px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px;}
    .tk-input{width:100%;background:var(--surface2);border:1.5px solid var(--border);border-radius:10px;padding:10px 14px;font-size:14px;color:var(--text);outline:none;box-sizing:border-box;transition:.2s;}
    .tk-input:focus{border-color:var(--accent1);}
    .tk-row{display:flex;gap:12px;margin-bottom:14px;}
    .tk-col{flex:1;}
    .tk-mb{margin-bottom:14px;}
    .tk-check-row{display:flex;align-items:flex-start;gap:10px;padding:12px 14px;border:1.5px solid var(--border);border-radius:10px;margin-bottom:8px;cursor:pointer;transition:.15s;}
    .tk-check-row:hover{border-color:var(--accent1);}
    .tk-check-row input[type=checkbox]{width:16px;height:16px;margin-top:2px;accent-color:var(--accent1);flex-shrink:0;cursor:pointer;}
    .tk-check-label{font-size:13px;font-weight:600;color:var(--text);}
    .tk-check-sub{font-size:11px;color:var(--text3);margin-top:2px;}
    .tk-sub-field{margin-top:10px;padding:12px;background:var(--surface2);border-radius:10px;display:none;}
    .tk-sub-field.show{display:block;}
    .tk-nav{display:flex;gap:10px;margin-top:20px;}
    .tk-btn{padding:11px 24px;border:none;border-radius:10px;font-size:13px;font-weight:800;cursor:pointer;transition:.2s;}
    .tk-btn-next{background:var(--grad1);color:#fff;flex:1;}
    .tk-btn-back{background:var(--surface2);color:var(--text2);border:1.5px solid var(--border);}
    .tk-btn:hover{opacity:.88;}
    .tk-progress{display:flex;gap:6px;margin-bottom:20px;}
    .tk-progress-dot{height:4px;flex:1;border-radius:2px;background:var(--border);transition:.3s;}
    .tk-progress-dot.done{background:var(--accent1);}
    .tk-progress-dot.active{background:var(--grad1);}
    .tk-result{background:var(--surface);border:1.5px solid var(--accent3);border-radius:16px;padding:24px;box-shadow:var(--shadow);}
    .tk-result-text{font-family:monospace;font-size:13px;line-height:1.7;color:var(--text);white-space:pre-wrap;background:var(--surface2);border-radius:10px;padding:16px;max-height:500px;overflow-y:auto;}
    .tk-highlight{background:#facc15;color:#000;border-radius:3px;padding:0 3px;font-weight:700;}
    .tk-copy-btn{margin-top:12px;width:100%;padding:12px;background:var(--grad1);color:#fff;border:none;border-radius:10px;font-size:14px;font-weight:800;cursor:pointer;transition:.2s;}
    .tk-copy-btn:hover{opacity:.88;}
    /* ── Saved tasks redesign ── */
    .tk-saved-group{margin-bottom:20px;border-radius:16px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.07);}
    .tk-saved-group-hdr{
      font-size:15px;font-weight:800;color:#fff;
      padding:13px 16px;
      background:linear-gradient(135deg,#4f46e5,#7c3aed);
      display:flex;align-items:center;gap:10px;
      justify-content:space-between;
    }
    .tk-saved-group-hdr .tk-ghdr-left{display:flex;align-items:center;gap:8px;font-size:16px;}
    .tk-saved-group-hdr .tk-ghdr-geo{font-size:12px;font-weight:500;opacity:.75;margin-left:4px;}
    .tk-saved-group-hdr .tk-ghdr-right{display:flex;gap:6px;flex-shrink:0;}

    .tk-saved-card{
      background:var(--surface);
      border-left:4px solid #6366f1;
      border-right:1px solid var(--border);
      border-bottom:1px solid var(--border);
      padding:14px 16px;
    }
    .tk-saved-card:last-child{border-radius:0 0 14px 14px;}
    .tk-saved-card:nth-child(even){background:var(--surface2);}
    .tk-saved-card-inner{display:flex;gap:14px;align-items:flex-start;}

    .tk-saved-thumb{width:64px;height:64px;border-radius:10px;object-fit:cover;border:2px solid var(--border);flex-shrink:0;background:var(--surface2);}
    .tk-saved-thumb-ph{width:64px;height:64px;border-radius:10px;border:2px dashed var(--border);flex-shrink:0;display:flex;align-items:center;justify-content:center;color:var(--text3);font-size:26px;background:var(--surface2);}

    .tk-saved-title{font-size:15px;font-weight:800;color:var(--text);margin-bottom:4px;line-height:1.3;}
    .tk-saved-num{display:inline-block;background:#eef2ff;color:#4f46e5;border-radius:6px;padding:1px 8px;font-size:12px;font-weight:800;margin-right:6px;}
    [data-theme="dark"] .tk-saved-num{background:#1e1b4b;color:#a5b4fc;}
    .tk-saved-meta{font-size:12px;color:var(--text3);margin-bottom:10px;display:flex;align-items:center;gap:8px;}
    .tk-saved-meta-flag{font-size:16px;}

    .tk-saved-btns{display:flex;gap:7px;flex-wrap:wrap;align-items:center;}
    .tk-saved-btn-del{margin-left:auto!important;}

    .tk-scat{padding:5px 12px;font-size:12px;font-weight:700;border:1.5px solid #4c1d95;border-radius:20px;background:#1e0b3a;color:#a78bfa;cursor:pointer;transition:.15s;}
    .tk-scat:hover,.tk-scat.on{background:#5b21b6;border-color:#a78bfa;color:#e9d5ff;}

    .tk-saved-btn{
      padding:7px 14px;font-size:12px;font-weight:700;
      border:1.5px solid var(--border);border-radius:8px;
      background:var(--surface);cursor:pointer;color:var(--text2);
      transition:.15s;white-space:nowrap;
    }
    .tk-saved-btn:hover{border-color:var(--accent1);color:var(--accent1);background:var(--surface2);}
    .tk-saved-btn.green{border-color:#22c55e;color:#16a34a;background:#f0fdf4;}
    .tk-saved-btn.green:hover{background:#dcfce7;}
    [data-theme="dark"] .tk-saved-btn.green{background:#052e16;color:#4ade80;}

    /* Group header action buttons */
    .tk-ghdr-btn{
      padding:5px 13px;font-size:12px;font-weight:700;
      border-radius:8px;cursor:pointer;border:none;
      transition:.15s;white-space:nowrap;
    }
    .tk-ghdr-btn.split{background:#22c55e;color:#fff;}
    .tk-ghdr-btn.split:hover{background:#16a34a;}
    .tk-ghdr-btn.sunduk{background:rgba(255,255,255,.18);color:#fff;border:1.5px solid rgba(255,255,255,.35);}
    .tk-ghdr-btn.sunduk:hover{background:rgba(255,255,255,.28);}

    .tk-binom-panel{background:var(--surface2);border-radius:10px;padding:14px;margin-top:12px;display:none;border:1.5px solid var(--border);}
    .tk-binom-panel.open{display:block;}
    .tk-binom-row{display:flex;align-items:center;gap:8px;margin-bottom:8px;}
    .tk-binom-label{font-size:10px;font-weight:700;color:var(--text3);text-transform:uppercase;width:120px;flex-shrink:0;}
    .tk-binom-val{font-size:13px;font-weight:700;color:var(--text);flex:1;background:var(--surface);border:1.5px solid var(--border);border-radius:7px;padding:6px 10px;cursor:pointer;transition:.15s;}
    .tk-binom-val:hover{border-color:var(--accent1);}
    .tk-binom-copy{padding:5px 10px;font-size:11px;font-weight:700;border:none;border-radius:7px;background:var(--accent1);color:#fff;cursor:pointer;flex-shrink:0;}
    .tk-url-preview{font-size:12px;color:var(--accent1);margin-top:6px;word-break:break-all;font-weight:600;}
    .tk-geo-search{position:relative;}
    .tk-geo-dropdown{position:absolute;top:100%;left:0;right:0;background:var(--surface);border:1.5px solid var(--accent1);border-radius:10px;max-height:200px;overflow-y:auto;z-index:100;box-shadow:0 8px 24px rgba(0,0,0,.2);display:none;}
    .tk-geo-dropdown.open{display:block;}
    .tk-geo-option{padding:9px 14px;font-size:13px;cursor:pointer;color:var(--text);display:flex;align-items:center;gap:8px;}
    .tk-geo-option:hover,.tk-geo-option.focused{background:var(--surface2);}
    .tk-geo-selected{display:flex;align-items:center;gap:8px;padding:6px 0;font-size:14px;font-weight:700;color:var(--accent1);min-height:24px;}
  </style>
  <div class="tk-wrap" id="tk-wrap-top">
    <div class="tk-progress" id="tk-progress">
      <div class="tk-progress-dot active"></div>
      <div class="tk-progress-dot"></div>
      <div class="tk-progress-dot"></div>
      <div class="tk-progress-dot"></div>
    </div>

    <!-- Step 1: Basic info -->
    <div class="tk-step active" id="tk-step-1">
      <div class="tk-step-title"><span class="tk-step-num">1</span>Основная информация</div>
      <div class="tk-mb">
        <div class="tk-label">Ссылка на офер (arknet)</div>
        <input class="tk-input" id="tk-offer-url" placeholder="https://arknet.life/offers/4937#" type="url">
      </div>
      <div class="tk-row">
        <div class="tk-col" style="position:relative;">
          <div class="tk-label">Название офера (полное)</div>
          <input class="tk-input" id="tk-offer-name-full" placeholder="HondroDin HR суставы" oninput="tkAutoShort();tkOfferSuggest()" autocomplete="off" onfocus="tkOfferSuggest()" onblur="setTimeout(()=>document.getElementById('tk-offer-suggest').style.display='none',200)">
          <div id="tk-offer-suggest" style="position:absolute;top:100%;left:0;right:0;background:var(--surface);border:1.5px solid var(--accent1);border-radius:10px;z-index:100;box-shadow:0 8px 24px rgba(0,0,0,.2);display:none;max-height:150px;overflow-y:auto;"></div>
        </div>
        <div class="tk-col">
          <div class="tk-label">Короткое (для URL)</div>
          <input class="tk-input" id="tk-offer-name-short" placeholder="HondroDin">
        </div>
      </div>
      <div class="tk-mb">
        <div class="tk-label">Гео — страна</div>
        <div class="tk-geo-search">
          <input class="tk-input" id="tk-geo-search" placeholder="🔍 Поиск страны..." autocomplete="off" oninput="tkGeoFilter()" onfocus="tkGeoOpen()" onblur="setTimeout(tkGeoClose,200)">
          <div class="tk-geo-dropdown" id="tk-geo-dropdown"></div>
        </div>
        <div class="tk-geo-selected" id="tk-geo-selected"></div>
        <input type="hidden" id="tk-geo-code" value="">
        <input type="hidden" id="tk-geo-name" value="">
      </div>
      <div class="tk-row">
        <div class="tk-col">
          <div class="tk-label">ID офера</div>
          <input class="tk-input" id="tk-offer-id" placeholder="5064">
        </div>
        <div class="tk-col">
          <div class="tk-label">ID потока</div>
          <input class="tk-input" id="tk-stream-id" placeholder="15708">
        </div>
      </div>
      <div class="tk-mb">
        <div class="tk-label">API токен</div>
        <input class="tk-input" id="tk-api-token" placeholder="611-53f5294c..." oninput="tkSaveApiToken()">
        <div style="font-size:11px;color:var(--text3);margin-top:4px;">Сохраняется автоматически</div>
      </div>
      <div class="tk-nav">
        <button class="tk-btn tk-btn-next" onclick="tkNext(1)">Далее →</button>
      </div>
    </div>

    <!-- Step 2: Prokla changes -->
    <div class="tk-step" id="tk-step-2">
      <div class="tk-step-title"><span class="tk-step-num">2</span>Изменения в прокле</div>
      <div class="tk-mb">
        <div class="tk-label">Тип задачи</div>
        <div style="display:flex;gap:8px;">
          <label style="flex:1;display:flex;align-items:center;gap:8px;padding:10px 14px;border:1.5px solid var(--border);border-radius:10px;cursor:pointer;font-size:13px;font-weight:600;transition:.15s;" id="tk-type-download-wrap">
            <input type="radio" name="tk-prokla-type" value="download" checked onchange="tkTypeChange()" style="accent-color:var(--accent1);"> 📥 Скачать и внести правки
          </label>
          <label style="flex:1;display:flex;align-items:center;gap:8px;padding:10px 14px;border:1.5px solid var(--border);border-radius:10px;cursor:pointer;font-size:13px;font-weight:600;transition:.15s;" id="tk-type-copy-wrap">
            <input type="radio" name="tk-prokla-type" value="copy" onchange="tkTypeChange()" style="accent-color:var(--accent1);"> 📋 Скопировать и внести правки
          </label>
        </div>
        <div id="tk-sub-copy-url" style="margin-top:8px;display:none;">
          <div class="tk-label">Ссылка на существующую проклу</div>
          <input class="tk-input" id="tk-copy-url" placeholder="https://gvita.beauty/landers/...">
        </div>
      </div>

      <label class="tk-check-row">
        <input type="checkbox" id="tk-ch-name" checked>
        <div><div class="tk-check-label">Заменить название офера</div></div>
      </label>
      <div class="tk-sub-field show" id="tk-sub-name">
        <div class="tk-row">
          <div class="tk-col"><div class="tk-label">Старое название</div><input class="tk-input" id="tk-old-name" placeholder="Nautubone"></div>
          <div class="tk-col"><div class="tk-label">Новое название</div><input class="tk-input" id="tk-new-name-field" placeholder="HondroDin"></div>
        </div>
      </div>

      <label class="tk-check-row">
        <input type="checkbox" id="tk-ch-photo" checked>
        <div><div class="tk-check-label">Заменить фото товара</div></div>
      </label>
      <div class="tk-sub-field show" id="tk-sub-photo">
        <div class="tk-label">Clip ID / вставь фото (Ctrl+V) / или введи название</div>
        <input class="tk-input" id="tk-photo-clip" placeholder="clip43034 или вставь фото">
        <div id="tk-photo-preview" style="margin-top:8px;display:none;"><img id="tk-photo-img" style="max-width:120px;max-height:120px;border-radius:8px;border:2px solid var(--accent1);"></div>
      </div>

      <label class="tk-check-row">
        <input type="checkbox" id="tk-ch-price" checked>
        <div><div class="tk-check-label">Изменить цену</div></div>
      </label>
      <div class="tk-sub-field show" id="tk-sub-price">
        <div class="tk-row">
          <div class="tk-col"><div class="tk-label">Новая цена</div><input class="tk-input" id="tk-new-price" placeholder="39" type="number" oninput="tkCalcOld()"></div>
          <div class="tk-col"><div class="tk-label">Старая цена</div><input class="tk-input" id="tk-old-price" placeholder="78" type="number" oninput="tkCalcDiscount()"></div>
          <div class="tk-col"><div class="tk-label">Скидка</div><input class="tk-input" id="tk-discount" placeholder="50%" readonly style="opacity:.7"></div>
        </div>
        <label class="tk-check-row" style="margin-top:4px;">
          <input type="checkbox" id="tk-ch-currency">
          <div><div class="tk-check-label">Изменить валюту</div></div>
        </label>
        <div class="tk-sub-field" id="tk-sub-currency">
          <div class="tk-label">Валюта</div>
          <input class="tk-input" id="tk-currency-search" placeholder="🔍 EUR, RON, PLN..." oninput="tkCurrencyFilter()" onfocus="tkCurrencyOpen()" onblur="setTimeout(tkCurrencyClose,200)" autocomplete="off">
          <div style="position:relative;"><div id="tk-currency-dropdown" style="position:absolute;top:0;left:0;right:0;background:var(--surface);border:1.5px solid var(--accent1);border-radius:10px;max-height:160px;overflow-y:auto;z-index:100;box-shadow:0 8px 24px rgba(0,0,0,.2);display:none;"></div></div>
          <input type="hidden" id="tk-currency" value="EUR">
        </div>
      </div>

      <label class="tk-check-row">
        <input type="checkbox" id="tk-ch-mask">
        <div><div class="tk-check-label">Поставить маску на номер</div></div>
      </label>
      <div class="tk-sub-field" id="tk-sub-mask">
        <div class="tk-label">Маска</div>
        <input class="tk-input" id="tk-mask" placeholder="(+385)099999999">
      </div>

      <label class="tk-check-row">
        <input type="checkbox" id="tk-ch-cert">
        <div><div class="tk-check-label">Заменить сертификат</div></div>
      </label>
      <div class="tk-sub-field" id="tk-sub-cert">
        <div class="tk-label">Фото сертификата</div>
        <input class="tk-input" id="tk-cert-file" placeholder="clip ID / вставь фото (Ctrl+V)">
        <div id="tk-cert-preview" style="margin-top:8px;display:none;"><img id="tk-cert-img" style="max-width:120px;max-height:120px;border-radius:8px;border:2px solid var(--accent1);"></div>
      </div>

      <label class="tk-check-row">
        <input type="checkbox" id="tk-ch-comments">
        <div><div class="tk-check-label">Действия с фото в комментариях</div></div>
      </label>
      <div class="tk-sub-field" id="tk-sub-comments">
        <div style="display:flex;flex-direction:column;gap:8px;">
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;cursor:pointer;">
            <input type="radio" name="tk-comment-action" value="keep" checked style="accent-color:var(--text3);" onchange="document.getElementById('tk-ch-comments').checked=false;document.getElementById('tk-sub-comments').classList.remove('show');document.getElementById('tk-sub-comment-files').classList.remove('show');"> Оставить коменты как есть
          </label>
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;cursor:pointer;">
            <input type="radio" name="tk-comment-action" value="delete" style="accent-color:var(--accent2);" onchange="document.getElementById('tk-sub-comment-files').classList.remove('show')"> Удалить все фото из комментов
          </label>
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;cursor:pointer;">
            <input type="radio" name="tk-comment-action" value="upload" onchange="document.getElementById('tk-sub-comment-files').classList.toggle('show',this.checked)" style="accent-color:var(--accent1);"> Загрузить новые фото в коменты
          </label>
          <div class="tk-sub-field" id="tk-sub-comment-files">
            <div class="tk-label">Clip ID файлов (через запятую)</div>
            <input class="tk-input" id="tk-comment-clips" placeholder="clip43034, clip43035">
          </div>
        </div>
      </div>

      <!-- SUNDUK SPECIAL TOGGLE -->
      <div style="margin-top:18px;margin-bottom:4px;">
        <div onclick="tkToggleSunduk()" id="tk-sunduk-toggle" style="display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-radius:14px;cursor:pointer;background:linear-gradient(135deg,#1a0a2e,#2d1060);border:2px solid #7c3aed;transition:.2s;user-select:none;">
          <div style="display:flex;align-items:center;gap:10px;">
            <span style="font-size:22px;">🎁</span>
            <div>
              <div style="font-size:14px;font-weight:800;color:#c4b5fd;text-transform:uppercase;letter-spacing:.08em;">Сундук / Бек-батон</div>
              <div style="font-size:11px;color:#a78bfa;margin-top:1px;">Дополнительная страница при нажатии "Назад"</div>
            </div>
          </div>
          <div id="tk-sunduk-badge" style="padding:5px 14px;border-radius:20px;font-size:12px;font-weight:800;background:#3b1d6e;color:#a78bfa;border:1.5px solid #7c3aed;">НЕТ</div>
        </div>
        <div id="tk-sunduk-fields" style="display:none;padding:14px;border:2px solid #7c3aed;border-top:none;border-radius:0 0 14px 14px;background:#12082a;display:flex;flex-direction:column;gap:12px;">

          <div>
            <div class="tk-label" style="color:#c4b5fd;">Откуда копировать сундук (URL источника)</div>
            <input class="tk-input" id="tk-sunduk-src-url" placeholder="https://gvita.beauty/landers/official-...">
          </div>

          <div>
            <div class="tk-label" style="color:#c4b5fd;">Флаг страны (фото) <span style="color:#a78bfa;font-size:11px;">— вставить Ctrl+V или clip ID</span></div>
            <input class="tk-input" id="tk-sunduk-flag-clip" placeholder="clip ID или вставь фото (Ctrl+V)" onfocus="tkSundukFlagFocus()">
            <div id="tk-sunduk-flag-preview-img" style="margin-top:6px;display:none;"><img id="tk-sunduk-flag-img" style="max-width:160px;max-height:80px;border-radius:8px;border:2px solid #7c3aed;"></div>
          </div>

          <div>
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
              <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;font-weight:700;color:#c4b5fd;">
                <input type="checkbox" id="tk-sunduk-ch-photo" style="accent-color:#7c3aed;"> Заменить фото товара
              </label>
            </div>
            <div id="tk-sunduk-photo-field" style="display:none;">
              <div style="font-size:11px;color:#a78bfa;margin-bottom:4px;">Фото товара уже прикреплено из прокла</div>
            </div>
          </div>

          <div>
            <div class="tk-label" style="color:#c4b5fd;">Тематика офера</div>
            <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;" id="tk-sunduk-cats">
              <button class="tk-scat" onclick="tkSundukCat('diabetes',this)">💊 Диабет</button>
              <button class="tk-scat" onclick="tkSundukCat('joints',this)">🦴 Суставы</button>
              <button class="tk-scat" onclick="tkSundukCat('potency',this)">💪 Потенция</button>
              <button class="tk-scat" onclick="tkSundukCat('pressure',this)">❤️ Давление</button>
              <button class="tk-scat" onclick="tkSundukCat('varicose',this)">🦶 Варикоз</button>
              <button class="tk-scat" onclick="tkSundukCat('hearing',this)">👂 Слух</button>
              <button class="tk-scat" onclick="tkSundukCat('vision',this)">👁️ Зрение</button>
              <button class="tk-scat" onclick="tkSundukCat('weight',this)">⚖️ Похудение</button>
              <button class="tk-scat" onclick="tkSundukCat('parasites',this)">🦠 Паразиты</button>
              <button class="tk-scat" onclick="tkSundukCat('fungus',this)">💅 Грибок</button>
              <button class="tk-scat" onclick="tkSundukCat('prostate',this)">🫀 Простатит</button>
            </div>
            <textarea class="tk-input" id="tk-sunduk-old-text" rows="4" placeholder="Выбери тематику выше — текст заполнится автоматически. Или вставь свой."></textarea>
            <button onclick="tkSundukTranslate()" style="margin-top:6px;padding:8px 16px;background:#4c1d95;border:1.5px solid #7c3aed;border-radius:8px;color:#c4b5fd;font-size:12px;font-weight:700;cursor:pointer;width:100%;">🌐 Перевести на язык выбранной страны</button>
          </div>

          <div>
            <div class="tk-label" style="color:#c4b5fd;">Переведённый текст <span style="color:#a78bfa;font-size:11px;font-weight:400;">— можно редактировать</span></div>
            <textarea class="tk-input" id="tk-sunduk-new-text" rows="4" placeholder="Нажми Перевести выше..."></textarea>
          </div>

          <div>
            <div class="tk-label" style="color:#c4b5fd;">Генератор логотипа с флагом</div>
            <button onclick="tkGenFlagLogo()" style="padding:10px 16px;background:#5b21b6;border:1.5px solid #a78bfa;border-radius:8px;color:#e9d5ff;font-size:12px;font-weight:700;cursor:pointer;width:100%;">🖼️ Сгенерировать логотип (сердце + флаг)</button>
            <div id="tk-sunduk-logo-wrap" style="display:none;margin-top:10px;text-align:center;">
              <div id="tk-sunduk-logo-svg" style="display:inline-block;border-radius:12px;overflow:hidden;"></div>
              <div style="margin-top:8px;display:flex;gap:8px;justify-content:center;">
                <button onclick="tkCopySvgAsPng()" style="padding:6px 14px;background:#4c1d95;border:1.5px solid #7c3aed;border-radius:8px;color:#c4b5fd;font-size:12px;font-weight:700;cursor:pointer;">📋 Скопировать</button>
                <a id="tk-sunduk-logo-dl" download="flag-logo.svg" style="padding:6px 14px;background:#4c1d95;border:1.5px solid #7c3aed;border-radius:8px;color:#c4b5fd;font-size:12px;font-weight:700;cursor:pointer;text-decoration:none;">💾 Скачать SVG</a>
              </div>
            </div>
          </div>

        </div>
      </div>

      <div class="tk-nav">
        <button class="tk-btn tk-btn-back" onclick="tkBack(2)">← Назад</button>
        <button class="tk-btn tk-btn-next" onclick="tkNext(2)">Далее →</button>
      </div>
    </div>

    <!-- Step 3: URL naming -->
    <div class="tk-step" id="tk-step-3">
      <div class="tk-step-title"><span class="tk-step-num">3</span>Название прокла (URL)</div>
      <div style="font-size:12px;color:var(--text3);margin-bottom:16px;">https://gvita.beauty/landers/official-<b style="color:var(--text)">{название}</b>-<b style="color:var(--text)">{метка}</b>-<b style="color:var(--text)">{гео}</b>-lend<b style="color:var(--text)">{номер}</b>/</div>
      <div class="tk-row">
        <div class="tk-col">
          <div class="tk-label">Моя метка</div>
          <input class="tk-input" id="tk-url-marker" placeholder="po" value="po">
        </div>
        <div class="tk-col">
          <div class="tk-label">Номер (сплит)</div>
          <input class="tk-input" id="tk-url-num" placeholder="1" type="number" value="1" min="1">
        </div>
      </div>
      <div class="tk-url-preview" id="tk-url-preview"></div>
      <div class="tk-nav">
        <button class="tk-btn tk-btn-back" onclick="tkBack(3)">← Назад</button>
        <button class="tk-btn tk-btn-next" onclick="tkNext(3)">Сгенерировать таску →</button>
      </div>
    </div>

    <!-- Step 4: Result -->
    <div class="tk-step" id="tk-step-4">
      <div class="tk-step-title"><span class="tk-step-num">4</span>Готовая таска</div>
      <div class="tk-result">
        <div class="tk-result-text" id="tk-result-text"></div>
        <div style="display:flex;gap:8px;margin-top:12px;">
          <button class="tk-copy-btn" style="margin-top:0;flex:1;" onclick="tkCopy()">📋 Скопировать</button>
          <button class="tk-copy-btn" style="margin-top:0;background:var(--accent3);width:140px;flex-shrink:0;" onclick="tkSaveTask()">💾 Сохранить</button>
        </div>
        <div id="tk-result-photos" style="display:none;margin-top:16px;">
          <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px;">📎 Прикрепи эти фото к таске:</div>
          <div id="tk-result-photos-inner" style="display:flex;gap:10px;flex-wrap:wrap;"></div>
        </div>
        <button class="tk-btn tk-btn-back" style="width:100%;margin-top:8px;" onclick="tkBack(4)">← Изменить</button>
      </div>
    </div>

    <!-- Saved tasks -->
    <div id="tk-saved-section" style="max-width:700px;margin:32px auto 0;">
      <div id="tk-saved-header" style="display:none;margin-bottom:18px;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;padding-bottom:14px;border-bottom:2px solid var(--border);">
          <div style="width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,#4f46e5,#7c3aed);display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;">💾</div>
          <div>
            <div style="font-size:18px;font-weight:800;color:var(--text);">Сохранённые таски</div>
            <div style="font-size:12px;color:var(--text3);">Все твои прокли и сундуки</div>
          </div>
        </div>
        <div style="position:relative;margin-bottom:12px;">
          <span style="position:absolute;left:14px;top:50%;transform:translateY(-50%);font-size:16px;pointer-events:none;">🔍</span>
          <input class="tk-input" id="tk-saved-search" placeholder="Поиск по офферу или стране..." oninput="tkRenderSaved()" style="padding-left:42px;font-size:14px;">
        </div>
        <div id="tk-filter-countries" style="display:flex;flex-wrap:wrap;gap:6px;"></div>
      </div>
      <div id="tk-saved-list"></div>
    </div>
  </div>
  </div>

</div>

<script>
const files = {video:null,audio:null,img:null};
const fmts = new Set(['9:16','1:1','16:9']);
let jobId = null, pollTimer = null;
let currentFiles = [];
let ytJobId = null, ytPollTimer = null;
let privacy = 'unlisted';

async function loadProjects(){
  const resp = await fetch('/projects');
  const data = await resp.json();
  const list = document.getElementById('projects-list');
  if(!list) return;
  if(!data.projects || !data.projects.length){
    list.innerHTML = '<div style="font-size:12px;color:var(--text3);padding:4px 0;">Нет проектов — добавь client_secret.json</div>';
    return;
  }
  list.innerHTML = data.projects.map(p=>{
    const pct = Math.round(p.uploads_today/100*100);
    const color = pct>80?'#ef4444':pct>50?'#f59e0b':'#22c55e';
    return `<div style="display:flex;align-items:center;gap:10px;padding:10px 12px;background:var(--surface2);border-radius:10px;border:1.5px solid var(--border);">
      <div style="flex:1;min-width:0;">
        <div style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:4px;">🔑 ${p.name}</div>
        <div style="background:var(--border);border-radius:4px;height:6px;overflow:hidden;">
          <div style="width:${pct}%;height:100%;background:${color};border-radius:4px;transition:.3s;"></div>
        </div>
        <div style="font-size:11px;color:var(--text3);margin-top:3px;">${p.uploads_today}/100 загружено сегодня · осталось <b style="color:${color};">${p.remaining}</b></div>
      </div>
      <button onclick="deleteProject('${p.id}')" style="padding:5px 10px;font-size:11px;font-weight:700;border:1.5px solid #fca5a5;border-radius:7px;background:transparent;color:#ef4444;cursor:pointer;flex-shrink:0;">✕</button>
    </div>`;
  }).join('');
}

async function addProject(input){
  const file = input.files[0];
  if(!file) return;
  const text = await file.text();
  const name = prompt('Название проекта (например: Проект 1):', file.name.replace('.json','')) || file.name;
  const r = await fetch('/add_project',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:text,name})});
  const d = await r.json();
  if(d.ok){ loadProjects(); }
  else { alert('Ошибка: ' + d.error); }
  input.value = '';
}

async function deleteProject(id){
  if(!confirm('Удалить проект?')) return;
  await fetch('/delete_project/'+id);
  loadProjects();
}

async function loadChannels(){
  const resp = await fetch('/channels');
  const data = await resp.json();
  const list = document.getElementById('channels-list');
  const listTop = document.getElementById('channels-list-top');
  const targets = [list, listTop].filter(Boolean);
  targets.forEach(l => l.innerHTML = '');
  // Rebuild channel select
  const sel = document.getElementById('upload-channel-select');
  if(sel){ sel.innerHTML = '<option value="auto">🔄 Авто (наименее загруженный)</option>'; }
  if(!data.channels || data.channels.length === 0){
    targets.forEach(l => l.innerHTML = '<div style="font-size:13px;color:#999;padding:6px 0;">Нет добавленных каналов</div>');
    return;
  }
  const projects = (await fetch('/projects').then(r=>r.json())).projects || [];
  data.channels.forEach(ch => {
    const color = ch.available ? '#16a34a' : '#dc2626';
    const errLabel = ch.last_error ? `<span style="font-size:10px;background:#fee2e2;color:#dc2626;border-radius:4px;padding:1px 6px;margin-left:6px;">❌ ${ch.last_error}</span>` : '';
    const status = ch.available ? `${ch.uploads_today}/10 сегодня` : '❌ Лимит исчерпан';
    const proxyLabel = ch.proxy ? `<span style="font-size:10px;background:#d1fae5;color:#065f46;border-radius:4px;padding:1px 6px;margin-left:6px;">🔒 прокси</span>` : '';
    const projName = ch.project_id ? (projects.find(p=>p.id===ch.project_id)||{name:'?'}).name : null;
    const projLabel = projName
      ? `<span style="font-size:10px;background:#ede9fe;color:#6d28d9;border-radius:4px;padding:1px 6px;margin-left:6px;">🔑 ${projName}</span>`
      : '';
    const html = `<div style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:var(--surface2,#f9f9f9);border-radius:8px;border:1px solid var(--border,#e5e5e5);">
      <div>
        <div style="font-size:13px;font-weight:600;">📺 ${ch.name}${proxyLabel}${projLabel}${errLabel}</div>
        <div style="font-size:11px;color:${color};margin-top:2px;">${status}</div>
      </div>
      <button onclick="deleteChannel('${ch.id}')" style="padding:4px 10px;font-size:11px;border:1px solid #fca5a5;border-radius:6px;background:transparent;color:#dc2626;cursor:pointer;">Удалить</button>
    </div>`;
    targets.forEach(l => l.innerHTML += html);
    if(sel){ const opt=document.createElement('option'); opt.value=ch.id; opt.textContent=`📺 ${ch.name}`; sel.appendChild(opt); }
  });
  updateAutoInfo();
}

async function deleteChannel(chId){
  if(!confirm('Удалить канал?')) return;
  await fetch('/delete_channel/'+chId);
  loadChannels();
}

async function assignProject(chId){
  const data = await fetch('/projects').then(r=>r.json());
  const projects = data.projects || [];
  if(!projects.length){ alert('Сначала добавь проект API!'); return; }
  const opts = projects.map((p,i)=>`${i+1}. ${p.name}`).join('\n');
  const choice = prompt(`Выбери проект для канала:\n${opts}\n\nВведи номер:`, '1');
  if(!choice) return;
  const idx = parseInt(choice)-1;
  if(idx<0||idx>=projects.length){ alert('Неверный номер'); return; }
  const projId = projects[idx].id;
  await fetch('/assign_project',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({channel_id:chId, project_id:projId})});
  loadChannels();
}

let addChTimer = null;
async function addChannel(){
  let modal = document.getElementById('add-ch-modal');
  if(modal) modal.remove();
  modal = document.createElement('div');
  modal.id = 'add-ch-modal';
  modal.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;background:#1a1a1a;color:#7eff7e;border-radius:14px;padding:18px 20px;font-size:13px;font-family:monospace;min-width:320px;max-width:440px;box-shadow:0 8px 32px rgba(0,0,0,.6);border:1.5px solid #333;';
  modal.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;"><b style="color:#fff;font-family:sans-serif;">📺 Добавление канала</b><span onclick="this.parentElement.parentElement.remove()" style="cursor:pointer;color:#666;font-size:18px;">✕</span></div><div id="add-ch-modal-log" style="white-space:pre-wrap;">⏳ Запускаем...</div>';
  document.body.appendChild(modal);
  const log = document.getElementById('add-ch-modal-log');

  // Show input form in modal
  log.innerHTML = `
    <div style="font-family:sans-serif;color:#fff;">
      <div style="margin-bottom:12px;">
        <label style="font-size:12px;color:#aaa;display:block;margin-bottom:4px;">EMAIL АККАУНТА <span style="color:#ff6b6b;">*</span></label>
        <input id="ch-email-inp" type="email" placeholder="farmaccount@gmail.com" style="width:100%;padding:8px 10px;border-radius:8px;border:1.5px solid #444;background:#222;color:#fff;font-size:13px;outline:none;" />
      </div>
      <div style="margin-bottom:16px;">
        <label style="font-size:12px;color:#aaa;display:block;margin-bottom:4px;">ПРОКСИ КАНАЛА <span style="color:#ff6b6b;">*</span></label>
        <input id="ch-proxy-inp" type="text" placeholder="socks5://user:pass@host:port" style="width:100%;padding:8px 10px;border-radius:8px;border:1.5px solid #444;background:#222;color:#fff;font-size:13px;outline:none;" />
        <div style="font-size:11px;color:#666;margin-top:4px;">Формат: socks5://user:pass@host:port</div>
      </div>
      <button id="ch-start-btn" style="width:100%;padding:10px;background:#4f46e5;color:#fff;border:none;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;">Продолжить →</button>
    </div>`;

  const {proxyStr, loginHint, useOcto} = await new Promise(resolve => {
    document.getElementById('ch-start-btn').onclick = () => {
      const email = document.getElementById('ch-email-inp').value.trim();
      const proxy = document.getElementById('ch-proxy-inp').value.trim();
      if(!email){ document.getElementById('ch-email-inp').style.borderColor='#ff6b6b'; document.getElementById('ch-email-inp').focus(); return; }
      if(!proxy){ document.getElementById('ch-proxy-inp').style.borderColor='#ff6b6b'; document.getElementById('ch-proxy-inp').focus(); return; }
      log.textContent = '⏳ Запускаем...';
      resolve({proxyStr: proxy, loginHint: email, useOcto: true});
    };
  });

  const resp = await fetch('/add_channel', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({proxy: proxyStr, force_manual: useOcto, login_hint: loginHint})});
  const data = await resp.json();
  const jobId = data.job_id;
  let logLen = 0;

  addChTimer = setInterval(async () => {
    const sr = await fetch('/add_channel_status/'+jobId);
    const sd = await sr.json();
    const newLogs = sd.log.slice(logLen); logLen = sd.log.length;
    newLogs.forEach(l => { log.textContent += '\n' + l; });

    if(sd.status === 'waiting_code' && sd.auth_url && !document.getElementById('add-ch-code-block')){
      // Remote user — show link + code input
      const block = document.createElement('div');
      block.id = 'add-ch-code-block';
      block.style.cssText = 'margin-top:12px;font-family:sans-serif;';
      block.innerHTML = `
        <a href="${sd.auth_url}" target="_blank" style="display:block;background:#7c3aed;color:#fff;text-align:center;padding:10px;border-radius:8px;text-decoration:none;font-weight:700;margin-bottom:10px;">🔗 Открыть Google авторизацию</a>
        <div style="color:#aaa;font-size:11px;margin-bottom:6px;">После авторизации скопируй адресную строку браузера и вставь сюда:</div>
        <input id="add-ch-code-inp" placeholder="http://localhost:1/?code=..." style="width:100%;padding:8px;background:#111;border:1px solid #444;border-radius:6px;color:#fff;font-size:12px;box-sizing:border-box;margin-bottom:8px;">
        <button onclick="submitAuthCode('${jobId}')" style="width:100%;padding:9px;background:#16a34a;color:#fff;border:none;border-radius:8px;font-weight:700;cursor:pointer;">✅ Подтвердить</button>
      `;
      modal.appendChild(block);
    }

    if(sd.status === 'done'){
      clearInterval(addChTimer);
      loadChannels();
      setTimeout(() => { modal.remove(); }, 3000);
    } else if(sd.status === 'error'){
      clearInterval(addChTimer);
      modal.style.borderColor = '#ef4444';
    }
  }, 1000);
}

async function submitAuthCode(jobId){
  const raw = document.getElementById('add-ch-code-inp').value.trim();
  if(!raw){ alert('Вставь адресную строку!'); return; }
  const btn = document.querySelector('#add-ch-code-block button');
  btn.textContent = '⏳ Проверяем...'; btn.disabled = true;
  const r = await fetch('/add_channel_code', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({job_id: jobId, code: raw})});
  const d = await r.json();
  if(!d.ok){ btn.textContent = '❌ Ошибка: ' + d.error; btn.disabled = false; }
}

// Load channels when YT section appears
const ytObserver = new MutationObserver(() => {
  const yt = document.getElementById('yt-section');
  if(yt && yt.style.display !== 'none') loadChannels();
});
document.addEventListener('DOMContentLoaded', () => {
  const yt = document.getElementById('yt-section');
  if(yt) ytObserver.observe(yt, {attributes:true, attributeFilter:['style']});
});

let uploadCat = '';
let uploadPrivacy = 'unlisted';
let uploadReadyFiles = [];

function setUploadCat(btn){
  document.querySelectorAll('#upload-cat-grid .lang-btn').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  uploadCat = btn.dataset.cat;
}

function setUploadPrivacy(p){
  uploadPrivacy = p;
  ['public','unlisted','private'].forEach(x=>{
    document.getElementById('up-priv-'+x).classList.toggle('on', x===p);
  });
}

async function generateAutoMeta(){
  const btn=document.getElementById('auto-gen-btn');
  btn.disabled=true;btn.textContent='⏳ Генерирую...';
  document.getElementById('auto-ai-result').style.display='none';
  try{
    const resp=await fetch('/ai_generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic:'NEUTRAL_LIFESTYLE'})});
    const data=await resp.json();
    if(data.error){alert('Ошибка: '+data.error);return;}
    const text=data.text;
    const t=text.match(/TITLE:\s*(.+)/);
    const d=text.match(/DESCRIPTION:\s*([\s\S]+)/);
    if(t&&d){
      document.getElementById('auto-ai-title').textContent=t[1].trim();
      document.getElementById('auto-ai-desc').textContent=d[1].trim();
      document.getElementById('auto-ai-result').style.display='block';
    }
  }catch(e){alert('Ошибка: '+e.message);}
  btn.disabled=false;btn.textContent='✨ Сгенерировать нейтральный заголовок (AI)';
}

async function generateUploadMeta(){
  const btn=document.getElementById('upload-gen-btn');
  btn.disabled=true;btn.textContent='⏳ Генерирую...';
  document.getElementById('upload-ai-result').style.display='none';
  try{
    const resp=await fetch('/ai_generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic:'NEUTRAL_LIFESTYLE'})});
    const data=await resp.json();
    if(data.error){alert('Ошибка: '+data.error);return;}
    const text=data.text;
    const t=text.match(/TITLE:\s*(.+)/);
    const d=text.match(/DESCRIPTION:\s*([\s\S]+)/);
    if(t&&d){
      document.getElementById('upload-ai-title').textContent=t[1].trim();
      document.getElementById('upload-ai-desc').textContent=d[1].trim();
      document.getElementById('upload-ai-result').style.display='block';
    }
  }catch(e){alert('Ошибка: '+e.message);}
  btn.disabled=false;btn.textContent='✨ Сгенерировать нейтральный заголовок (AI)';
}

function applyUploadMeta(){
  document.getElementById('upload-title').value=document.getElementById('upload-ai-title').textContent;
  document.getElementById('upload-desc').value=document.getElementById('upload-ai-desc').textContent;
  alert('Применено!');
}

async function handleUploadFiles(input){
  const files = Array.from(input.files);
  if(!files.length) return;
  const listEl = document.getElementById('upload-files-list');
  listEl.innerHTML = '⏳ Загружаем файлы на сервер...';
  const promises = files.map(f => {
    const fd = new FormData();
    fd.append('file', f);
    fd.append('type', 'video');
    fd.append('filename', f.name);
    return fetch('/upload',{method:'POST',body:fd}).then(r=>r.json()).then(d=>({
      path: d.path,
      fmt: f.name.replace('.mp4',''),
      size: (f.size/1024/1024).toFixed(1),
      title: f.name.replace('.mp4','')
    }));
  });
  uploadReadyFiles = await Promise.all(promises);
  listEl.innerHTML = uploadReadyFiles.map(f=>`✅ ${f.fmt} (${f.size}MB)`).join('<br>');
  console.log('uploadReadyFiles:', uploadReadyFiles);
  if(uploadReadyFiles.length > 0){
    document.getElementById('upload-yt-btn').disabled = false;
    document.getElementById('upload-yt-btn').style.background='#ff0000';
  }
}

let uploadJobId = null, uploadPollTimer = null, uploadLogLen = 0;

function startDirectUpload(){
  const title = document.getElementById('upload-title').value || 'Video';
  const desc = document.getElementById('upload-desc').value || '';
  if(!uploadReadyFiles.length){alert('Выбери файлы!');return;}
  const btn = document.getElementById('upload-yt-btn');
  btn.disabled = true;
  const log = document.getElementById('upload-yt-log');
  log.style.display='block'; log.textContent='';
  document.getElementById('upload-yt-links').innerHTML='';
  const files = uploadReadyFiles.map(f=>({...f, title: title+' ['+f.fmt+']'}));
  const _selCh = document.getElementById('upload-channel-select');
  const _chId = _selCh ? _selCh.value : 'auto';
  fetch('/yt_upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({files,title,description:desc,privacy:uploadPrivacy,channel_id:_chId})})
    .then(r=>r.json()).then(d=>{uploadJobId=d.job_id;uploadLogLen=0;uploadPollTimer=setInterval(pollUpload,1000);});
}

function pollUpload(){
  fetch('/yt_status/'+uploadJobId).then(r=>r.json()).then(d=>{
    const newLogs=d.log.slice(uploadLogLen);uploadLogLen=d.log.length;
    const log=document.getElementById('upload-yt-log');
    newLogs.forEach(l=>{log.textContent+=l+'\n';});
    log.scrollTop=log.scrollHeight;
    if(d.status==='done'||d.status==='error'){
      clearInterval(uploadPollTimer);
      document.getElementById('upload-yt-btn').disabled=false;
      document.getElementById('upload-yt-btn').style.background='#ff0000';
      if(d.links && d.links.length){
        const linksEl=document.getElementById('upload-yt-links');
        d.links.forEach(l=>{
          linksEl.innerHTML+=`<a href="${l.link}" target="_blank" style="display:block;padding:8px 12px;background:#f0fdf4;border:1px solid #86efac;border-radius:8px;color:#16a34a;text-decoration:none;font-size:13px;margin-bottom:6px;">✅ ${l.fmt} → ${l.link}</a>`;
        });
      }
    }
  }).catch(e=>{ console.error('pollUpload error:', e); });
}

let proklaZipData = null;
let proklaImgData = null;
let proklaImgExt = null;

// Load saved offer names
function loadProklaNames(){
  const names = JSON.parse(localStorage.getItem('prokla_names') || '[]');
  const container = document.getElementById('prokla-names-history');
  if(!container) return;
  container.innerHTML = '';
  names.forEach(name => {
    const chip = document.createElement('div');
    chip.className = 'pk-chip';
    chip.textContent = name;
    chip.onclick = () => { document.getElementById('prokla-new-name').value = name; checkProklaReady(); calcOldPrice(); };
    container.appendChild(chip);
  });
}

function saveProklaName(name){
  if(!name) return;
  const names = JSON.parse(localStorage.getItem('prokla_names') || '[]');
  if(!names.includes(name)){
    names.unshift(name);
    if(names.length > 10) names.pop();
    localStorage.setItem('prokla_names', JSON.stringify(names));
  }
}

function setProklaType(type){
  document.getElementById('prokla-type').value = type;
  document.getElementById('type-static').style.background = type==='static' ? 'rgba(99,102,241,0.8)' : 'rgba(255,255,255,0.07)';
  document.getElementById('type-static').style.borderColor = type==='static' ? '#818cf8' : 'rgba(255,255,255,0.15)';
  document.getElementById('type-vsl').style.background = type==='vsl' ? 'rgba(99,102,241,0.8)' : 'rgba(255,255,255,0.07)';
  document.getElementById('type-vsl').style.borderColor = type==='vsl' ? '#818cf8' : 'rgba(255,255,255,0.15)';
  // Name field always enabled - for VSL it changes name in form only
  const nameSection = document.getElementById('prokla-name-section');
  if(nameSection){ nameSection.style.opacity = '1'; nameSection.style.pointerEvents = 'auto'; }
}

function selectPhoneMask(sel){
  if(sel.value) document.getElementById('prokla-phone-mask').value = sel.value;
}

function calcOldPrice(){
  const price = parseFloat(document.getElementById('prokla-new-price').value);
  const discount = parseFloat(document.getElementById('prokla-discount').value) || 50;
  const currency = document.getElementById('prokla-currency').value;
  const el = document.getElementById('prokla-old-price-show');
  if(price && discount){
    const old = Math.round(price / (1 - discount/100));
    el.textContent = old + ' ' + currency;
  } else {
    el.textContent = '—';
  }
}

function handleProklaZip(input){
  const file = input.files[0];
  if(!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    proklaZipData = e.target.result;
    document.getElementById('prokla-zip-lbl').textContent = '✅ ' + file.name;
    document.getElementById('prokla-zip-lbl').className = 'prokla-drop-text ok';
    document.getElementById('prokla-drop').classList.add('ok');
    checkProklaReady();
    analyzeProkla();
  };
  reader.readAsDataURL(file);
}

async function analyzeProkla(){
  const panel = document.getElementById('prokla-analysis');
  const items = document.getElementById('prokla-found-items');
  panel.style.display = 'block';
  items.innerHTML = '<span style="color:var(--text3);font-size:12px;">Анализируем...</span>';
  try {
    const resp = await fetch('/analyze_prokla', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({zip_data: proklaZipData})
    });
    const data = await resp.json();
    if(data.error){ items.innerHTML = '<span style="color:var(--accent2);">⚠️ ' + data.error + '</span>'; return; }
    items.innerHTML = '';
    function chip(label, val, fieldId){
      const d = document.createElement('div');
      d.style.cssText = 'background:var(--surface);border:1.5px solid var(--border);border-radius:8px;padding:8px 12px;font-size:12px;';
      d.innerHTML = '<div style="color:var(--text3);font-size:10px;font-weight:700;text-transform:uppercase;margin-bottom:3px;">'+label+'</div>'
        + '<div style="color:var(--text);font-weight:700;">'+val+'</div>';
      if(fieldId){
        const el = document.getElementById(fieldId);
        if(el && !el.value) el.value = val;
      }
      items.appendChild(d);
    }
    if(data.price) chip('Текущая цена', data.price, 'prokla-new-price');
    if(data.currency){
      chip('Валюта', data.currency);
      const sel = document.getElementById('prokla-currency');
      if(sel){ for(let o of sel.options){ if(o.value===data.currency){ sel.value=data.currency; break; } } }
    }
    if(data.offer_name) chip('Название офера', data.offer_name, 'prokla-new-name');
    if(data.price || data.currency || data.offer_name) calcOldPrice();
  } catch(e){ items.innerHTML = '<span style="color:var(--text3);font-size:12px;">Не удалось проанализировать</span>'; }
}

function handleProklaImg(input){
  const file = input.files[0];
  if(!file) return;
  proklaImgExt = file.name.split('.').pop().toLowerCase();
  const reader = new FileReader();
  reader.onload = e => {
    proklaImgData = e.target.result;
    document.getElementById('prokla-img-lbl').textContent = '✅ ' + file.name;
    document.getElementById('prokla-img-drop').classList.add('ok');
    document.getElementById('prokla-img-icon').style.display='none';
    const prev = document.getElementById('prokla-img-preview');
    prev.innerHTML = '<img src="'+e.target.result+'" style="width:100%;height:100%;object-fit:cover;border-radius:10px;">';
    checkProklaReady();
  };
  reader.readAsDataURL(file);
}

function checkProklaReady(){
  const ready = proklaZipData && document.getElementById('prokla-new-name').value;
  document.getElementById('prokla-btn').disabled = !ready;
}

async function processProkla(){
  const log = document.getElementById('prokla-log');
  log.style.display = 'block';
  log.textContent = '⏳ Обрабатываем...';
  document.getElementById('prokla-btn').disabled = true;
  document.getElementById('prokla-preview-section').style.display = 'none';

  const newName = document.getElementById('prokla-new-name').value;
  const newPriceVal = document.getElementById('prokla-new-price').value;
  const discount = parseFloat(document.getElementById('prokla-discount').value) || 50;
  const currency = document.getElementById('prokla-currency').value;
  const newPriceFull = newPriceVal ? newPriceVal + ' ' + currency : '';
  const oldPriceNum = newPriceVal ? Math.round(parseFloat(newPriceVal) / (1 - discount/100)) : 0;
  const oldPriceFull = oldPriceNum ? oldPriceNum + ' ' + currency : '';
  saveProklaName(newName);
  const reviewAction = document.querySelector('input[name="review-photo-action"]:checked')?.value || 'none';
  const params = {
    zip_data: proklaZipData,
    img_data: proklaImgData,
    img_ext: proklaImgExt,
    new_name: newName,
    new_price: newPriceFull,
    old_price: oldPriceFull,
    price_was: '',
    discount: discount + '%',
    currency: currency,
    phone_mask: document.getElementById('prokla-phone-mask').value.trim(),
    old_name: document.getElementById('prokla-old-name') ? document.getElementById('prokla-old-name').value.trim() : '',
    review_photo_action: reviewAction,
  };

  const resp = await fetch('/process_prokla', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(params)
  });
  const data = await resp.json();
  if(data.error){ log.textContent = '❌ ' + data.error; document.getElementById('prokla-btn').disabled=false; return; }
  log.textContent = data.log + '\n✅ Готово!';

  // Auto download
  const a = document.createElement('a');
  a.href = '/download_prokla/' + data.file_id;
  a.download = data.filename;
  a.click();
  document.getElementById('prokla-btn').disabled = false;

  // Show preview
  showProklaPreview(data.file_id, data.is_vsl, data.form_anchor || '', data.preview_index || 'index.html');
}

function showProklaPreview(fileId, isVsl, formAnchor, previewIndex){
  const section = document.getElementById('prokla-preview-section');
  const phones = document.getElementById('pk-preview-phones');
  const badge = document.getElementById('pk-vsl-badge');
  phones.innerHTML = '';
  badge.style.display = isVsl ? 'inline-block' : 'none';

  const baseUrl = '/preview/' + fileId + '/' + previewIndex;

  function makePhone(label, src){
    const wrap = document.createElement('div');
    wrap.className = 'pk-phone-wrap';
    wrap.innerHTML = `<div class="pk-phone-label">${label}</div>`;
    const phone = document.createElement('div');
    phone.className = 'pk-phone';
    const iframe = document.createElement('iframe');
    iframe.src = src;
    phone.appendChild(iframe);
    wrap.appendChild(phone);
    const btnRow = document.createElement('div');
    btnRow.className = 'pk-phone-btn-row';
    const reloadBtn = document.createElement('button');
    reloadBtn.className = 'pk-phone-btn reload';
    reloadBtn.textContent = '🔄 Обновить';
    reloadBtn.onclick = () => { iframe.src = iframe.src; };
    const openBtn = document.createElement('button');
    openBtn.className = 'pk-phone-btn';
    openBtn.textContent = '↗ Открыть';
    openBtn.onclick = () => window.open(src, '_blank');
    btnRow.appendChild(reloadBtn);
    btnRow.appendChild(openBtn);
    if(isVsl){
      const formBtn = document.createElement('button');
      formBtn.className = 'pk-phone-btn';
      formBtn.textContent = '📋 Форма';
      formBtn.onclick = () => {
        try {
          const doc = iframe.contentDocument || iframe.contentWindow.document;
          // unhide all hidden elements that look like form/order blocks
          doc.querySelectorAll('*').forEach(el => {
            const s = window.getComputedStyle(el);
            const id = (el.id||'').toLowerCase();
            const cls = (el.className||'').toLowerCase();
            if(s.display==='none' && (id.match(/form|order|checkout|buy/) || cls.match(/form|order|checkout|buy/))){
              el.style.display='block';
            }
          });
          // scroll to form
          const sel = ['form','#form','#order','#checkout','[id*=form]','[id*=order]','[class*=form__wrap]','[class*=order]'];
          for(const s of sel){
            const el = doc.querySelector(s);
            if(el){ el.scrollIntoView({behavior:'smooth',block:'start'}); break; }
          }
        } catch(e){ alert('Ошибка: '+e.message); }
      };
      btnRow.appendChild(formBtn);
    }
    wrap.appendChild(btnRow);
    return wrap;
  }

  phones.appendChild(makePhone(isVsl ? '▶ ВСЛ — Прокла' : '📱 Превью прокла', baseUrl));

  section.style.display = 'block';
  section.scrollIntoView({behavior:'smooth', block:'start'});
}

// Enable button when name is typed
document.addEventListener('input', e => {
  if(e.target.id === 'prokla-new-name') checkProklaReady();
});

function updateReviewOpt(){
  ['replace','delete','none'].forEach(v => {
    const wrap = document.getElementById('review-opt-'+v+'-wrap');
    const radio = document.getElementById('review-opt-'+v);
    if(wrap && radio) {
      const colors = {replace:'var(--accent1)',delete:'var(--accent2)',none:'var(--border2)'};
      wrap.style.borderColor = radio.checked ? colors[v] : 'var(--border)';
      wrap.style.background = radio.checked ? (v==='replace'?'rgba(108,99,255,.06)':v==='delete'?'rgba(255,101,132,.06)':'var(--surface2)') : '';
    }
  });
}

function switchTab(tab){
  document.querySelectorAll('.tab-btn').forEach((b,i)=>b.classList.toggle('active',['editor','ads','upload','tasks','binom'][i]===tab));
  document.querySelectorAll('.tab-pane').forEach(p=>p.classList.remove('active'));
  document.getElementById('tab-'+tab).classList.add('active');
  if(tab==='prokla') loadProklaNames();
  if(tab==='tasks') tkInit();
  if(tab==='upload'){ loadChannels(); loadProjects(); }
  if(tab==='binom'){ loadBinom(); }
}

// ===== TASKS =====
let tkGeoCode='', tkGeoName='', tkCurrentStep=1;
const TK_STEPS=4;

const TK_COUNTRIES=[
  {n:'Хорватия',c:'hr',flag:'🇭🇷',cur:'EUR'},
  {n:'Сербия',c:'rs',flag:'🇷🇸',cur:'RSD'},
  {n:'Румыния',c:'ro',flag:'🇷🇴',cur:'RON'},
  {n:'Польша',c:'pl',flag:'🇵🇱',cur:'PLN'},
  {n:'Испания',c:'es',flag:'🇪🇸',cur:'EUR'},
  {n:'Украина',c:'ua',flag:'🇺🇦',cur:'UAH'},
  {n:'Молдова',c:'md',flag:'🇲🇩',cur:'MDL'},
  {n:'Венгрия',c:'hu',flag:'🇭🇺',cur:'HUF'},
  {n:'Германия',c:'de',flag:'🇩🇪',cur:'EUR'},
  {n:'Франция',c:'fr',flag:'🇫🇷',cur:'EUR'},
  {n:'Италия',c:'it',flag:'🇮🇹',cur:'EUR'},
  {n:'Португалия',c:'pt',flag:'🇵🇹',cur:'EUR'},
  {n:'Греция',c:'gr',flag:'🇬🇷',cur:'EUR'},
  {n:'Австрия',c:'at',flag:'🇦🇹',cur:'EUR'},
  {n:'Бельгия',c:'be',flag:'🇧🇪',cur:'EUR'},
  {n:'Нидерланды',c:'nl',flag:'🇳🇱',cur:'EUR'},
  {n:'Чехия',c:'cz',flag:'🇨🇿',cur:'CZK'},
  {n:'Словакия',c:'sk',flag:'🇸🇰',cur:'EUR'},
  {n:'Болгария',c:'bg',flag:'🇧🇬',cur:'BGN'},
  {n:'Словения',c:'si',flag:'🇸🇮',cur:'EUR'},
  {n:'Швейцария',c:'ch',flag:'🇨🇭',cur:'CHF'},
  {n:'Швеция',c:'se',flag:'🇸🇪',cur:'SEK'},
  {n:'Норвегия',c:'no',flag:'🇳🇴',cur:'NOK'},
  {n:'Дания',c:'dk',flag:'🇩🇰',cur:'DKK'},
  {n:'Финляндия',c:'fi',flag:'🇫🇮',cur:'EUR'},
  {n:'Литва',c:'lt',flag:'🇱🇹',cur:'EUR'},
  {n:'Латвия',c:'lv',flag:'🇱🇻',cur:'EUR'},
  {n:'Эстония',c:'ee',flag:'🇪🇪',cur:'EUR'},
  {n:'Босния',c:'ba',flag:'🇧🇦',cur:'BAM'},
  {n:'Черногория',c:'me',flag:'🇲🇪',cur:'EUR'},
  {n:'Македония',c:'mk',flag:'🇲🇰',cur:'MKD'},
  {n:'Албания',c:'al',flag:'🇦🇱',cur:'ALL'},
  {n:'Косово',c:'xk',flag:'🇽🇰',cur:'EUR'},
  {n:'Беларусь',c:'by',flag:'🇧🇾',cur:'BYR'},
  {n:'Турция',c:'tr',flag:'🇹🇷',cur:'TRY'},
  {n:'Казахстан',c:'kz',flag:'🇰🇿',cur:'KZT'},
  {n:'Грузия',c:'ge',flag:'🇬🇪',cur:'GEL'},
  {n:'Армения',c:'am',flag:'🇦🇲',cur:'AMD'},
  {n:'Узбекистан',c:'uz',flag:'🇺🇿',cur:'UZS'},
];

const TK_CURRENCIES=[
  {c:'EUR',n:'Евро'},
  {c:'USD',n:'Доллар'},
  {c:'PLN',n:'Польский злотый'},
  {c:'RON',n:'Румынский лей'},
  {c:'UAH',n:'Гривна'},
  {c:'MDL',n:'Молдавский лей'},
  {c:'RSD',n:'Сербский динар'},
  {c:'HUF',n:'Венгерский форинт'},
  {c:'CZK',n:'Чешская крона'},
  {c:'BGN',n:'Болгарский лев'},
  {c:'CHF',n:'Швейцарский франк'},
  {c:'SEK',n:'Шведская крона'},
  {c:'NOK',n:'Норвежская крона'},
  {c:'DKK',n:'Датская крона'},
  {c:'BAM',n:'Конвертируемая марка'},
  {c:'MKD',n:'Македонский денар'},
  {c:'ALL',n:'Албанский лек'},
  {c:'TRY',n:'Турецкая лира'},
  {c:'KZT',n:'Казахский тенге'},
  {c:'GEL',n:'Грузинский лари'},
  {c:'GBP',n:'Фунт стерлингов'},
  {c:'HRK',n:'Хорватская куна'},
];

function tkInit(){
  const saved = localStorage.getItem('tk_api_token');
  if(saved) document.getElementById('tk-api-token').value=saved;
  document.querySelectorAll('#tk-step-2 .tk-check-row input[type=checkbox]').forEach(cb=>{
    cb.onchange = ()=>{
      const sub = document.getElementById('tk-sub-'+cb.id.replace('tk-ch-',''));
      if(sub) sub.classList.toggle('show', cb.checked);
    };
  });
  tkUpdateUrlPreview();
  ['tk-offer-name-short','tk-url-marker','tk-url-num'].forEach(id=>{
    const el=document.getElementById(id);
    if(el) el.oninput=tkUpdateUrlPreview;
  });
  tkRenderGeo('');
  tkRenderCurrencies('');
  tkRenderSaved();
}

function tkSaveApiToken(){ localStorage.setItem('tk_api_token', document.getElementById('tk-api-token').value); }

function tkTypeChange(){
  const val=document.querySelector('input[name="tk-prokla-type"]:checked').value;
  document.getElementById('tk-sub-copy-url').style.display=val==='copy'?'block':'none';
}

// Geo search
function tkRenderGeo(q){
  const dd=document.getElementById('tk-geo-dropdown');
  const matches=TK_COUNTRIES.filter(c=>c.n.toLowerCase().includes(q.toLowerCase())||c.c.includes(q.toLowerCase()));
  dd.innerHTML=matches.map(c=>`<div class="tk-geo-option" onmousedown="tkPickGeo('${c.n}','${c.c}','${c.flag}','${c.cur}')">${c.flag} ${c.n} <span style="color:var(--text3);font-size:11px;margin-left:auto;">${c.c.toUpperCase()}</span></div>`).join('');
}
function tkGeoFilter(){ tkRenderGeo(document.getElementById('tk-geo-search').value); }
function tkGeoOpen(){ document.getElementById('tk-geo-dropdown').classList.add('open'); tkRenderGeo(document.getElementById('tk-geo-search').value); }
function tkGeoClose(){ document.getElementById('tk-geo-dropdown').classList.remove('open'); }
function tkPickGeo(name,code,flag,cur){
  tkGeoCode=code; tkGeoName=name;
  document.getElementById('tk-geo-code').value=code;
  document.getElementById('tk-geo-name').value=name;
  document.getElementById('tk-geo-search').value='';
  document.getElementById('tk-geo-selected').innerHTML=`${flag} <b>${name}</b> <span style="color:var(--text3);font-size:12px;">${code.toUpperCase()}</span> <span onclick="tkClearGeo()" style="color:var(--accent2);cursor:pointer;margin-left:8px;font-size:12px;">✕</span>`;
  document.getElementById('tk-geo-dropdown').classList.remove('open');
  // Auto-set currency
  document.getElementById('tk-currency-search').value=cur;
  document.getElementById('tk-currency').value=cur;
  tkUpdateUrlPreview();
}
function tkClearGeo(){
  tkGeoCode=''; tkGeoName='';
  document.getElementById('tk-geo-code').value='';
  document.getElementById('tk-geo-name').value='';
  document.getElementById('tk-geo-selected').innerHTML='';
  tkUpdateUrlPreview();
}

// Currency search
function tkRenderCurrencies(q){
  const dd=document.getElementById('tk-currency-dropdown');
  const matches=TK_CURRENCIES.filter(c=>c.c.toLowerCase().includes(q.toLowerCase())||c.n.toLowerCase().includes(q.toLowerCase()));
  dd.innerHTML=matches.map(c=>`<div class="tk-geo-option" onmousedown="tkPickCurrency('${c.c}','${c.n}')">${c.c} <span style="color:var(--text3);font-size:11px;">${c.n}</span></div>`).join('');
}
function tkCurrencyFilter(){ tkRenderCurrencies(document.getElementById('tk-currency-search').value); document.getElementById('tk-currency-dropdown').style.display='block'; }
function tkCurrencyOpen(){ document.getElementById('tk-currency-dropdown').style.display='block'; tkRenderCurrencies(document.getElementById('tk-currency-search').value||''); }
function tkCurrencyClose(){ document.getElementById('tk-currency-dropdown').style.display='none'; }
function tkPickCurrency(code,name){
  document.getElementById('tk-currency').value=code;
  document.getElementById('tk-currency-search').value=code+' — '+name;
  document.getElementById('tk-currency-dropdown').style.display='none';
}

// Offer name memory
function tkOfferSuggest(){
  const val=document.getElementById('tk-offer-name-full').value.toLowerCase();
  const saved=JSON.parse(localStorage.getItem('tk_offers')||'[]');
  const box=document.getElementById('tk-offer-suggest');
  const matches=saved.filter(o=>o.full.toLowerCase().includes(val));
  if(!matches.length){ box.style.display='none'; return; }
  box.innerHTML=matches.map(o=>`<div class="tk-geo-option" onmousedown="tkPickOffer(${JSON.stringify(o).replace(/"/g,'&quot;')})">${o.full} <span style='color:var(--text3);font-size:11px;'>${o.short}</span></div>`).join('');
  box.style.display='block';
}
function tkPickOffer(o){
  document.getElementById('tk-offer-name-full').value=o.full;
  document.getElementById('tk-offer-name-short').value=o.short;
  document.getElementById('tk-offer-suggest').style.display='none';
  document.getElementById('tk-new-name-field').value=o.short;
  tkUpdateUrlPreview();
}
function tkSaveOffer(){
  const full=document.getElementById('tk-offer-name-full').value.trim();
  const short=document.getElementById('tk-offer-name-short').value.trim();
  if(!full) return;
  const saved=JSON.parse(localStorage.getItem('tk_offers')||'[]');
  if(!saved.find(o=>o.full===full)){
    saved.unshift({full,short});
    localStorage.setItem('tk_offers',JSON.stringify(saved.slice(0,30)));
  }
}

function tkAutoShort(){
  const full=document.getElementById('tk-offer-name-full').value;
  const short=full.split(' ')[0];
  const el=document.getElementById('tk-offer-name-short');
  if(!el.dataset.edited) el.value=short;
  document.getElementById('tk-new-name-field').value=short;
  tkUpdateUrlPreview();
  // Auto-detect country from offer name (e.g. "DIZAXEN PL диабет" → Poland)
  if(!tkGeoCode){
    const words=full.toUpperCase().split(/\s+/);
    for(const w of words){
      const found=TK_COUNTRIES.find(c=>c.c.toUpperCase()===w);
      if(found){ tkPickGeo(found.n, found.c, found.flag, found.cur); break; }
    }
  }
}

function tkCalcOld(){
  const np=parseFloat(document.getElementById('tk-new-price').value)||0;
  const op=document.getElementById('tk-old-price');
  if(np&&!op.dataset.edited){ op.value=Math.round(np*2); }
  tkCalcDiscount();
}
function tkCalcDiscount(){
  const n=parseFloat(document.getElementById('tk-new-price').value)||0;
  const o=parseFloat(document.getElementById('tk-old-price').value)||0;
  if(n&&o) document.getElementById('tk-discount').value=Math.round((1-n/o)*100)+'%';
}

function tkUpdateUrlPreview(){
  const name=document.getElementById('tk-offer-name-short').value||'НазваниеОфера';
  const marker=document.getElementById('tk-url-marker').value||'po';
  const geo=tkGeoCode||'geo';
  const num=document.getElementById('tk-url-num').value||'1';
  const url=`https://gvita.beauty/landers/official-${name}-${marker}-${geo}-lend${num}/`;
  const el=document.getElementById('tk-url-preview');
  if(el) el.textContent=url;
}

let tkSundukOn = false;
// Flag data: colors [top,mid,bot], phrase for logo, language code for translation
const TK_FLAG_DATA={
  hr:{c:['#FF0000','#FFFFFF','#003DA5'],p1:'ZDRAVA',p2:'ZEMLJA',lang:'hr'},
  rs:{c:['#C6363C','#0C4077','#EDB92E'],p1:'ЗДРАВА',p2:'ЗЕМЉА',lang:'sr'},
  ro:{c:['#002B7F','#FCD116','#CE1126'],p1:'ȚARA',p2:'SĂNĂTOASĂ',lang:'ro'},
  pl:{c:['#FFFFFF','#DC143C','#DC143C'],p1:'ZDROWY',p2:'KRAJ',lang:'pl'},
  es:{c:['#AA151B','#F1BF00','#AA151B'],p1:'PAÍS',p2:'SANO',lang:'es'},
  ua:{c:['#005BBB','#FFD500','#005BBB'],p1:'ЗДОРОВА',p2:'КРАЇНА',lang:'uk'},
  md:{c:['#003DA5','#FFD200','#CC0001'],p1:'ȚARA',p2:'SĂNĂTOASĂ',lang:'ro'},
  hu:{c:['#CE2939','#FFFFFF','#477050'],p1:'EGÉSZSÉGES',p2:'ORSZÁG',lang:'hu'},
  de:{c:['#000000','#DD0000','#FFCE00'],p1:'GESUNDES',p2:'LAND',lang:'de'},
  fr:{c:['#002395','#FFFFFF','#ED2939'],p1:'PAYS',p2:'SAIN',lang:'fr'},
  it:{c:['#009246','#FFFFFF','#CE2B37'],p1:'PAESE',p2:'SANO',lang:'it'},
  pt:{c:['#006600','#FF0000','#006600'],p1:'PAÍS',p2:'SAUDÁVEL',lang:'pt'},
  gr:{c:['#0D5EAF','#FFFFFF','#0D5EAF'],p1:'ΥΓΙΕΙΝΗ',p2:'ΧΩΡΑ',lang:'el'},
  at:{c:['#ED2939','#FFFFFF','#ED2939'],p1:'GESUNDES',p2:'LAND',lang:'de'},
  be:{c:['#000000','#FAE042','#EF3340'],p1:'GEZOND',p2:'LAND',lang:'nl'},
  nl:{c:['#AE1C28','#FFFFFF','#21468B'],p1:'GEZOND',p2:'LAND',lang:'nl'},
  cz:{c:['#FFFFFF','#D7141A','#11457E'],p1:'ZDRAVÁ',p2:'ZEMĚ',lang:'cs'},
  sk:{c:['#FFFFFF','#0B4EA2','#EE1C25'],p1:'ZDRAVÁ',p2:'KRAJINA',lang:'sk'},
  bg:{c:['#FFFFFF','#00966E','#D62612'],p1:'ЗДРАВА',p2:'СТРАНА',lang:'bg'},
  si:{c:['#003DA5','#FFFFFF','#DD0000'],p1:'ZDRAVA',p2:'DEŽELA',lang:'sl'},
  ch:{c:['#FF0000','#FFFFFF','#FF0000'],p1:'GESUNDES',p2:'LAND',lang:'de'},
  se:{c:['#006AA7','#FECC02','#006AA7'],p1:'FRISKT',p2:'LAND',lang:'sv'},
  no:{c:['#EF2B2D','#FFFFFF','#EF2B2D'],p1:'SUNT',p2:'LAND',lang:'no'},
  dk:{c:['#C60C30','#FFFFFF','#C60C30'],p1:'SUNDT',p2:'LAND',lang:'da'},
  fi:{c:['#FFFFFF','#003580','#FFFFFF'],p1:'TERVE',p2:'MAA',lang:'fi'},
  lt:{c:['#FDB913','#006A44','#C1272D'],p1:'SVEIKA',p2:'ŠALIS',lang:'lt'},
  lv:{c:['#9E3039','#FFFFFF','#9E3039'],p1:'VESELĪGA',p2:'ZEME',lang:'lv'},
  ee:{c:['#0072CE','#000000','#FFFFFF'],p1:'TERVE',p2:'MAA',lang:'et'},
  ba:{c:['#002395','#FFCC00','#002395'],p1:'ZDRAVA',p2:'ZEMLJA',lang:'bs'},
  me:{c:['#D4AF37','#D4AF37','#D4AF37'],p1:'ZDRAVA',p2:'ZEMLJA',lang:'sr'},
  mk:{c:['#CE2028','#F7C535','#CE2028'],p1:'ЗДРАВА',p2:'ЗЕМЈА',lang:'mk'},
  al:{c:['#E41E20','#000000','#E41E20'],p1:'SHËNDETI',p2:'VEND',lang:'sq'},
  xk:{c:['#244AA5','#E4C842','#244AA5'],p1:'VEND',p2:'SHËNDETSHËM',lang:'sq'},
  by:{c:['#CF101A','#009A44','#CF101A'],p1:'ЗДАРОВАЯ',p2:'КРАІНА',lang:'be'},
  tr:{c:['#E30A17','#FFFFFF','#E30A17'],p1:'SAĞLIKLI',p2:'ÜLKE',lang:'tr'},
  kz:{c:['#00AFCA','#FFEC00','#00AFCA'],p1:'САУАТТЫ',p2:'ЕЛ',lang:'kk'},
  ge:{c:['#FFFFFF','#FF0000','#FFFFFF'],p1:'ᲯᲐᲜᲛᲠᲗᲔᲚᲘ',p2:'ᲥᲕᲔᲧᲐᲜᲐ',lang:'ka'},
  am:{c:['#D90012','#0033A0','#F2A800'],p1:'ԱՌՈՂՋ',p2:'ԵՐԿԻՐ',lang:'hy'},
  uz:{c:['#1EB53A','#FFFFFF','#CE1126'],p1:'SOGLOM',p2:'MAMLAKAT',lang:'uz'},
};

let tkSundukFlagPasted = false;
function tkSundukFlagFocus(){ document.getElementById('tk-sunduk-flag-clip').select(); }

document.addEventListener('paste', function(e){
  const active = document.activeElement;
  if(!active || active.id !== 'tk-sunduk-flag-clip') return;
  const items = [...(e.clipboardData||{}).items||[]];
  const img = items.find(i=>i.type.startsWith('image/'));
  if(!img) return;
  e.preventDefault();
  const reader = new FileReader();
  reader.onload = ev => {
    document.getElementById('tk-sunduk-flag-img').src = ev.target.result;
    document.getElementById('tk-sunduk-flag-preview-img').style.display = 'block';
    document.getElementById('tk-sunduk-flag-clip').value = '[фото вставлено]';
    document.getElementById('tk-sunduk-flag-clip').dataset.imgData = ev.target.result;
    tkSundukFlagPasted = true;
  };
  reader.readAsDataURL(img.getAsFile());
}, true);

document.getElementById('tk-sunduk-ch-photo').addEventListener('change', function(){
  document.getElementById('tk-sunduk-photo-field').style.display = this.checked ? 'block' : 'none';
});

const TK_SUNDUK_TEMPLATES = {
  diabetes: `Искрени поздравления! Вие сте един от късметлиите, които могат да получат до 50% отстъпка за натуралното средство срещу диабет! 🔥 Кликнете върху аптечната чанта и се възползвайте от своя шанс:`,
  joints: `Искрени поздравления! Вие сте един от късметлиите, които могат да получат до 50% отстъпка за натуралното средство за здрави стави! 🔥 Кликнете върху аптечната чанта и се възползвайте от своя шанс:`,
  potency: `Искрени поздравления! Вие сте един от късметлиите, които могат да получат до 50% отстъпка за натуралното средство за мъжка сила и увереност! 🔥 Кликнете върху аптечната чанта и се възползвайте от своя шанс:`,
  pressure: `Искрени поздравления! Вие сте един от късметлиите, които могат да получат до 50% отстъпка за натуралното средство за нормализиране на кръвното налягане! 🔥 Кликнете върху аптечната чанта и се възползвайте от своя шанс:`,
  varicose: `Искрени поздравления! Вие сте един от късметлиите, които могат да получат до 50% отстъпка за натуралното средство срещу разширени вени! 🔥 Кликнете върху аптечната чанта и се възползвайте от своя шанс:`,
  hearing: `Искрени поздравления! Вие сте един от късметлиите, които могат да получат до 50% отстъпка за натуралното средство за подобряване на слуха! 🔥 Кликнете върху аптечната чанта и се възползвайте от своя шанс:`,
  vision: `Искрени поздравления! Вие сте един от късметлиите, които могат да получат до 50% отстъпка за натуралното средство за подобряване на зрението! 🔥 Кликнете върху аптечната чанта и се възползвайте от своя шанс:`,
  weight: `Искрени поздравления! Вие сте един от късметлиите, които могат да получат до 50% отстъпка за натуралното средство за отслабване! 🔥 Кликнете върху аптечната чанта и се възползвайте от своя шанс:`,
  parasites: `Искрени поздравления! Вие сте един от късметлиите, които могат да получат до 50% отстъпка за натуралното средство срещу паразити! 🔥 Кликнете върху аптечната чанта и се възползвайте от своя шанс:`,
  fungus: `Искрени поздравления! Вие сте един от късметлиите, които могат да получат до 50% отстъпка за натуралното средство срещу гъбички! 🔥 Кликнете върху аптечната чанта и се възползвайте от своя шанс:`,
  prostate: `Искрени поздравления! Вие сте един от късметлиите, които могат да получат до 50% отстъпка за натуралното средство срещу простатит! 🔥 Кликнете върху аптечната чанта и се възползвайте от своя шанс:`,
};
function tkSundukCat(cat, btn){
  document.querySelectorAll('.tk-scat').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  document.getElementById('tk-sunduk-old-text').value = TK_SUNDUK_TEMPLATES[cat]||'';
}
async function tkSundukTranslate(){
  const text = document.getElementById('tk-sunduk-old-text').value.trim();
  if(!text){ alert('Вставь оригинальный текст!'); return; }
  const geo = tkGeoCode;
  const fd = TK_FLAG_DATA[geo];
  if(!fd){ alert('Выбери страну в шаге 1!'); return; }
  const lang = fd.lang;
  const btn = event.target;
  btn.textContent = '⏳ Переводим...'; btn.disabled = true;
  try {
    const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=${lang}&dt=t&q=${encodeURIComponent(text)}`;
    const r = await fetch(url);
    const data = await r.json();
    const translated = data[0].map(s=>s[0]).join('');
    document.getElementById('tk-sunduk-new-text').value = translated;
    btn.textContent = '✅ Переведено!';
    setTimeout(()=>{ btn.textContent='🌐 Перевести на язык выбранной страны'; btn.disabled=false; }, 2000);
  } catch(err){
    btn.textContent = '❌ Ошибка — попробуй вручную';
    setTimeout(()=>{ btn.textContent='🌐 Перевести на язык выбранной страны'; btn.disabled=false; }, 2000);
  }
}

function tkGenFlagLogo(){
  const geo = tkGeoCode;
  const fd = TK_FLAG_DATA[geo];
  if(!fd){ alert('Выбери страну в шаге 1!'); return; }
  const [c1,c2,c3] = fd.c;
  const p1 = fd.p1, p2 = fd.p2;
  const svg = `<svg viewBox="0 0 320 138" xmlns="http://www.w3.org/2000/svg" width="320" height="138">
  <defs>
    <filter id="sh"><feDropShadow dx="2" dy="2" stdDeviation="3" flood-color="rgba(180,0,0,0.35)"/></filter>
    <clipPath id="hc">
      <path d="M72,105 C30,75 10,55 10,38 C10,22 22,12 36,12 C48,12 60,20 72,32 C84,20 96,12 108,12 C122,12 134,22 134,38 C134,55 114,75 72,105Z"/>
    </clipPath>
  </defs>
  <rect x="2" y="2" width="316" height="134" rx="22" fill="white" stroke="#CC0000" stroke-width="3.5" filter="url(#sh)"/>
  <rect x="10" y="12" width="124" height="31" fill="${c1}" clip-path="url(#hc)"/>
  <rect x="10" y="43" width="124" height="32" fill="${c2}" clip-path="url(#hc)"/>
  <rect x="10" y="75" width="124" height="32" fill="${c3}" clip-path="url(#hc)"/>
  <path d="M72,105 C30,75 10,55 10,38 C10,22 22,12 36,12 C48,12 60,20 72,32 C84,20 96,12 108,12 C122,12 134,22 134,38 C134,55 114,75 72,105Z" fill="none" stroke="white" stroke-width="3"/>
  <text x="152" y="70" font-family="Arial Black,Impact,sans-serif" font-size="28" font-weight="900" fill="#CC0000" stroke="white" stroke-width="3" paint-order="stroke">${p1}</text>
  <text x="152" y="106" font-family="Arial Black,Impact,sans-serif" font-size="28" font-weight="900" fill="#006400" stroke="white" stroke-width="3" paint-order="stroke">${p2}</text>
</svg>`;
  const wrap = document.getElementById('tk-sunduk-logo-wrap');
  const svgEl = document.getElementById('tk-sunduk-logo-svg');
  svgEl.innerHTML = svg;
  wrap.style.display = 'block';
  const blob = new Blob([svg],{type:'image/svg+xml'});
  const burl = URL.createObjectURL(blob);
  const dl = document.getElementById('tk-sunduk-logo-dl');
  dl.href = burl;
  dl.download = `logo-${geo}.svg`;
}

async function tkCopySvgAsPng(){
  const svgEl = document.getElementById('tk-sunduk-logo-svg').querySelector('svg');
  if(!svgEl) return;
  const svgStr = new XMLSerializer().serializeToString(svgEl);
  const blob = new Blob([svgStr],{type:'image/svg+xml'});
  const url = URL.createObjectURL(blob);
  const img = new Image();
  img.onload = async ()=>{
    const canvas = document.createElement('canvas');
    canvas.width = 640; canvas.height = 276;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0, 640, 276);
    canvas.toBlob(async b=>{
      try{
        await navigator.clipboard.write([new ClipboardItem({'image/png':b})]);
        const btn = event.target;
        const orig = btn.textContent;
        btn.textContent = '✅ Скопировано!';
        setTimeout(()=>btn.textContent=orig, 2000);
      }catch(e){ alert('Не удалось скопировать — скачай SVG'); }
    },'image/png');
  };
  img.src = url;
}

function tkToggleSunduk(){
  tkSundukOn = !tkSundukOn;
  const badge = document.getElementById('tk-sunduk-badge');
  const fields = document.getElementById('tk-sunduk-fields');
  const toggle = document.getElementById('tk-sunduk-toggle');
  if(tkSundukOn){
    badge.textContent='ДА'; badge.style.background='#5b21b6'; badge.style.color='#e9d5ff'; badge.style.borderColor='#a78bfa';
    toggle.style.borderColor='#a78bfa'; toggle.style.background='linear-gradient(135deg,#2e1065,#4c1d95)';
    fields.style.display='flex';
  } else {
    badge.textContent='НЕТ'; badge.style.background='#3b1d6e'; badge.style.color='#a78bfa'; badge.style.borderColor='#7c3aed';
    toggle.style.borderColor='#7c3aed'; toggle.style.background='linear-gradient(135deg,#1a0a2e,#2d1060)';
    fields.style.display='none';
  }
}
function tkNext(step){
  document.getElementById('tk-step-'+step).classList.remove('active');
  const next=step+1;
  document.getElementById('tk-step-'+next).classList.add('active');
  tkCurrentStep=next;
  tkUpdateProgress();
  if(next===3) tkUpdateUrlPreview();
  if(next===4) tkGenerate();
}

function tkBack(step){
  document.getElementById('tk-step-'+step).classList.remove('active');
  const prev=step-1;
  document.getElementById('tk-step-'+prev).classList.add('active');
  tkCurrentStep=prev;
  tkUpdateProgress();
}

function tkUpdateProgress(){
  document.querySelectorAll('.tk-progress-dot').forEach((d,i)=>{
    d.className='tk-progress-dot'+(i+1<tkCurrentStep?' done':i+1===tkCurrentStep?' active':'');
  });
}

function tkGenerate(){
  tkSaveOffer();
  tkCurrentTaskData = null;
  const offerUrl=document.getElementById('tk-offer-url').value.trim();
  const offerFull=document.getElementById('tk-offer-name-full').value.trim();
  const geoName=tkGeoName||document.getElementById('tk-geo-name').value.trim();
  const offerId=document.getElementById('tk-offer-id').value.trim();
  const streamId=document.getElementById('tk-stream-id').value.trim();
  const apiToken=document.getElementById('tk-api-token').value.trim();
  const name=document.getElementById('tk-offer-name-short').value.trim();
  const marker=document.getElementById('tk-url-marker').value.trim()||'po';
  const geo=tkGeoCode||'geo';
  const num=document.getElementById('tk-url-num').value.trim()||'1';
  const finalUrl=`https://gvita.beauty/landers/official-${name}-${marker}-${geo}-lend${num}/`;
  const proklaType=document.querySelector('input[name="tk-prokla-type"]:checked').value;
  const copyUrl=document.getElementById('tk-copy-url').value.trim();

  // Title
  const typeLabel=proklaType==='download'?'Скачать проклу и внести правки':'Скопировать проклу и внести правки';
  let lines=[`${typeLabel}${offerFull?' '+offerFull:''}`, ''];

  if(offerUrl) lines.push(offerUrl,'');
  if(geoName) lines.push(`Гео: ${geoName}`);
  if(offerFull) lines.push(`Офер: ${offerFull}`);
  if(offerId) lines.push(`ID: ${offerId}`);
  if(streamId) lines.push(`id потока: ${streamId}`);
  if(apiToken) lines.push(`API токен: ${apiToken}`);
  lines.push('','ПРОКЛА','');
  if(proklaType==='download'){
    lines.push('1)Выкачать проклу (ниже добавил)');
  } else {
    lines.push(`1)Скопировать проклу: ${copyUrl||'[ссылка на проклу]'}`);
  }
  lines.push('1. Залить на домен gvita.beauty');
  lines.push('2. Удалить все редиректы и бекбаттоны');
  lines.push('3. Заменить ID , ID потоку , и api токен');
  lines.push('4. Все пути должны быть исключительно относительными!');
  lines.push('5. На прокле сделать камбекер');

  let idx=6;
  if(document.getElementById('tk-ch-name').checked){
    const oldN=document.getElementById('tk-old-name').value.trim();
    const newN=document.getElementById('tk-new-name-field').value.trim()||name;
    if(oldN&&newN) lines.push(`${idx++}. заменить название офера ${oldN} на ${newN}`);
  }
  if(document.getElementById('tk-ch-photo').checked){
    const inp=document.getElementById('tk-photo-clip');
    const clip=inp.value.trim();
    const hasImg=inp.dataset.imgData;
    if(hasImg){ lines.push(`${idx++}. заменить фото товара (фото прикреплено)`); }
    else if(clip){ lines.push(`${idx++}. заменить фото товара на ${clip}`); }
  }
  if(document.getElementById('tk-ch-price').checked){
    const np=document.getElementById('tk-new-price').value.trim();
    const op=document.getElementById('tk-old-price').value.trim();
    const disc=document.getElementById('tk-discount').value.trim();
    const changeCur=document.getElementById('tk-ch-currency').checked;
    const cur=document.getElementById('tk-currency').value||'EUR';
    if(np){
      lines.push(`${idx++}) старая цена ${op} ${cur}\nНовая цена ${np} ${cur}\nСкидка ${disc}`);
      if(changeCur) lines.push(`   (изменить валюту на ${cur})`);
    }
  }
  if(document.getElementById('tk-ch-mask').checked){
    const mask=document.getElementById('tk-mask').value.trim();
    if(mask) lines.push(`${idx++}. поставить маску на номер ${mask}`);
  }
  if(document.getElementById('tk-ch-cert').checked){
    const cert=document.getElementById('tk-cert-file').value.trim();
    lines.push(`${idx++}. заменить сертификат${cert?' на '+cert:' (файл прикреплён)'}`);
  }
  if(document.getElementById('tk-ch-comments').checked){
    const action=document.querySelector('input[name="tk-comment-action"]:checked').value;
    if(action==='delete'){
      lines.push(`${idx++}. удалить все фото с комментов`);
    } else if(action==='upload'){
      const clips=document.getElementById('tk-comment-clips').value.trim();
      lines.push(`${idx++}. загрузить фото в коменты с новым офером${clips?': '+clips:' (файлы прикреплены)'}`);
    }
    // 'keep' — ничего не добавляем в таску
  }

  lines.push('','назвать как:');
  lines.push(finalUrl);

  // Build rich HTML output
  const cur = document.getElementById('tk-currency').value || 'EUR';
  let html = '';

  // Title
  html += `<div style="font-size:15px;font-weight:800;color:var(--text);margin-bottom:16px;padding-bottom:10px;border-bottom:2px solid var(--accent1);">${lines[0]}</div>`;

  // Offer info block
  html += `<div style="background:var(--surface);border:1.5px solid var(--border);border-radius:10px;padding:12px 16px;margin-bottom:14px;line-height:2;">`;
  if(offerUrl) html += `<div style="color:var(--accent1);font-size:12px;">${offerUrl}</div>`;
  if(geoName) html += `<div><span style="color:var(--text3);">Гео:</span> <b>${geoName}</b></div>`;
  if(offerFull) html += `<div><span style="color:var(--text3);">Офер:</span> <b>${offerFull}</b></div>`;
  if(offerId) html += `<div><span style="color:var(--text3);">ID:</span> <b>${offerId}</b></div>`;
  if(streamId) html += `<div><span style="color:var(--text3);">id потока:</span> <b>${streamId}</b></div>`;
  if(apiToken) html += `<div><span style="color:var(--text3);">API токен:</span> <b>${apiToken}</b></div>`;
  html += `</div>`;

  // Prokla section
  html += `<div style="font-size:12px;font-weight:800;color:var(--text3);text-transform:uppercase;letter-spacing:.07em;margin-bottom:10px;">ПРОКЛА</div>`;
  html += `<div style="line-height:2.1;margin-bottom:14px;">`;

  // Fixed items
  const proklaType2 = document.querySelector('input[name="tk-prokla-type"]:checked').value;
  const copyUrl2 = document.getElementById('tk-copy-url').value.trim();
  if(proklaType2==='download'){
    html += `<div>1) Выкачать проклу <span style="color:var(--text3);">(ниже добавил)</span></div>`;
  } else {
    html += `<div>1) Скопировать проклу: <b style="color:var(--accent1);">${copyUrl2||'[ссылка]'}</b></div>`;
  }
  html += `<div>1. Залить на домен <b>gvita.beauty</b></div>`;
  html += `<div>2. Удалить все редиректы и бекбаттоны</div>`;
  html += `<div>3. Заменить ID , ID потоку , и api токен</div>`;
  html += `<div>4. Все пути должны быть исключительно относительными!</div>`;
  html += `<div>5. На прокле сделать камбекер</div>`;

  // Variable items
  let vidx = 6;
  if(document.getElementById('tk-ch-name').checked){
    const oldN=document.getElementById('tk-old-name').value.trim();
    const newN=document.getElementById('tk-new-name-field').value.trim()||name;
    if(oldN&&newN) html += `<div>${vidx++}. заменить название офера <b>${oldN}</b> на <b>${newN}</b></div>`;
  }
  if(document.getElementById('tk-ch-photo').checked){
    const inp=document.getElementById('tk-photo-clip');
    const clip=inp.value.trim();
    const hasImg=inp.dataset.imgData;
    if(hasImg){
      html += `<div>${vidx++}. заменить фото товара <span class="tk-highlight">( фото прикреплено )</span></div>`;
    } else if(clip){
      html += `<div>${vidx++}. заменить фото товара на <b style="color:var(--accent1);">${clip}</b></div>`;
    }
  }
  if(document.getElementById('tk-ch-price').checked){
    const np=document.getElementById('tk-new-price').value.trim();
    const op=document.getElementById('tk-old-price').value.trim();
    const disc=document.getElementById('tk-discount').value.trim();
    const changeCur=document.getElementById('tk-ch-currency').checked;
    const curVal=document.getElementById('tk-currency').value||'EUR';
    if(np){
      html += `<div style="margin:4px 0;">${vidx++}) <span style="color:var(--text3);">старая цена</span> <b>${op} ${curVal}</b> &nbsp;→&nbsp; <span style="color:var(--accent3);font-weight:800;">Новая цена ${np} ${curVal}</span> &nbsp;·&nbsp; Скидка <b>${disc}</b>${changeCur?` &nbsp;·&nbsp; <span style="color:var(--accent4);">изменить валюту на ${curVal}</span>`:''}</div>`;
    }
  }
  if(document.getElementById('tk-ch-mask').checked){
    const mask=document.getElementById('tk-mask').value.trim();
    if(mask) html += `<div>${vidx++}. поставить маску на номер <b>${mask}</b></div>`;
  }
  if(document.getElementById('tk-ch-cert').checked){
    const certInp=document.getElementById('tk-cert-file');
    const cert=certInp.value.trim();
    if(certInp.dataset.imgData){
      html += `<div>${vidx++}. заменить сертификат <span class="tk-highlight">( файл прикреплён )</span></div>`;
    } else {
      html += `<div>${vidx++}. заменить сертификат${cert?' на <b>'+cert+'</b>':''}</div>`;
    }
  }
  if(document.getElementById('tk-ch-comments').checked){
    const action=document.querySelector('input[name="tk-comment-action"]:checked').value;
    if(action==='delete'){
      html += `<div>${vidx++}. удалить все фото с комментов</div>`;
    } else if(action==='upload'){
      const clips=document.getElementById('tk-comment-clips').value.trim();
      html += `<div>${vidx++}. загрузить фото в коменты с новым офером ${clips?'<b>'+clips+'</b>':'<span class="tk-highlight">( файлы прикреплены )</span>'}</div>`;
    }
  }
  html += `</div>`;

  // URL
  html += `<div style="padding:12px 16px;background:var(--surface2);border-radius:10px;border-left:3px solid var(--accent1);">`;
  html += `<div style="font-size:11px;color:var(--text3);font-weight:700;margin-bottom:4px;">НАЗВАТЬ КАК:</div>`;
  html += `<div style="color:var(--accent1);font-weight:700;word-break:break-all;">${finalUrl}</div>`;
  html += `</div>`;

  // SUNDUK section
  const sundukOldText = document.getElementById('tk-sunduk-old-text').value.trim();
  const sundukNewText = document.getElementById('tk-sunduk-new-text').value.trim();
  const sundukSrcUrl = document.getElementById('tk-sunduk-src-url').value.trim();
  const sundukReplacePhoto = document.getElementById('tk-sunduk-ch-photo').checked;
  const sundukFlagClip = document.getElementById('tk-sunduk-flag-clip');
  const sundukFlagVal = sundukFlagClip.value.trim();
  const sundukFlagHasImg = !!sundukFlagClip.dataset.imgData;
  const sundukUrl = `https://gvita.beauty/landers/official-${name}-backbutton-${marker}-${geo}-sunduk/`;
  if(tkSundukOn){
    html += `<div style="margin-top:20px;padding:16px;border-radius:14px;border:2px solid #7c3aed;background:#12082a;">`;
    html += `<div style="font-size:13px;font-weight:800;color:#c4b5fd;text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px;">🎁 СУНДУК / БЕК-БАТОН</div>`;
    html += `<div style="font-size:13px;line-height:1.8;color:var(--text);">`;
    if(sundukSrcUrl){
      html += `<b>Скопировать сундук:</b> <span style="color:#a78bfa;">${sundukSrcUrl}</span><br><br>`;
    } else {
      html += `<b>Скопировать сундук и внести правки:</b><br>`;
    }
    let pIdx = 1;
    // Flag
    html += `${pIdx++}) заменить флаг страны (картинка вверху)`;
    if(sundukFlagVal && sundukFlagVal !== '[фото вставлено]') html += ` → <b>${sundukFlagVal}</b>`;
    else if(sundukFlagHasImg) html += ` <span class="tk-highlight">(фото флага прикреплено)</span>`;
    html += `<br>`;
    // Photo of product
    if(sundukReplacePhoto){
      const photoInput = document.getElementById('tk-photo-clip');
      html += `${pIdx++}) заменить фото товара`;
      if(photoInput && photoInput.value && photoInput.value!=='[фото вставлено]') html += ` → <b>${photoInput.value}</b>`;
      else if(photoInput && photoInput.dataset.imgData) html += ` <span class="tk-highlight">(фото прикреплено)</span>`;
      html += `<br>`;
    }
    // Text replacement
    if(sundukOldText && sundukNewText){
      html += `${pIdx++}) заменить текст:<br><span style="color:var(--text3);font-style:italic;">${sundukOldText.replace(/\n/g,'<br>')}</span><br><b>на:</b><br><span style="color:#c4b5fd;">${sundukNewText.replace(/\n/g,'<br>')}</span><br>`;
    }
    html += `</div>`;
    html += `<div style="margin-top:12px;padding:10px 14px;background:#1e0b3a;border-radius:10px;border-left:3px solid #7c3aed;">`;
    html += `<div style="font-size:11px;color:#a78bfa;font-weight:700;margin-bottom:4px;">НАЗВАТЬ КАК:</div>`;
    html += `<div style="color:#c4b5fd;font-weight:700;word-break:break-all;">${sundukUrl}</div>`;
    html += `</div></div>`;
  }

  document.getElementById('tk-result-text').innerHTML = html;

  // Save task data for later
  const geoEntry = TK_COUNTRIES.find(c=>c.c===tkGeoCode);
  tkCurrentTaskData = {
    offerUrl, offerFull, offerShort: name, geoName, geoCode: tkGeoCode,
    geoFlag: geoEntry?geoEntry.flag:'', geoCur: document.getElementById('tk-currency').value,
    offerId, streamId, apiToken, marker, num, finalUrl,
    proklaType, copyUrl,
    newPrice: document.getElementById('tk-new-price').value,
    oldPrice: document.getElementById('tk-old-price').value,
    sunduk: tkSundukOn, sundukOldText, sundukNewText, sundukUrl, sundukSrcUrl,
    sundukReplacePhoto, sundukFlagImg: sundukFlagClip.dataset.imgData||'', sundukFlagVal,
  };
  const saveBtn = document.querySelector('[onclick="tkSaveTask()"]');
  saveBtn.textContent = '💾 Сохранить'; saveBtn.disabled = false; saveBtn.style.opacity = '';

  // Show attached photos
  const photosWrap=document.getElementById('tk-result-photos');
  const photosInner=document.getElementById('tk-result-photos-inner');
  photosInner.innerHTML='';
  let hasPhotos=false;
  function addPhotoResult(inp, label){
    if(inp&&inp.dataset.imgData){
      hasPhotos=true;
      const d=document.createElement('div');
      d.style.cssText='text-align:center;';
      d.innerHTML=`<img src="${inp.dataset.imgData}" style="max-width:150px;max-height:150px;border-radius:8px;border:2px solid var(--accent1);display:block;cursor:pointer;" title="Кликни правой кнопкой → Копировать изображение">
        <div style="font-size:10px;color:var(--text3);margin-top:4px;">${label}</div>`;
      photosInner.appendChild(d);
    }
  }
  addPhotoResult(document.getElementById('tk-photo-clip'), 'Фото товара');
  addPhotoResult(document.getElementById('tk-cert-file'), 'Сертификат');
  if(tkSundukOn) addPhotoResult(document.getElementById('tk-sunduk-flag-clip'), 'Флаг сундука');
  photosWrap.style.display=hasPhotos?'block':'none';
}

function tkCopy(){
  // Get plain text — strip HTML tags
  const el=document.getElementById('tk-result-text');
  const text=el.innerText.replace(/ {2,}/g,' ').trim();
  navigator.clipboard.writeText(text).then(()=>{
    const btn=document.querySelector('.tk-copy-btn');
    btn.textContent='✅ Скопировано!';
    setTimeout(()=>btn.textContent='📋 Скопировать таску',2000);
  });
}

// ===== SAVED TASKS =====
let tkCurrentTaskData = null;

function tkThumbFromInput(inp){
  if(!inp||!inp.dataset.imgData) return null;
  try {
    const img = new Image();
    img.src = inp.dataset.imgData;
    const canvas = document.createElement('canvas');
    canvas.width=80; canvas.height=80;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img,0,0,80,80);
    return canvas.toDataURL('image/jpeg',0.6);
  } catch(e){ return inp.dataset.imgData; }
}

function tkSaveTask(){
  if(!tkCurrentTaskData) return;
  const btn = document.querySelector('[onclick="tkSaveTask()"]');
  if(btn && btn.disabled) return;
  // Attach thumbnail from photo field
  const photoInp = document.getElementById('tk-photo-clip');
  if(photoInp && photoInp.dataset.imgData){
    tkCurrentTaskData.thumb = tkThumbFromInput(photoInp) || photoInp.dataset.imgData;
  }
  const tasks = JSON.parse(localStorage.getItem('tk_saved_tasks')||'[]');
  tkCurrentTaskData.savedAt = new Date().toLocaleString('ru');
  tkCurrentTaskData.id = Date.now();
  tasks.unshift(tkCurrentTaskData);
  localStorage.setItem('tk_saved_tasks', JSON.stringify(tasks.slice(0,50)));
  tkRenderSaved();
  if(btn){ btn.textContent='✅ Сохранено!'; btn.disabled=true; btn.style.opacity='0.5'; }
}

let tkFilterGeo = '';
function tkSetFilterGeo(code){
  tkFilterGeo = tkFilterGeo===code ? '' : code;
  tkRenderSaved();
}
function tkRenderSaved(){
  const q = (document.getElementById('tk-saved-search')||{}).value||'';
  const allTasks = JSON.parse(localStorage.getItem('tk_saved_tasks')||'[]');
  // Build country filter buttons
  const fcEl = document.getElementById('tk-filter-countries');
  if(fcEl){
    const geos = [...new Map(allTasks.filter(t=>t.geoCode).map(t=>[t.geoCode,{code:t.geoCode,name:t.geoName||t.geoCode,flag:t.geoFlag||''}])).values()];
    fcEl.innerHTML = geos.map(g=>`<button onclick="tkSetFilterGeo('${g.code}')" style="border:1.5px solid ${tkFilterGeo===g.code?'var(--accent1)':'var(--border)'};background:${tkFilterGeo===g.code?'var(--accent1)':'var(--surface)'};color:${tkFilterGeo===g.code?'#fff':'var(--text1)'};border-radius:20px;padding:4px 12px;font-size:12px;font-weight:600;cursor:pointer;">${g.flag} ${g.name}</button>`).join('');
  }
  let tasks = allTasks;
  if(q) tasks = tasks.filter(t=>(t.offerFull||'').toLowerCase().includes(q.toLowerCase())||(t.geoName||'').toLowerCase().includes(q.toLowerCase())||(t.geoCode||'').toLowerCase().includes(q.toLowerCase()));
  if(tkFilterGeo) tasks = tasks.filter(t=>t.geoCode===tkFilterGeo);
  const list = document.getElementById('tk-saved-list');
  const header = document.getElementById('tk-saved-header');
  header.style.display = allTasks.length ? 'block' : 'none';
  if(!tasks.length){ list.innerHTML='<div style="color:var(--text3);font-size:13px;padding:10px 0;">Ничего не найдено</div>'; return; }

  // Group by offerShort
  const groups = {};
  tasks.forEach(t=>{
    const key = t.offerShort||t.offerFull||'Без названия';
    if(!groups[key]) groups[key]={tasks:[],flag:t.geoFlag||'',geo:t.geoName||''};
    groups[key].tasks.push(t);
  });

  list.innerHTML = Object.entries(groups).map(([name,g])=>{
    const lastTask = g.tasks[g.tasks.length-1];
    const sundukTask = g.tasks.find(t=>t.sunduk);
    const sid = sundukTask ? 'sd-'+sundukTask.id : '';
    const count = g.tasks.length;
    return `
    <div class="tk-saved-group">
      <div class="tk-saved-group-hdr">
        <div class="tk-ghdr-left">
          <span style="font-size:22px;">${g.flag||'📦'}</span>
          <div>
            <div>${name}</div>
            <div class="tk-ghdr-geo">${g.geo} &nbsp;·&nbsp; ${count} прокл${count===1?'а':count<5?'ы':''}</div>
          </div>
        </div>
        <div class="tk-ghdr-right">
          <button class="tk-ghdr-btn split" onclick="tkSplitFrom(${lastTask.id})">➕ В сплит</button>
          <button class="tk-ghdr-btn sunduk" onclick="tkNewSunduk(${lastTask.id})">🎁 Сундук</button>
        </div>
      </div>
      ${g.tasks.sort((a,b)=>(parseInt(a.num)||1)-(parseInt(b.num)||1)).map((t,i)=>`
        <div class="tk-saved-card" id="tk-card-${t.id}">
          <div class="tk-saved-card-inner">
            ${t.thumb?`<img class="tk-saved-thumb" src="${t.thumb}">`:`<div class="tk-saved-thumb-ph">📦</div>`}
            <div style="flex:1;min-width:0;">
              <div class="tk-saved-title">
                <span class="tk-saved-num">Прокла ${t.num||'1'}</span>${t.offerFull||name}
              </div>
              <div class="tk-saved-meta">
                <span class="tk-saved-meta-flag">${t.geoFlag||''}</span>
                <span>${t.geoName||''}</span>
                <span style="opacity:.5;">·</span>
                <span>${t.savedAt||''}</span>
              </div>
              <div class="tk-saved-btns">
                <button class="tk-saved-btn" onclick="tkToggleBinom(${t.id})">📊 Бином</button>
                <button class="tk-saved-btn tk-saved-btn-del" onclick="tkDeleteTask(${t.id})" style="color:#ef4444;border-color:#fca5a5;">✕ Удалить</button>
              </div>
            </div>
          </div>
          <div class="tk-binom-panel" id="tk-binom-${t.id}">
            <div style="font-size:11px;font-weight:800;color:var(--accent1);text-transform:uppercase;margin-bottom:10px;letter-spacing:.06em;">📊 Поля для Бинома</div>
            ${tkBinomRows(t)}
          </div>
        </div>
      `).join('')}
      ${sundukTask ? `<div class="tk-saved-card" style="border-left-color:#8b5cf6;background:linear-gradient(135deg,#13072a 0%,#1a0b38 100%);" id="tk-card-${sid}">
          <div class="tk-saved-card-inner">
            <div class="tk-saved-thumb-ph" style="background:#2e1065;color:#c4b5fd;border-color:#5b21b6;font-size:30px;">🎁</div>
            <div style="flex:1;min-width:0;">
              <div class="tk-saved-title" style="color:#e9d5ff;">
                <span style="display:inline-block;background:#3b0764;color:#c4b5fd;border-radius:6px;padding:1px 8px;font-size:12px;font-weight:800;margin-right:6px;">Сундук</span>${sundukTask.offerFull||name}
              </div>
              <div class="tk-saved-meta" style="color:#a78bfa;">
                <span class="tk-saved-meta-flag">${sundukTask.geoFlag||''}</span>
                <span>${sundukTask.geoName||''}</span>
                <span style="opacity:.5;">·</span>
                <span>${sundukTask.savedAt||''}</span>
              </div>
              <div class="tk-saved-btns">
                <button class="tk-saved-btn" onclick="tkSplitFrom(${sundukTask.id})" style="border-color:#7c3aed;color:#c4b5fd;background:#1e0b3a;">🔄 Открыть</button>
                <button class="tk-saved-btn" onclick="tkToggleBinom('${sid}')" style="border-color:#7c3aed;color:#c4b5fd;background:#1e0b3a;">📊 Бином</button>
                <button class="tk-saved-btn tk-saved-btn-del" onclick="tkDeleteTask(${sundukTask.id})" style="color:#ef4444;border-color:#7f1d1d;">✕ Удалить</button>
              </div>
            </div>
          </div>
          <div class="tk-binom-panel" id="tk-binom-${sid}" style="background:#1e0b3a;border-color:#5b21b6;">
            <div style="font-size:11px;font-weight:800;color:#a78bfa;text-transform:uppercase;margin-bottom:10px;letter-spacing:.06em;">🎁 Бином — Сундук</div>
            ${tkBinomRows(sundukTask)}
          </div>
        </div>` : ''}
    </div>`;
  }).join('');
}

function tkBinomRows(t){
  const short = t.offerShort || '';
  const marker = t.marker || 'po';
  const geo = t.geoCode || '';
  const num = t.num || '1';
  const offerName = `${short}_prokla${num}_${geo}_${marker}`;
  const offerUrl = `https://gvita.beauty/landers/official-${short}-${marker}-${geo}-lend${num}/?clickid={clickid}`;
  const campaignName = `${short}_${geo.toUpperCase()}`;
  const fields = [
    {label:'Offer Name', val: offerName},
    {label:'Offer URL', val: offerUrl},
    {label:'Campaign Name', val: campaignName},
  ];
  let html = fields.map(f=>`
    <div class="tk-binom-row">
      <div class="tk-binom-label">${f.label}</div>
      <div class="tk-binom-val" title="Кликни чтобы скопировать" onclick="tkCopyText('${f.val.replace(/'/g,"\\'")}',this)">${f.val}</div>
      <button class="tk-binom-copy" onclick="tkCopyText('${f.val.replace(/'/g,"\\'")}',this)">Копировать</button>
    </div>
  `).join('');
  if(t.sunduk){
    const sundukName = `${short}_sunduk_${geo}`;
    const sundukUrl = `https://gvita.beauty/landers/official-${short}-${marker}-${geo}-sunduk/?clickid={clickid}`;
    html += `<div style="font-size:11px;font-weight:800;color:#a78bfa;text-transform:uppercase;margin:10px 0 6px;border-top:1px solid #3b1d6e;padding-top:8px;">🎁 Сундук</div>`;
    [{label:'Offer Name', val:sundukName},{label:'Offer URL', val:sundukUrl}].forEach(f=>{
      html += `<div class="tk-binom-row"><div class="tk-binom-label">${f.label}</div><div class="tk-binom-val" onclick="tkCopyText('${f.val.replace(/'/g,"\\'")}',this)">${f.val}</div><button class="tk-binom-copy" onclick="tkCopyText('${f.val.replace(/'/g,"\\'")}',this)">Копировать</button></div>`;
    });
  }
  return html;
}

function tkToggleBinom(id){
  const panel = document.getElementById('tk-binom-'+id);
  panel.classList.toggle('open');
}

function tkCopyText(text, el){
  navigator.clipboard.writeText(text).then(()=>{
    const orig = el.textContent;
    el.textContent = '✅';
    setTimeout(()=>el.textContent=orig, 1500);
  });
}

function tkDeleteTask(id){
  let tasks = JSON.parse(localStorage.getItem('tk_saved_tasks')||'[]');
  tasks = tasks.filter(t=>t.id!==id);
  localStorage.setItem('tk_saved_tasks', JSON.stringify(tasks));
  tkRenderSaved();
}

function tkNewSunduk(id){
  // Open form with offer data, enable sunduk, skip to step 2
  tkSplitFrom(id);
  // Enable sunduk toggle if not already on
  if(!tkSundukOn) tkToggleSunduk();
  // Go to step 2 instead of step 1
  setTimeout(()=>{
    document.querySelectorAll('.tk-step').forEach(s=>s.classList.remove('active'));
    document.getElementById('tk-step-2').classList.add('active');
    tkCurrentStep=2; tkUpdateProgress();
    document.getElementById('tk-sunduk-fields').scrollIntoView({behavior:'smooth',block:'center'});
  }, 50);
}
function tkSplitFrom(id){
  const tasks = JSON.parse(localStorage.getItem('tk_saved_tasks')||'[]');
  const t = tasks.find(t=>t.id===id);
  if(!t) return;
  // Restore all fields
  document.getElementById('tk-offer-url').value = t.offerUrl||'';
  document.getElementById('tk-offer-name-full').value = t.offerFull||'';
  const shortEl = document.getElementById('tk-offer-name-short');
  shortEl.value = t.offerShort||'';
  shortEl.dataset.edited = '1';
  document.getElementById('tk-offer-id').value = t.offerId||'';
  document.getElementById('tk-stream-id').value = t.streamId||'';
  document.getElementById('tk-api-token').value = t.apiToken||'';
  document.getElementById('tk-url-marker').value = t.marker||'po';
  document.getElementById('tk-new-name-field').value = t.offerShort||'';
  if(t.newPrice) document.getElementById('tk-new-price').value = t.newPrice;
  if(t.oldPrice) document.getElementById('tk-old-price').value = t.oldPrice;
  if(t.proklaType){ const r=document.querySelector(`input[name="tk-prokla-type"][value="${t.proklaType}"]`); if(r){ r.checked=true; tkTypeChange(); } }
  if(t.copyUrl) document.getElementById('tk-copy-url').value = t.copyUrl;
  // Auto-increment: next lend number after max existing for this offer+geo
  const sameOffer = tasks.filter(x=>x.offerShort===t.offerShort && x.geoCode===t.geoCode);
  const maxNum = sameOffer.reduce((m,x)=>Math.max(m,parseInt(x.num)||1),0);
  document.getElementById('tk-url-num').value = maxNum+1;
  // Restore geo
  if(t.geoCode){ const ge=TK_COUNTRIES.find(c=>c.c===t.geoCode); tkPickGeo(t.geoName||'', t.geoCode, ge?ge.flag:'', t.geoCur||'EUR'); }
  tkUpdateUrlPreview();
  // Restore photo
  if(t.thumb){
    const inp=document.getElementById('tk-photo-clip');
    inp.dataset.imgData=t.thumb; inp.value='[фото вставлено]';
    document.getElementById('tk-photo-img').src=t.thumb;
    document.getElementById('tk-photo-preview').style.display='block';
  }
  // Restore sunduk
  if(t.sunduk !== undefined){
    if(t.sunduk !== tkSundukOn) tkToggleSunduk();
    if(t.sunduk){
      document.getElementById('tk-sunduk-old-text').value = t.sundukOldText||'';
      document.getElementById('tk-sunduk-new-text').value = t.sundukNewText||'';
      document.getElementById('tk-sunduk-src-url').value = t.sundukSrcUrl||'';
      const chPhoto = document.getElementById('tk-sunduk-ch-photo');
      chPhoto.checked = !!t.sundukReplacePhoto;
      document.getElementById('tk-sunduk-photo-field').style.display = chPhoto.checked?'block':'none';
      if(t.sundukFlagImg){
        document.getElementById('tk-sunduk-flag-clip').value = t.sundukFlagVal||'[фото вставлено]';
        document.getElementById('tk-sunduk-flag-clip').dataset.imgData = t.sundukFlagImg;
        document.getElementById('tk-sunduk-flag-img').src = t.sundukFlagImg;
        document.getElementById('tk-sunduk-flag-preview-img').style.display = 'block';
      }
    }
  }
  // Go to step 1
  document.querySelectorAll('.tk-step').forEach(s=>s.classList.remove('active'));
  document.getElementById('tk-step-1').classList.add('active');
  tkCurrentStep=1; tkUpdateProgress();
  document.getElementById('tk-wrap-top').scrollIntoView({behavior:'smooth'});
}

// Paste image support for photo fields
let tkPhotoPasted=false, tkCertPasted=false;
document.addEventListener('paste', function(e){
  const items=[...(e.clipboardData||e.originalEvent.clipboardData).items];
  const img=items.find(i=>i.type.startsWith('image/'));
  if(!img) return;
  const active=document.activeElement;
  let targetInput=null, previewId=null, imgId=null;
  if(active&&active.id==='tk-photo-clip'){ targetInput='tk-photo-clip'; previewId='tk-photo-preview'; imgId='tk-photo-img'; tkPhotoPasted=true; }
  else if(active&&active.id==='tk-cert-file'){ targetInput='tk-cert-file'; previewId='tk-cert-preview'; imgId='tk-cert-img'; tkCertPasted=true; }
  if(!targetInput) return;
  e.preventDefault();
  const reader=new FileReader();
  reader.onload=ev=>{
    document.getElementById(imgId).src=ev.target.result;
    document.getElementById(previewId).style.display='block';
    document.getElementById(targetInput).value='[фото вставлено]';
    document.getElementById(targetInput).dataset.imgData=ev.target.result;
  };
  reader.readAsDataURL(img.getAsFile());
});
let adsCat='',adsLang='';
function setCat(btn){
  document.querySelectorAll('#cat-grid .lang-btn').forEach(b=>{b.classList.remove('on');});
  btn.classList.add('on');
  adsCat=btn.dataset.cat || btn.textContent.replace(/^[^a-zA-Zа-яА-Я]+/,'').trim();
}
function setLang(btn){
  document.querySelectorAll('#lang-grid .lang-btn').forEach(b=>{b.classList.remove('on');});
  btn.classList.add('on');
  adsLang=btn.dataset.lang;
}
function copyText(text){
  navigator.clipboard.writeText(text);
}
async function generateAds(){
  if(!adsCat){alert('Выбери категорию!');return;}
  if(!adsLang){alert('Выбери язык!');return;}
  const btn=document.getElementById('ads-btn');
  btn.disabled=true;btn.textContent='⏳ Генерирую...';
  document.getElementById('ads-result').style.display='none';
  try{
    const resp=await fetch('/ai_generate',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({topic:'ADS:'+adsCat+'|'+adsLang})
    });
    const data=await resp.json();
    if(data.error){alert('Ошибка: '+data.error);btn.disabled=false;btn.textContent='✨ Сгенерировать 15 заголовков и описаний';return;}
    parseAds(data.text);
    document.getElementById('ads-result').style.display='block';
  }catch(e){alert('Ошибка: '+e.message);}
  btn.disabled=false;btn.textContent='✨ Сгенерировать 15 заголовков и описаний';
}
function parseAds(text){
  const lines=text.split('\n').map(l=>l.trim()).filter(l=>l);
  const titles=[],descs=[];
  let mode='';
  lines.forEach(l=>{
    if(l.match(/^#{0,2}\s*TITLES?:/i)||l.match(/^#{0,2}\s*ЗАГОЛОВКИ/i)){mode='t';return;}
    if(l.match(/^#{0,2}\s*DESCS?:/i)||l.match(/^#{0,2}\s*ОПИСАНИЯ/i)){mode='d';return;}
    const m=l.match(/^\d+[.)\s]+(.+?)\s*[-–]\s*(.+)$/);
    if(m){
      if(mode==='t') titles.push({orig:m[1].trim(),ru:m[2].trim()});
      else if(mode==='d') descs.push({orig:m[1].trim(),ru:m[2].trim()});
    }
  });
  const tt=document.getElementById('titles-table');
  tt.innerHTML='<tr><th>#</th><th>Заголовок</th><th>Перевод</th><th>Симв.</th><th></th></tr>';
  let titleNum=1;
  titles.forEach((t,i)=>{
    const len=t.orig.length;
    if(len>39){return;} // пропускаем если больше 39
    const color='color:green';
    tt.innerHTML+=`<tr><td>${titleNum++}</td><td>${t.orig}</td><td style="color:#888">${t.ru}</td><td style="${color}">${len}</td><td><button class="copy-btn" onclick="copyText('${t.orig.replace(/'/g,"\'")}')">📋</button></td></tr>`;
  });
  const dt=document.getElementById('descs-table');
  dt.innerHTML='<tr><th>#</th><th>Описание</th><th>Перевод</th><th>Симв.</th><th></th></tr>';
  let descNum=1;
  descs.forEach((d,i)=>{
    const len=d.orig.length;
    if(len>85){return;} // пропускаем если больше 85
    const color='color:green';
    dt.innerHTML+=`<tr><td>${descNum++}</td><td>${d.orig}</td><td style="color:#888">${d.ru}</td><td style="${color}">${len}</td><td><button class="copy-btn" onclick="copyText('${d.orig.replace(/'/g,"\'")}')">📋</button></td></tr>`;
  });
}
function setTopic(btn){
  document.querySelectorAll('[onclick="setTopic(this)"]').forEach(b=>{
    b.style.opacity='0.55';b.style.transform='scale(1)';
  });
  btn.style.opacity='1';btn.style.transform='scale(1.08)';
  document.getElementById('ai-topic').value=btn.textContent.replace(/^.\s/,'');
}
async function generateMeta(){
  const topic=document.getElementById('ai-topic').value.trim();
  if(!topic){alert('Введи тему!');return;}
  const btn=document.getElementById('ai-btn');
  btn.disabled=true;btn.textContent='Генерирую...';
  document.getElementById('ai-result').style.display='none';
  try{
    const resp=await fetch('/ai_generate',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({topic:topic})
    });
    const data=await resp.json();
    if(data.error){alert("Ошибка: "+data.error);btn.disabled=false;btn.textContent="Сгенерировать";return;}
    const text=data.text;
    const t=text.match(/TITLE:\s*(.+)/);
    const d=text.match(/DESCRIPTION:\s*([\s\S]+)/);
    if(t&&d){
      document.getElementById('ai-title-out').textContent=t[1].trim();
      document.getElementById('ai-desc-out').textContent=d[1].trim();
      document.getElementById('ai-result').style.display='block';
    } else { alert('Не удалось распарсить ответ: '+text); }
  }catch(e){alert('Ошибка: '+e.message);}
  btn.disabled=false;btn.textContent='Сгенерировать на английском';
}
function applyMeta(){
  const titleVal=document.getElementById('ai-title-out').textContent;
  const descVal=document.getElementById('ai-desc-out').textContent;
  document.getElementById('vid-title').value=titleVal;
  const ytShow=document.getElementById('yt-title-show');
  if(ytShow) ytShow.value=titleVal;
  const ytDesc=document.getElementById('yt-desc');
  if(ytDesc) ytDesc.value=descVal;
  alert('Применено!');
  document.getElementById('yt-desc').value=document.getElementById('ai-desc-out').textContent;
  alert('Применено!');
}
function toggle(id,cb){ document.getElementById(id).classList.toggle('show', cb.checked); if(id==='overlay-extra') setTimeout(updatePreview,50); }

let previewVideoEl = null;

function updatePreview(){
  const canvas=document.getElementById('overlay-preview');
  if(!canvas) return;
  const ctx=canvas.getContext('2d');
  const cw=canvas.width, ch=canvas.height;
  ctx.clearRect(0,0,cw,ch);
  if(previewVideoEl){
    ctx.drawImage(previewVideoEl,0,0,cw,ch);
  } else {
    const grad=ctx.createLinearGradient(0,0,0,ch);
    grad.addColorStop(0,'#2a2a2a'); grad.addColorStop(1,'#111');
    ctx.fillStyle=grad; ctx.fillRect(0,0,cw,ch);
    ctx.fillStyle='#555'; ctx.font='32px sans-serif';
    ctx.textAlign='center'; ctx.textBaseline='middle';
    ctx.fillText('🎥',cw/2,ch/2-10);
    ctx.font='11px sans-serif'; ctx.fillStyle='#444';
    ctx.fillText('загрузи видео',cw/2,ch/2+22);
  }
  const barPct=parseInt(document.getElementById('bar-pct').value)||20;
  const fontSize=parseInt(document.getElementById('overlay-size').value)||32;
  const txt=document.getElementById('overlay-txt').value||'';
  const barH=Math.round(ch*barPct/100);
  const barY=ch-barH;
  const barColor=document.getElementById('bar-color')?document.getElementById('bar-color').value:'#000000';
  const txtColor=document.getElementById('txt-color')?document.getElementById('txt-color').value:'#ffffff';
  ctx.fillStyle=barColor;
  ctx.fillRect(0,barY,cw,barH);
  const scale=ch/640;
  const previewFontSize=Math.max(8,Math.round(fontSize*scale));
  ctx.fillStyle=txtColor;
  ctx.font='bold '+previewFontSize+'px -apple-system,sans-serif';
  ctx.textAlign='center'; ctx.textBaseline='middle';
  ctx.fillText(txt,cw/2,barY+barH/2);
}
function toggleFmt(el,fmt){ el.classList.toggle('on'); if(fmts.has(fmt)) fmts.delete(fmt); else fmts.add(fmt); }
function setPrivacy(p){
  privacy=p;
  ['public','unlisted','private'].forEach(x=>{
    document.getElementById('priv-'+x).classList.toggle('on',x===p);
  });
}

['vdrop','adrop','idrop'].forEach(id=>{
  const el=document.getElementById(id);
  el.ondragover=e=>{e.preventDefault();el.classList.add('drag');};
  el.ondragleave=()=>el.classList.remove('drag');
  el.ondrop=e=>{
    e.preventDefault();el.classList.remove('drag');
    const f=e.dataTransfer.files[0];
    if(f){ const t=id[0]==='v'?'video':id[0]==='a'?'audio':'img'; uploadFile(t,f); }
  };
});

function pickFile(type){
  const inp=document.createElement('input');
  inp.type='file';
  inp.accept=type==='video'||type==='tail_video'?'video/*':type==='audio'?'audio/*':'image/*';
  inp.style.display='none';
  inp.onchange=e=>{ if(e.target.files[0]) uploadFile(type,e.target.files[0]); document.body.removeChild(inp); };
  document.body.appendChild(inp);
  inp.click();
}

function uploadFile(type,file){
  if(type==='video'){
    const lbl=document.getElementById('vlbl');
    const drop=document.getElementById('vdrop');
    lbl.textContent='⏳ Загружаем '+file.name+' ('+Math.round(file.size/1024/1024)+' МБ)...';
    lbl.className='drop-text';
    drop.classList.remove('ok');
    drop.style.opacity='0.6';
    const url=URL.createObjectURL(file);
    const vid=document.createElement('video');
    vid.src=url; vid.muted=true; vid.playsInline=true;
    vid.addEventListener('loadeddata',()=>{ vid.currentTime=Math.min(1,vid.duration*0.1); });
    vid.addEventListener('seeked',()=>{ previewVideoEl=vid; updatePreview(); });
    vid.load();
  }
  if(type==='tail_video'){
    const lblMap={tail_video:'tail-vlbl'};
    const dropMap={tail_video:'tail-vdrop'};
    const fd=new FormData();
    fd.append('file',file);fd.append('type','video');fd.append('filename',file.name);
    fetch('/upload',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
      files['tail_video']=d.path;
      document.getElementById('tail-vlbl').textContent=file.name;
      document.getElementById('tail-vlbl').className='drop-text ok';
      document.getElementById('tail-vdrop').classList.add('ok');
    });
    return;
  }
  const fd=new FormData();
  fd.append('file',file);
  fd.append('type',type);
  fd.append('filename',file.name);
  fetch('/upload',{method:'POST',body:fd})
    .then(r=>r.json()).then(d=>{
      files[type]=d.path;
      const lblMap={video:'vlbl',audio:'albl',img:'ilbl'};
      const dropMap={video:'vdrop',audio:'adrop',img:'idrop'};
      document.getElementById(lblMap[type]).textContent='✅ '+file.name;
      document.getElementById(lblMap[type]).className='drop-text ok';
      const dropEl=document.getElementById(dropMap[type]);
      dropEl.classList.add('ok');
      dropEl.style.opacity='1';
      checkReady();
    }).catch(()=>{
      const lblMap={video:'vlbl',audio:'albl',img:'ilbl'};
      const dropMap={video:'vdrop',audio:'adrop',img:'idrop'};
      document.getElementById(lblMap[type]).textContent='❌ Ошибка загрузки';
      document.getElementById(dropMap[type]).style.opacity='1';
    });
}

function checkReady(){ document.getElementById('go-btn').disabled=!files.video; }

function startJob(){
  if(!files.video) return;
  const params={
    video: files.video, audio: files.audio, tail_img: files.tail_video || files.img,
    use_voice: document.getElementById('voice-on').checked && !!files.audio,
    use_tail: document.getElementById('tail-on').checked && !!(files.tail_video || files.img),
    use_overlay: document.getElementById('overlay-on').checked,
    overlay_txt: document.getElementById('overlay-txt').value,
    overlay_size: document.getElementById('overlay-size').value,
    bar_pct: document.getElementById('bar-pct').value,
    bar_color: document.getElementById('bar-color').value,
    txt_color: document.getElementById('txt-color').value,
    vol: parseInt(document.getElementById('vol').value)/100,
    tail_min: document.getElementById('tail-min').value,
    tail_vol: document.getElementById('tail-vol') ? parseFloat(document.getElementById('tail-vol').value)/100 : 1.0,
    use_noise: document.getElementById('noise-on') ? document.getElementById('noise-on').checked : false,
    noise_strength: document.getElementById('noise-strength') ? document.getElementById('noise-strength').value : 3,
    formats: [...fmts],
    vid_title: document.getElementById('vid-title').value || 'Video',
  };
  document.getElementById('go-btn').disabled=true;
  document.getElementById('progress').style.display='block';
  document.getElementById('downloads').style.display='none';
  document.getElementById('downloads').innerHTML='';
  document.getElementById('yt-section').style.display='none';
  document.getElementById('log-box').textContent='';
  document.getElementById('prog-bar').style.width='0%';

  fetch('/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(params)})
    .then(r=>r.json()).then(d=>{ jobId=d.job_id; logLen=0; pollTimer=setInterval(poll,800); });
}

let logLen=0;
function poll(){
  fetch('/status/'+jobId).then(r=>r.json()).then(d=>{
    const newLogs=d.log.slice(logLen); logLen=d.log.length;
    const lb=document.getElementById('log-box');
    newLogs.forEach(l=>{lb.textContent+=l+'\n';}); lb.scrollTop=lb.scrollHeight;
    document.getElementById('prog-bar').style.width=Math.min(95,logLen*8)+'%';
    if(d.status==='done'){
      clearInterval(pollTimer);
      document.getElementById('prog-bar').style.width='100%';
      document.getElementById('go-btn').disabled=false;
      currentFiles=d.files;
      showDownloads(d.files);
      document.getElementById('yt-section').style.display='block';
    } else if(d.status==='error'){
      clearInterval(pollTimer);
      document.getElementById('go-btn').disabled=false;
    }
  });
}

function showDownloads(files){
  const wrap=document.getElementById('downloads');
  wrap.innerHTML='';
  wrap.style.display='flex';
  // Add video preview for first file
  if(files.length > 0){
    const previewDiv = document.createElement('div');
    previewDiv.style.cssText='width:100%;background:#000;border-radius:12px;overflow:hidden;margin-bottom:8px;';
    const vid = document.createElement('video');
    vid.src = '/download/'+jobId+'/'+files[0].name;
    vid.controls = true;
    vid.style.cssText='width:100%;max-height:360px;display:block;';
    vid.setAttribute('controlsList','');
    vid.setAttribute('preload','metadata');
    previewDiv.appendChild(vid);
    wrap.appendChild(previewDiv);
  }
  files.forEach(f=>{
    const a=document.createElement('a');
    a.href='/download/'+jobId+'/'+f.name;
    a.download=f.name;
    a.className='dl-btn';
    a.innerHTML=`<span style="font-size:22px">⬇️</span><span>Скачать ${f.fmt} — ${f.name}</span><span class="dl-badge">${f.size}MB</span>`;
    wrap.appendChild(a);
  });
}

// ── Mass upload (tab-upload) ──
const massFiles = {916: null, 11: null, 169: null};
let massPrivacy = 'unlisted';
let massJobId = null, massPollTimer = null;

function massFileSelected(input, key){
  const f = input.files[0];
  if(!f) return;
  massFiles[key] = f;
  const drop = document.getElementById('mass-drop-'+key);
  const sub = document.getElementById('mass-sub-'+key);
  drop.classList.add('ok');
  sub.textContent = f.name.length > 16 ? f.name.slice(0,14)+'…' : f.name;
  checkMassReady();
}

function checkMassReady(){
  const ready = massFiles[916] && massFiles[11] && massFiles[169];
  document.getElementById('mass-run-btn').disabled = !ready;
}

function updateMassInfo(){
  const n = parseInt(document.getElementById('mass-n').value)||1;
  document.getElementById('mass-n-info').textContent = `= ${n*3} загрузок (3 формата × ${n})`;
}

function setMassPrivacy(p){
  massPrivacy = p;
  ['public','unlisted','private'].forEach(v=>{
    document.getElementById('mass-priv-'+v).classList.toggle('on', v===p);
  });
}

function renderMassSets(sets, bodyId){
  const tbody = document.getElementById(bodyId);
  sets.forEach(s=>{
    const byFmt = {};
    s.links.forEach(l=>byFmt[l.fmt]=l.link);
    const tr = document.createElement('tr');
    const mk = (fmt,cls) => byFmt[fmt]
      ? `<div style="display:flex;align-items:center;gap:4px;">
           <a href="${byFmt[fmt]}" target="_blank" style="color:#4f46e5;font-size:11px;word-break:break-all;flex:1;">${byFmt[fmt]}</a>
           <button onclick="navigator.clipboard.writeText('${byFmt[fmt]}');this.textContent='✓';setTimeout(()=>this.textContent='📋',1200);" style="border:none;background:#f0f0f0;border-radius:4px;padding:2px 6px;cursor:pointer;font-size:11px;flex-shrink:0;">📋</button>
         </div>`
      : '—';
    tr.innerHTML = `<td style="font-weight:800;color:var(--text2);">${s.set_idx}</td>
      <td style="font-size:11px;color:var(--text3);">${s.channel}</td>
      <td>${mk('9:16','fmt-tag-916')}</td>
      <td>${mk('1:1','fmt-tag-11')}</td>
      <td>${mk('16:9','fmt-tag-169')}</td>`;
    tbody.appendChild(tr);
  });
}

async function startMassUpload(){
  const n = parseInt(document.getElementById('mass-n').value)||1;
  const title = document.getElementById('mass-title').value || 'Video';
  const desc = document.getElementById('mass-desc').value || '';
  const btn = document.getElementById('mass-run-btn');
  btn.disabled = true;

  // Upload 3 files first
  const fmtMap = [
    {key:'916', fmt:'9:16', file:massFiles[916]},
    {key:'11',  fmt:'1:1',  file:massFiles[11]},
    {key:'169', fmt:'16:9', file:massFiles[169]},
  ];
  const uploadedFiles = [];
  for(const {fmt, file} of fmtMap){
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch('/upload',{method:'POST',body:fd});
    const d = await r.json();
    uploadedFiles.push({path:d.path, fmt, size:(file.size/1024/1024).toFixed(1), title:`${title} [${fmt}]`});
  }

  // Start mass upload job
  const res = await fetch('/mass_yt_upload',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({files:uploadedFiles, n_sets:n, title, description:desc, privacy:massPrivacy})});
  const data = await res.json();
  massJobId = data.job_id;

  document.getElementById('mass-log').style.display='block';
  document.getElementById('mass-log').textContent='';
  document.getElementById('mass-progress-wrap').style.display='block';
  document.getElementById('mass-result').style.display='none';
  document.getElementById('mass-result-body').innerHTML='';
  let massLogLen=0, lastSetCount=0;
  massPollTimer = setInterval(()=>{
    fetch('/mass_yt_status/'+massJobId).then(r=>r.json()).then(d=>{
      const newLogs=d.log.slice(massLogLen); massLogLen=d.log.length;
      const lb=document.getElementById('mass-log');
      newLogs.forEach(l=>{lb.textContent+=l+'\n';}); lb.scrollTop=lb.scrollHeight;
      const pct = d.total>0 ? Math.round(d.done/d.total*100) : 0;
      document.getElementById('mass-progress-fill').style.width=pct+'%';
      document.getElementById('mass-progress-text').textContent=`${d.done} / ${d.total}`;
      // Render new sets
      if(d.sets.length > lastSetCount){
        const newSets = d.sets.slice(lastSetCount);
        renderMassSets(newSets,'mass-result-body');
        document.getElementById('mass-result').style.display='block';
        lastSetCount=d.sets.length;
      }
      if(d.status==='done'||d.status==='error'){
        clearInterval(massPollTimer);
        btn.disabled=false;
      }
    });
  },1500);
}

// ── Auto upload (1 video → 3 formats → N accounts) ──
// ─── Upload mode switcher ───────────────────────────────────────
function setUploadMode(mode){
  const isAuto = mode === 'auto';
  document.getElementById('auto-mode-section').style.display = isAuto ? '' : 'none';
  document.getElementById('ready-mode-section').style.display = isAuto ? 'none' : '';
  document.getElementById('mode-auto-btn').style.cssText = isAuto
    ? 'flex:1;padding:10px;border-radius:10px;border:2px solid #4f46e5;background:#4f46e5;color:#fff;font-weight:700;font-size:13px;cursor:pointer;'
    : 'flex:1;padding:10px;border-radius:10px;border:2px solid #d1d5db;background:var(--surface2);color:var(--text3);font-weight:700;font-size:13px;cursor:pointer;';
  document.getElementById('mode-ready-btn').style.cssText = isAuto
    ? 'flex:1;padding:10px;border-radius:10px;border:2px solid #d1d5db;background:var(--surface2);color:var(--text3);font-weight:700;font-size:13px;cursor:pointer;'
    : 'flex:1;padding:10px;border-radius:10px;border:2px solid #16a34a;background:#16a34a;color:#fff;font-weight:700;font-size:13px;cursor:pointer;';
}

// ─── Ready upload mode ──────────────────────────────────────────
let readyFiles = {}, readyCat = '', readyPrivacy = 'unlisted', readyJobId = null, readyPollTimer = null;

function readyDropAll(event){
  event.preventDefault();
  document.getElementById('ready-dropzone').style.borderColor = '#d1d5db';
  const files = Array.from(event.dataTransfer.files).filter(f=>f.type.startsWith('video/'));
  files.forEach(f => detectAndUploadReadyFile(f));
}

function readyAllSelected(input){
  Array.from(input.files).forEach(f => detectAndUploadReadyFile(f));
}

function detectAndUploadReadyFile(file){
  // Detect format from filename or use video metadata
  const name = file.name.toLowerCase();
  let fmt = null;
  if(name.includes('9x16') || name.includes('9_16') || name.includes('916') || name.includes('short')) fmt = '9:16';
  else if(name.includes('1x1') || name.includes('1_1') || name.includes('11') || name.includes('feed') || name.includes('square')) fmt = '1:1';
  else if(name.includes('16x9') || name.includes('16_9') || name.includes('169') || name.includes('youtube')) fmt = '16:9';

  if(fmt){
    uploadReadyFile(file, fmt);
  } else {
    // Try to detect from video dimensions
    const video = document.createElement('video');
    video.preload = 'metadata';
    video.onloadedmetadata = () => {
      URL.revokeObjectURL(video.src);
      const w = video.videoWidth, h = video.videoHeight;
      if(h > w) fmt = '9:16';
      else if(w === h) fmt = '1:1';
      else fmt = '16:9';
      uploadReadyFile(file, fmt);
    };
    video.src = URL.createObjectURL(file);
  }
}

function uploadReadyFile(file, fmt){
  const fd = new FormData();
  fd.append('file', file); fd.append('type', 'video'); fd.append('filename', file.name);
  fetch('/upload',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    readyFiles[fmt] = {path: d.path, fmt};
    const idMap = {'9:16':'916','1:1':'11','16:9':'169'};
    const key = idMap[fmt];
    document.getElementById('ready-'+key+'-name').textContent = '✅ ' + file.name;
    document.getElementById('ready-'+key+'-name').style.display = '';
    document.getElementById('ready-'+key+'-btn').style.borderColor = '#16a34a';
    updateReadyBtn();
  });
}

function readyFileSelected(input, fmt){
  const file = input.files[0];
  if(!file) return;
  uploadReadyFile(file, fmt);
}

function setReadyCat(btn){
  document.querySelectorAll('#ready-cat-grid .lang-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  readyCat = btn.dataset.cat;
  updateReadyBtn();
}

function setReadyPrivacy(p){
  readyPrivacy = p;
  ['public','unlisted','private'].forEach(x=>{
    document.getElementById('ready-priv-'+x).classList.toggle('on', x===p);
  });
}

function updateReadyInfo(){
  const n = parseInt(document.getElementById('ready-n').value)||1;
  const fmts = Object.keys(readyFiles).length;
  document.getElementById('ready-n-info').textContent = fmts > 0 ? `= ${n*fmts} видео (${fmts} форм. × ${n})` : '';
}

function updateReadyBtn(){
  updateReadyInfo();
  const hasFiles = Object.keys(readyFiles).length > 0;
  document.getElementById('ready-run-btn').disabled = !(hasFiles && readyCat);
}

async function startReadyUpload(){
  const n = parseInt(document.getElementById('ready-n').value)||1;
  const files = Object.values(readyFiles);
  document.getElementById('ready-progress-wrap').style.display = '';
  document.getElementById('ready-log').style.display = '';
  document.getElementById('ready-result').style.display = 'none';
  document.getElementById('ready-run-btn').disabled = true;
  const res = await fetch('/ready_upload',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({files, n_sets:n, category:readyCat, privacy:readyPrivacy})});
  const data = await res.json();
  readyJobId = data.job_id;
  readyPollTimer = setInterval(()=>pollReadyJob(), 1500);
}

function pollReadyJob(){
  fetch('/mass_yt_status/'+readyJobId).then(r=>r.json()).then(d=>{
    document.getElementById('ready-log').textContent = d.log.join('\n');
    document.getElementById('ready-log').scrollTop = 9999;
    const pct = d.total>0 ? Math.round(d.done/d.total*100) : 0;
    document.getElementById('ready-progress-fill').style.width = pct+'%';
    document.getElementById('ready-progress-text').textContent = d.done+' / '+d.total;
    if(d.status==='done'||d.status==='error'){
      clearInterval(readyPollTimer);
      document.getElementById('ready-run-btn').disabled = false;
      if(d.sets && d.sets.length){
        document.getElementById('ready-result').style.display = '';
        const tbody = document.getElementById('ready-result-body');
        tbody.innerHTML = '';
        d.sets.forEach(s=>{
          s.links.forEach(lk=>{
            tbody.innerHTML += `<tr><td>${s.set_idx}</td><td>${s.channel}</td><td>${lk.fmt}</td><td><a href="${lk.link}" target="_blank">${lk.link}</a></td></tr>`;
          });
        });
      }
    }
  });
}

// ─── Auto upload mode ───────────────────────────────────────────
let autoVideoPath = null, autoCat = '', autoPrivacy = 'unlisted', autoJobId = null, autoPollTimer = null;

function autoVideoSelected(input){
  const file = input.files[0];
  if(!file) return;
  const fd = new FormData();
  fd.append('file', file);
  document.getElementById('auto-video-name').textContent = '⏳ Загружаем файл...';
  fetch('/upload',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    autoVideoPath = d.path;
    document.getElementById('auto-video-name').textContent = '✅ ' + file.name;
    document.getElementById('auto-video-btn').style.borderColor = '#16a34a';
    updateAutoRunBtn();
    // Диагностика: что перекрывает кнопку Суставы
    setTimeout(()=>{
      const btn = document.querySelector('#auto-cat-grid .lang-btn');
      if(btn){
        const r = btn.getBoundingClientRect();
        const el = document.elementFromPoint(r.left+5, r.top+5);
        console.log('Поверх кнопки:', el ? el.tagName+' id='+el.id+' class='+el.className : 'null');
      }
    }, 500);
  });
}

function setAutoCat(btn){
  document.querySelectorAll('#auto-cat-grid .lang-btn').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  autoCat = btn.dataset.cat;
  document.getElementById('auto-cat-selected').textContent = 'Выбрано: ' + autoCat;
  updateAutoRunBtn();
}

function setAutoPrivacy(p){
  autoPrivacy = p;
  ['public','unlisted','private'].forEach(x=>{
    document.getElementById('auto-priv-'+x).classList.toggle('on', x===p);
  });
}

function updateAutoInfo(){
  const n = parseInt(document.getElementById('auto-n').value)||1;
  document.getElementById('auto-n-info').textContent = `= ${n*3} видео (3 формата × ${n})`;
  updateAutoRunBtn();
}

function updateAutoRunBtn(){
  document.getElementById('auto-run-btn').disabled = !(autoVideoPath && autoCat);
}

async function startAutoUpload(){
  const n = parseInt(document.getElementById('auto-n').value)||1;
  const btn = document.getElementById('auto-run-btn');
  btn.disabled = true;
  document.getElementById('auto-log').style.display = 'block';
  document.getElementById('auto-log').textContent = '';
  document.getElementById('auto-progress-wrap').style.display = 'block';
  document.getElementById('auto-result').style.display = 'none';
  document.getElementById('auto-result-body').innerHTML = '';

  const res = await fetch('/auto_upload',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({src_video:autoVideoPath, n_sets:n, category:autoCat, privacy:autoPrivacy, custom_title:document.getElementById('auto-ai-title').textContent||'', custom_desc:document.getElementById('auto-ai-desc').textContent||''})});
  const data = await res.json();
  autoJobId = data.job_id;

  let logLen=0, lastSetCount=0;
  autoPollTimer = setInterval(()=>{
    fetch('/mass_yt_status/'+autoJobId).then(r=>r.json()).then(d=>{
      const newLogs=d.log.slice(logLen); logLen=d.log.length;
      const lb=document.getElementById('auto-log');
      newLogs.forEach(l=>{lb.textContent+=l+'\n';}); lb.scrollTop=lb.scrollHeight;
      const pct = d.total>0 ? Math.round(d.done/d.total*100) : 0;
      document.getElementById('auto-progress-fill').style.width=pct+'%';
      document.getElementById('auto-progress-text').textContent=`${d.done} / ${d.total}`;
      if(d.sets.length > lastSetCount){
        renderMassSets(d.sets.slice(lastSetCount),'auto-result-body');
        document.getElementById('auto-result').style.display='block';
        lastSetCount=d.sets.length;
      }
      if(d.status==='done'||d.status==='error'){
        clearInterval(autoPollTimer);
        btn.disabled=false;
      }
    });
  },1500);
}

// ── Mass upload from build tab ──
let buildMassJobId=null, buildMassPollTimer=null;
function updateBuildMassInfo(){
  const n=parseInt(document.getElementById('build-mass-n').value)||1;
  document.getElementById('build-mass-info').textContent=`= ${n*3} загрузок`;
}
function startBuildMassUpload(){
  const n=parseInt(document.getElementById('build-mass-n').value)||1;
  if(!currentFiles||currentFiles.length===0){alert('Сначала собери видео!');return;}
  const title=document.getElementById('vid-title').value||'Video';
  const desc=document.getElementById('yt-desc').value||'';
  const btn=document.getElementById('build-mass-btn');
  btn.disabled=true;
  document.getElementById('build-mass-log').style.display='block';
  document.getElementById('build-mass-log').textContent='';
  document.getElementById('build-mass-progress-wrap').style.display='block';
  document.getElementById('build-mass-result').style.display='none';
  document.getElementById('build-mass-result-body').innerHTML='';
  fetch('/mass_yt_upload',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({files:currentFiles,n_sets:n,title,description:desc,privacy:privacy})})
  .then(r=>r.json()).then(data=>{
    buildMassJobId=data.job_id;
    let logLen=0, lastSetCount=0;
    buildMassPollTimer=setInterval(()=>{
      fetch('/mass_yt_status/'+buildMassJobId).then(r=>r.json()).then(d=>{
        const newLogs=d.log.slice(logLen); logLen=d.log.length;
        const lb=document.getElementById('build-mass-log');
        newLogs.forEach(l=>{lb.textContent+=l+'\n';}); lb.scrollTop=lb.scrollHeight;
        const pct=d.total>0?Math.round(d.done/d.total*100):0;
        document.getElementById('build-mass-progress-fill').style.width=pct+'%';
        document.getElementById('build-mass-progress-text').textContent=`${d.done} / ${d.total}`;
        if(d.sets.length>lastSetCount){
          renderMassSets(d.sets.slice(lastSetCount),'build-mass-result-body');
          document.getElementById('build-mass-result').style.display='block';
          lastSetCount=d.sets.length;
        }
        if(d.status==='done'||d.status==='error'){
          clearInterval(buildMassPollTimer);
          btn.disabled=false;
        }
      });
    },1500);
  });
}

function handleReadyFiles(input){
  const files = Array.from(input.files);
  if(!files.length) return;
  const listEl = document.getElementById('ready-files-list');
  listEl.innerHTML = files.map(f => `✅ ${f.name} (${(f.size/1024/1024).toFixed(1)}MB)`).join('<br>');
  // Store as ready files for upload
  window.readyFilesData = files;
  // Upload them to server first
  const promises = files.map(f => {
    const fd = new FormData();
    fd.append('file', f);
    fd.append('type', 'ready_video');
    fd.append('filename', f.name);
    return fetch('/upload', {method:'POST', body:fd}).then(r=>r.json()).then(d => ({
      path: d.path,
      fmt: f.name.replace('.mp4',''),
      size: (f.size/1024/1024).toFixed(1),
      title: document.getElementById('vid-title').value || f.name.replace('.mp4','')
    }));
  });
  Promise.all(promises).then(uploadedFiles => {
    currentFiles = uploadedFiles;
    listEl.innerHTML += '<br><b style="color:#16a34a">✅ Готово! Нажми Загрузить на YouTube</b>';
  });
}

function startUpload(){
  const btn=document.getElementById('yt-btn');
  btn.disabled=true;
  document.getElementById('yt-log').style.display='block';
  document.getElementById('yt-log').textContent='';
  document.getElementById('yt-links').innerHTML='';
  const selCh = document.getElementById('upload-channel-select');
  const params={
    files: currentFiles,
    title: document.getElementById('vid-title').value || 'Video',
    description: document.getElementById('yt-desc').value || '',
    privacy: privacy,
    channel_id: selCh ? selCh.value : 'auto',
  };
  fetch('/yt_upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(params)})
    .then(r=>r.json()).then(d=>{ ytJobId=d.job_id; ytLogLen=0; ytPollTimer=setInterval(pollYt,1000); });
}

let ytLogLen=0;
function pollYt(){
  fetch('/yt_status/'+ytJobId).then(r=>r.json()).then(d=>{
    const newLogs=d.log.slice(ytLogLen); ytLogLen=d.log.length;
    const lb=document.getElementById('yt-log');
    newLogs.forEach(l=>{lb.textContent+=l+'\n';}); lb.scrollTop=lb.scrollHeight;
    if(d.status==='done'){
      clearInterval(ytPollTimer);
      document.getElementById('yt-btn').disabled=false;
      showYtLinks(d.links||[]);
    } else if(d.status==='error'){
      clearInterval(ytPollTimer);
      document.getElementById('yt-btn').disabled=false;
    }
  });
}

function showYtLinks(links){
  const wrap=document.getElementById('yt-links');
  links.forEach(l=>{
    const a=document.createElement('a');
    a.href=l.link; a.target='_blank'; a.className='yt-link';
    a.innerHTML=`<span>🔗</span><span>${l.fmt} → ${l.link}</span>`;
    wrap.appendChild(a);
  });
}

// Theme toggle
fetch('/version').then(r=>r.json()).then(d=>{ document.getElementById('app-version').textContent='v'+d.version; });

window.addEventListener('DOMContentLoaded', async ()=>{
  try{
    const r = await fetch('/update');
    const d = await r.json();
    if(d.status === 'updated'){
      const banner = document.createElement('div');
      banner.style.cssText = 'position:fixed;top:0;left:0;right:0;background:#4f46e5;color:#fff;text-align:center;padding:12px;font-size:14px;font-weight:700;z-index:9999;';
      banner.innerHTML = '🔄 Обновление установлено! <button onclick="location.reload()" style="margin-left:12px;padding:4px 12px;background:#fff;color:#4f46e5;border:none;border-radius:6px;font-weight:700;cursor:pointer;">Перезагрузить</button>';
      document.body.prepend(banner);
    }
  }catch(e){}
});

async function checkUpdate(){
  const btn = document.getElementById('update-btn');
  btn.textContent = '⏳ Проверяем...';
  btn.disabled = true;
  try {
    const r = await fetch('/update');
    const d = await r.json();
    if(d.status === 'latest'){
      btn.textContent = `✓ Версия ${d.version} — актуальная`;
      setTimeout(()=>{btn.textContent='🔄 Обновить';btn.disabled=false;}, 3000);
    } else if(d.status === 'updated'){
      btn.textContent = `✅ Оновлено ${d.old} → ${d.new}! Закрий термінал і запусти знову`;
      
    } else {
      btn.textContent = '❌ Ошибка';
      btn.disabled = false;
    }
  } catch(e){
    btn.textContent = '❌ Ошибка';
    btn.disabled = false;
  }
}

function toggleTheme(){
  const html=document.documentElement;
  const isDark=html.getAttribute('data-theme')==='dark';
  html.setAttribute('data-theme', isDark?'light':'dark');
  const btn=document.getElementById('theme-btn');
  btn.textContent=isDark?'🌙 Тёмная':'☀️ Светлая';
  localStorage.setItem('theme', isDark?'light':'dark');
}
(function(){
  const saved=localStorage.getItem('theme');
  if(saved==='dark'){
    document.documentElement.setAttribute('data-theme','dark');
    document.addEventListener('DOMContentLoaded',()=>{
      const btn=document.getElementById('theme-btn');
      if(btn) btn.textContent='☀️ Светлая';
    });
  }
})();

// ── Binom ──────────────────────────────────────────────────────
const GOOGLE_THRESHOLDS = [10, 50, 100, 200, 350];

function getNextBill(cost, prepay) {
  const spend = Math.max(0, cost - prepay);
  for (let t of GOOGLE_THRESHOLDS) {
    if (spend < t) return { next: t, remaining: +(t - spend).toFixed(2) };
  }
  const extra = Math.ceil((spend - 350) / 350);
  const next = 350 + extra * 350;
  return { next, remaining: +(next - spend).toFixed(2) };
}

async function saveBinomKey() {
  const key = document.getElementById('binom-key').value.trim();
  if (!key) return;
  await fetch('/binom/key', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({key})});
  document.getElementById('binom-status').textContent = '✅ Ключ сохранён';
  loadBinom();
}

async function loadBinom() {
  const st = document.getElementById('binom-status');
  const wrap = document.getElementById('binom-table-wrap');
  st.textContent = '⏳ Загружаем данные из Binom...';
  wrap.innerHTML = '';
  try {
    const [statsR, settR] = await Promise.all([fetch('/binom/stats'), fetch('/binom/settings')]);
    const stats = await statsR.json();
    const sett = await settR.json();
    if (stats.error) { st.textContent = '❌ ' + stats.error; return; }

    // Group by account name (ACC####_NAME pattern)
    const accounts = {};
    for (const c of stats) {
      if (c.id === "totals") continue;
      const name = c.name || '';
      const m = name.match(/^(ACC\d+_[A-Z_]+)/i);
      const acc = m ? m[1] : name.split('_').slice(0,2).join('_');
      if (!accounts[acc]) accounts[acc] = { cost: 0, n: 0 };
      accounts[acc].cost += parseFloat(c.cost || 0);
      accounts[acc].n++;
    }

    const now = new Date().toLocaleTimeString();
    st.textContent = `✅ Обновлено в ${now} · ${Object.keys(accounts).length} аккаунтов`;

    let html = `<table style="width:100%;border-collapse:collapse;font-size:13px;">
<thead><tr style="background:var(--surface2);">
<th style="padding:9px 12px;text-align:left;border:1px solid var(--border);">Аккаунт</th>
<th style="padding:9px 12px;text-align:right;border:1px solid var(--border);">Cost</th>
<th style="padding:9px 12px;text-align:center;border:1px solid var(--border);">Припей $</th>
<th style="padding:9px 12px;text-align:right;border:1px solid var(--border);">Следующий бил</th>
<th style="padding:9px 12px;text-align:right;border:1px solid var(--border);">Осталось до била</th>
</tr></thead><tbody>`;

    const sorted = Object.entries(accounts).sort((a,b) => b[1].cost - a[1].cost);
    for (const [acc, data] of sorted) {
      const s = sett[acc] || {};
      const prepay = parseFloat(s.prepay || 0);
      const bill = getNextBill(data.cost, prepay);
      const rem = bill.remaining;
      const color = rem < 5 ? '#ef4444' : rem < 20 ? '#f59e0b' : 'var(--text1)';
      html += `<tr>
<td style="padding:9px 12px;border:1px solid var(--border);font-weight:600;">${acc}</td>
<td style="padding:9px 12px;text-align:right;border:1px solid var(--border);">$${data.cost.toFixed(2)}</td>
<td style="padding:9px 12px;text-align:center;border:1px solid var(--border);">
  <input type="number" value="${prepay||''}" placeholder="0" min="0" step="1"
    style="width:60px;padding:4px 6px;border:1px solid var(--border);border-radius:6px;background:var(--surface2);color:var(--text1);text-align:center;font-size:12px;"
    onchange="saveBinomSetting('${acc}','prepay',this.value)">
</td>
<td style="padding:9px 12px;text-align:right;border:1px solid var(--border);font-weight:700;">$${bill.next}</td>
<td style="padding:9px 12px;text-align:right;border:1px solid var(--border);font-weight:700;color:${color};">$${rem}</td>
</tr>`;
    }
    html += '</tbody></table>';
    wrap.innerHTML = html;
    setTimeout(loadBinom, 300000); // refresh every 5 min
  } catch(e) { st.textContent = '❌ ' + e.message; }
}

async function saveBinomSetting(acc, field, value) {
  await fetch('/binom/settings', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({acc, field, value})});
}
</script>

  <div id="tab-binom" class="tab-pane">
    <div style="max-width:960px;margin:0 auto;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:8px;">
        <h2 style="margin:0;font-size:18px;">📊 Binom — Спенд по аккаунтам</h2>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <input id="binom-key" type="password" placeholder="Binom API Key" style="padding:7px 10px;border:1px solid var(--border);border-radius:8px;background:var(--surface2);color:var(--text1);font-size:12px;width:210px;">
          <button onclick="saveBinomKey()" style="padding:7px 12px;background:var(--grad1);color:#fff;border:none;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;">Сохранить ключ</button>
          <button onclick="loadBinom()" style="padding:7px 12px;background:var(--surface2);color:var(--text1);border:1px solid var(--border);border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;">🔄 Обновить</button>
        </div>
      </div>
      <div id="binom-status" style="margin-bottom:12px;font-size:13px;color:var(--text3);"></div>
      <div id="binom-table-wrap"></div>
    </div>
  </div>

</body>
</html>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def get_current_user(self):
        # Localhost (Pavel's machine) — always auto-login
        if self.client_address[0] in ('127.0.0.1', '::1'):
            return 'pavel'
        # Check session cookie
        cookies = self.headers.get('Cookie', '')
        for part in cookies.split(';'):
            part = part.strip()
            if part.startswith('session='):
                sid = part[8:]
                if sid in SESSIONS:
                    return SESSIONS[sid]['user']
        return None

    def require_auth(self):
        user = self.get_current_user()
        if user:
            return user
        # First launch — show setup screen
        html = SETUP_HTML if is_first_launch() else LOGIN_HTML
        body = html.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return None

    def do_GET(self):
        path = urlparse(self.path).path

        if path == '/setup':
            html = SETUP_HTML if is_first_launch() else LOGIN_HTML
            body = html.encode()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)
            return

        if path == '/login':
            body = LOGIN_HTML.encode()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(body)
            return

        if path == '/logout':
            cookies = self.headers.get('Cookie','')
            for part in cookies.split(';'):
                part = part.strip()
                if part.startswith('session='):
                    SESSIONS.pop(part[8:], None)
                    save_sessions(SESSIONS)
            self.send_response(302)
            self.send_header('Location','/')
            self.send_header('Set-Cookie','session=; Max-Age=0; Path=/')
            self.end_headers()
            return

        user = self.require_auth()
        if not user:
            return

        if path == '/admin':
            if user.lower() not in ('pavel', 'pavel2121'):
                self.send_response(403); self.end_headers(); return
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(ADMIN_HTML.encode())
            return
        elif path == '/admin/users':
            if user.lower() not in ('pavel', 'pavel2121'):
                self.json({'ok': False}); return
            self.json({'ok': True, 'users': list(USERS.keys())})
            return
        elif path == '/binom/stats':
            binom_key_file = os.path.join(BASE_DIR, 'binom_key.txt')
            if not os.path.exists(binom_key_file):
                self.json({'error': 'API ключ не задан'}); return
            bk = open(binom_key_file).read().strip()
            try:
                import requests as _breq
                resp = _breq.get('https://swat.icu/public/api/v1/stats/campaign',
                    headers={'Api-Key': bk}, timeout=15)
                self.json(resp.json())
            except Exception as e:
                self.json({'error': str(e)})
            return
        elif path == '/binom/settings':
            binom_sett_file = os.path.join(BASE_DIR, 'binom_settings.json')
            import json as _bsj
            self.json(_bsj.load(open(binom_sett_file)) if os.path.exists(binom_sett_file) else {})
            return
        elif path == '/version':
            self.json({'version': VERSION}); return
        elif path == '/update':
            import urllib.request as _ur
            try:
                update_url = 'https://raw.githubusercontent.com/Rodenom/videoeditor-panel/main/app.py'
                req = _ur.Request(update_url)
                new_code = _ur.urlopen(req, timeout=10).read()
                current_file = os.path.abspath(__file__)
                with open(current_file, 'rb') as f:
                    current_code = f.read()
                import re as _re
                new_ver = (_re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', new_code.decode('utf-8', errors='ignore')) or [None,None])[1] or '?'
                if new_ver == VERSION:
                    self.json({'ok': True, 'status': 'latest', 'version': VERSION})
                else:
                    with open(current_file, 'wb') as f:
                        f.write(new_code)
                    self.json({'ok': True, 'status': 'updated', 'old': VERSION, 'new': new_ver})
            except Exception as e:
                self.json({'ok': False, 'error': str(e)})
            return
        elif path == '/':
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store, no-cache, must-revalidate')
            self.send_header('Pragma','no-cache')
            self.end_headers()
            self.wfile.write(HTML.encode())
        elif path == '/projects':
            projects = load_projects(user)
            uploads = load_project_uploads(user)
            counts = uploads.get('counts', {})
            result = []
            for pid, pinfo in projects.items():
                result.append({'id': pid, 'name': pinfo.get('name',''), 'uploads_today': counts.get(pid,0), 'remaining': max(0, 100-counts.get(pid,0))})
            self.json({'projects': result})
        elif path.startswith('/delete_project/'):
            pid = path.split('/')[-1]
            projects = load_projects(user)
            if pid in projects:
                f = projects[pid].get('file','')
                if os.path.exists(f) and f != CREDENTIALS_FILE:
                    os.remove(f)
                del projects[pid]
                save_projects(user, projects)
            self.json({'ok': True})
        elif path == '/channels':
            channels = load_channels(user)
            today_data = load_uploads_today()
            counts = today_data.get('counts', {})
            result = []
            for ch_id, ch_info in channels.items():
                result.append({
                    'id': ch_id,
                    'name': ch_info['name'],
                    'uploads_today': counts.get(ch_id, 0),
                    'available': counts.get(ch_id, 0) < 10,
                    'proxy': bool(ch_info.get('proxy', ''))
                })
            self.json({'channels': result})
        elif path == '/add_channel_status/':
            pass
        elif path.startswith('/add_channel_status/'):
            job_id = path.split('/')[-1]
            job = UPLOAD_JOBS.get(job_id, {'status':'unknown','log':[]})
            self.json({'status':job['status'],'log':job['log'],'channel':job.get('channel'),'auth_url':job.get('auth_url')})
        elif path.startswith('/delete_channel/'):
            ch_id = path.split('/')[-1]
            channels = load_channels(user)
            if ch_id in channels:
                token_file = channels[ch_id].get('token_file','')
                if os.path.exists(token_file):
                    os.remove(token_file)
                del channels[ch_id]
                save_channels(user, channels)
            self.json({'ok': True})
        elif path == '/download_prokla/':
            pass
        elif path.startswith('/download_prokla/'):
            file_id = path.split('/')[-1]
            fpath = os.path.join(OUTPUT_DIR, 'prokla_' + file_id + '.zip')
            if os.path.exists(fpath):
                fname = os.path.basename(fpath)
                self.send_response(200)
                self.send_header('Content-Type','application/zip')
                self.send_header('Content-Disposition',f'attachment; filename="{fname}"')
                self.send_header('Content-Length', str(os.path.getsize(fpath)))
                self.end_headers()
                with open(fpath,'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404); self.end_headers()
        elif path.startswith('/preview/'):
            parts = path.split('/', 3)
            if len(parts) >= 3:
                pid = parts[2]
                subpath = parts[3] if len(parts) > 3 else 'index.html'
                if not subpath: subpath = 'index.html'
                preview_base = os.path.join(OUTPUT_DIR, f'preview_{pid}')
                safe_base = os.path.realpath(preview_base)
                # Try direct path first
                fpath = os.path.realpath(os.path.join(preview_base, subpath))
                # If not found, search in subdirectories (ZIP may have subdomain folder)
                if not os.path.exists(fpath):
                    fname_only = subpath.split('/')[-1]
                    for root, dirs, files in os.walk(preview_base):
                        if fname_only in files:
                            candidate = os.path.realpath(os.path.join(root, fname_only))
                            if candidate.startswith(safe_base):
                                fpath = candidate
                                break
                if not fpath.startswith(safe_base):
                    self.send_response(403); self.end_headers(); return
                if os.path.isdir(fpath):
                    fpath = os.path.join(fpath, 'index.html')
                if os.path.exists(fpath):
                    ext = os.path.splitext(fpath)[1].lower().lstrip('.')
                    mime = {'html':'text/html;charset=utf-8','css':'text/css','js':'application/javascript',
                            'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png','webp':'image/webp',
                            'gif':'image/gif','svg':'image/svg+xml','ico':'image/x-icon',
                            'woff':'font/woff','woff2':'font/woff2','ttf':'font/ttf','otf':'font/otf',
                            'mp4':'video/mp4','webm':'video/webm'}.get(ext,'application/octet-stream')
                    with open(fpath,'rb') as f: data = f.read()
                    # Inject scroll-to-form script for part=2
                    if ext == 'html':
                        pass
                    self.send_response(200)
                    self.send_header('Content-Type', mime)
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_response(404); self.end_headers()
            else:
                self.send_response(404); self.end_headers()
        elif path == '/get_key':
            self.json({'key': get_anthropic_key()})
        elif path.startswith('/status/'):
            job_id = path.split('/')[-1]
            job = JOBS.get(job_id, {'status':'unknown','log':[],'files':[]})
            self.json({'status':job['status'],'log':job['log'],'files':job.get('files',[])})
        elif path.startswith('/yt_status/'):
            job_id = path.split('/')[-1]
            job = UPLOAD_JOBS.get(job_id, {'status':'unknown','log':[],'links':[]})
            self.json({'status':job['status'],'log':job['log'],'links':job.get('links',[])})
        elif path.startswith('/mass_yt_status/'):
            job_id = path.split('/')[-1]
            job = MASS_UPLOAD_JOBS.get(job_id, {'status':'unknown','log':[],'sets':[],'total':0,'done':0})
            self.json({'status':job['status'],'log':job['log'],'sets':job.get('sets',[]),'total':job.get('total',0),'done':job.get('done',0)})
        elif path.startswith('/download/'):
            parts = path.split('/')
            job_id, fname = parts[2], parts[3]
            fpath = os.path.join(OUTPUT_DIR, job_id, fname)
            if os.path.exists(fpath):
                file_size = os.path.getsize(fpath)
                range_header = self.headers.get('Range')
                if range_header:
                    # Support range requests for video seeking
                    byte1, byte2 = 0, None
                    m = range_header.replace('bytes=','').split('-')
                    byte1 = int(m[0]) if m[0] else 0
                    byte2 = int(m[1]) if m[1] else file_size - 1
                    length = byte2 - byte1 + 1
                    self.send_response(206)
                    self.send_header('Content-Type','video/mp4')
                    self.send_header('Accept-Ranges','bytes')
                    self.send_header('Content-Range',f'bytes {byte1}-{byte2}/{file_size}')
                    self.send_header('Content-Length', str(length))
                    self.end_headers()
                    with open(fpath,'rb') as f:
                        f.seek(byte1)
                        self.wfile.write(f.read(length))
                else:
                    self.send_response(200)
                    self.send_header('Content-Type','video/mp4')
                    self.send_header('Accept-Ranges','bytes')
                    self.send_header('Content-Length', str(file_size))
                    self.end_headers()
                    with open(fpath,'rb') as f:
                        self.wfile.write(f.read())
            else:
                self.send_response(404); self.end_headers()
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        user = self.get_current_user()

        # Login endpoint — no auth needed
        if path == '/admin/add_user':
            if user.lower() not in ('pavel', 'pavel2121'):
                self.json({'ok': False, 'error': 'Нет доступа'}); return
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            uname = data.get('username', '').strip()
            pw = data.get('password', '').strip()
            if not uname or not pw:
                self.json({'ok': False, 'error': 'Заполни все поля'}); return
            if uname == 'pavel':
                self.json({'ok': False, 'error': 'Нельзя'}); return
            USERS[uname] = hashlib.sha256(pw.encode()).hexdigest()
            save_users(USERS)
            self.json({'ok': True})
            return
        elif path == '/admin/delete_user':
            if user.lower() not in ('pavel', 'pavel2121'):
                self.json({'ok': False, 'error': 'Нет доступа'}); return
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            uname = data.get('username', '').strip()
            if uname == 'pavel':
                self.json({'ok': False, 'error': 'Нельзя удалить pavel'}); return
            USERS.pop(uname, None)
            save_users(USERS)
            # Remove sessions for this user
            to_del = [k for k, v in SESSIONS.items() if v.get('user') == uname]
            for k in to_del: SESSIONS.pop(k)
            save_sessions(SESSIONS)
            self.json({'ok': True})
            return
        elif path == '/binom/key':
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            binom_key_file = os.path.join(BASE_DIR, 'binom_key.txt')
            open(binom_key_file, 'w').write(data.get('key','').strip())
            self.json({'ok': True}); return
        elif path == '/binom/settings':
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            import json as _bsj2
            binom_sett_file = os.path.join(BASE_DIR, 'binom_settings.json')
            sett = _bsj2.load(open(binom_sett_file)) if os.path.exists(binom_sett_file) else {}
            acc = data.get('acc','')
            if acc:
                if acc not in sett: sett[acc] = {}
                sett[acc][data.get('field','')] = data.get('value','')
            open(binom_sett_file,'w').write(_bsj2.dumps(sett, indent=2))
            self.json({'ok': True}); return
        elif path == '/setup':
            if not is_first_launch():
                self.json({'ok': False, 'error': 'Аккаунт уже создан'}); return
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            uname = data.get('u', '').strip()
            pw = data.get('p', '')
            if len(uname) < 2 or len(pw) < 4:
                self.json({'ok': False, 'error': 'Логин или пароль слишком короткий'}); return
            pw_hash = hashlib.sha256(pw.encode()).hexdigest()
            USERS[uname] = pw_hash
            save_users(USERS)
            sid = uuid.uuid4().hex
            SESSIONS[sid] = {'user': uname, 'exp': time.time() + 30*24*3600}
            save_sessions(SESSIONS)
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Set-Cookie', f'session={sid}; Max-Age=2592000; Path=/; HttpOnly; SameSite=Lax')
            self.end_headers()
            self.wfile.write(body)
            return
        elif path == '/login':
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            uname = data.get('u', '')
            pw_hash = hashlib.sha256(data.get('p', '').encode()).hexdigest()
            if uname in USERS and USERS[uname] == pw_hash:
                sid = uuid.uuid4().hex
                SESSIONS[sid] = {'user': uname, 'exp': time.time() + 30*24*3600}
                save_sessions(SESSIONS)
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Set-Cookie', f'session={sid}; Max-Age=2592000; Path=/; HttpOnly; SameSite=Lax')
                self.end_headers()
                self.wfile.write(body)
            else:
                self.json({'ok': False})
            return

        if not user:
            self.send_response(401); self.end_headers(); return

        if path == '/upload':
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length)
            ct = self.headers.get('Content-Type', '')
            boundary = None
            for part in ct.split(';'):
                part = part.strip()
                if part.startswith('boundary='):
                    boundary = part[9:].strip('"').encode()
            fields = {}
            if boundary:
                delimiter = b'--' + boundary
                parts = raw.split(delimiter)
                for p in parts[1:]:
                    if p in (b'--\r\n', b'--', b'\r\n'):
                        continue
                    if p.startswith(b'\r\n'): p = p[2:]
                    if p.endswith(b'\r\n'): p = p[:-2]
                    if b'\r\n\r\n' not in p:
                        continue
                    hdr_raw, body = p.split(b'\r\n\r\n', 1)
                    hdr_text = hdr_raw.decode('utf-8', errors='replace')
                    name = ''
                    for seg in hdr_text.split(';'):
                        seg = seg.strip()
                        if seg.startswith('name='):
                            name = seg[5:].strip('"')
                    fields.setdefault(name, []).append(body)
            ftype = (fields.get('type', [b''])[0] or b'').decode() if isinstance(fields.get('type',[b''])[0], bytes) else fields.get('type',[''])[0]
            fdata = fields.get('file', [b''])[0]
            orig_name_raw = fields.get('filename', [b'file'])[0]
            orig_name = orig_name_raw.decode() if isinstance(orig_name_raw, bytes) else orig_name_raw
            fname = f"{ftype}_{uuid.uuid4().hex[:8]}"
            ext = os.path.splitext(orig_name)[-1].lower() or '.mp4'
            fpath = os.path.join(UPLOAD_DIR, fname+ext)
            with open(fpath, 'wb') as f:
                f.write(fdata if isinstance(fdata, bytes) else fdata.encode())
            self.json({'path': fpath})
        elif path == '/analyze_prokla':
            import zipfile, base64, re as _re, tempfile, shutil as _shutil2
            length = int(self.headers.get('Content-Length',0))
            params = json.loads(self.rfile.read(length))
            try:
                zip_bytes = base64.b64decode(params['zip_data'].split(',')[1])
                tmp = tempfile.mkdtemp()
                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                    zf.extractall(tmp)
                # Find index.html
                index_html = None
                for root, dirs, files in os.walk(tmp):
                    for fn in files:
                        if fn.lower() == 'index.html':
                            index_html = os.path.join(root, fn)
                            break
                    if index_html: break
                result = {}
                if index_html:
                    with open(index_html, 'r', encoding='utf-8', errors='ignore') as f:
                        html = f.read()
                    # Find current price
                    pm = _re.search(r'class="[^"]*(?:price-new|price--new|new-price|price_new|priceAndLabel)[^"]*"[^>]*>(?:<[^>]+>)*(\d+(?:[.,]\d+)?)', html, _re.IGNORECASE)
                    if not pm:
                        pm = _re.search(r'class="[^"]*price-new[^"]*">(\d+(?:[.,]\d+)?)', html, _re.IGNORECASE)
                    if pm: result['price'] = pm.group(1)
                    # Find currency
                    known = ['EUR','USD','PLN','RON','UAH','MDL','RSD','HUF','CZK','BGN','GBP','TRY']
                    for cur in known:
                        if cur in html:
                            result['currency'] = cur
                            break
                    if 'currency' not in result:
                        for sym, code in [('€','EUR'),('$','USD'),('£','GBP'),('₴','UAH'),('₽','RUB'),('zł','PLN'),('lei','RON'),('грн','UAH')]:
                            if sym in html:
                                result['currency'] = code
                                break
                    # Find offer name from title or h1
                    nm = _re.search(r'<title[^>]*>([^<]{3,60})</title>', html, _re.IGNORECASE)
                    if nm: result['offer_name'] = nm.group(1).strip()
                _shutil2.rmtree(tmp, ignore_errors=True)
                self.json(result)
            except Exception as e:
                self.json({'error': str(e)})

        elif path == '/process_prokla':
            import zipfile, base64, shutil, re as _re
            from collections import Counter as _Counter
            length = int(self.headers.get('Content-Length',0))
            params = json.loads(self.rfile.read(length))
            try:
                zip_bytes = base64.b64decode(params['zip_data'].split(',')[1])
                file_id = uuid.uuid4().hex[:8]
                tmp_dir = os.path.join(OUTPUT_DIR, 'prokla_tmp_' + file_id)
                os.makedirs(tmp_dir, exist_ok=True)
                extract_dir = os.path.join(tmp_dir, 'extracted')
                import io as _io
                with zipfile.ZipFile(_io.BytesIO(zip_bytes)) as z:
                    z.extractall(extract_dir)

                log_lines = []
                old_name = params.get('old_name','').strip()
                new_name = params.get('new_name','').strip()
                new_price = params.get('new_price','').strip()
                old_price_show = params.get('old_price','').strip()
                price_was = params.get('price_was','').strip()
                new_currency = params.get('currency','').strip()
                img_data = params.get('img_data','')
                img_ext = (params.get('img_ext','') or 'jpg').lower()
                prokla_type = params.get('prokla_type','static').strip()

                # Find main HTML file (index.html or any .html)
                index_html = None
                for root, _, files in os.walk(extract_dir):
                    for f in files:
                        if f == 'index.html':
                            index_html = os.path.join(root, f)
                            break
                    if index_html: break
                if not index_html:
                    for root, _, files in os.walk(extract_dir):
                        for f in files:
                            if f.endswith('.html'):
                                index_html = os.path.join(root, f)
                                break
                        if index_html: break
                if not index_html:
                    self.json({'error': 'HTML файл не найден в ZIP'}); return

                with open(index_html, 'r', encoding='utf-8', errors='ignore') as f:
                    html = f.read()

                                # Replace product name everywhere
                if old_name and new_name:
                    count = html.count(old_name)
                    html = html.replace(old_name, new_name)
                    # Also replace common suffix forms (e.g. Cimethroma -> DiabetOvera)
                    for suffix in ['a', 'om', 'u', 'e']:
                        old_form = old_name + suffix
                        if old_form in html:
                            html = html.replace(old_form, new_name + suffix)
                    log_lines.append(f'✅ Название: {old_name} → {new_name} ({count} замен)')

                # Replace current price with new price
                if new_price:
                    # Extract just the number from new_price (e.g. "39 EUR" -> "39")
                    new_price_num_m = _re.search(r'\d+(?:[.,]\d+)?', new_price)
                    new_price_num = new_price_num_m.group(0) if new_price_num_m else ''

                    if not price_was:
                        # Try with currency symbol first
                        cur_m = _re.search(r'([€$£₴₽]|[A-Z]{2,})', new_price)
                        cur_sym = cur_m.group(1) if cur_m else ''
                        if cur_sym:
                            pm = _re.search(r'\d+(?:[.,]\d+)?\s*' + _re.escape(cur_sym), html)
                            if not pm:
                                pm = _re.search(_re.escape(cur_sym) + r'\s*\d+(?:[.,]\d+)?', html)
                            if pm:
                                price_was = pm.group(0)
                        # Fallback: find number inside element with class containing price-new/price--new etc.
                        if not price_was:
                            pm = _re.search(r'class="[^"]*(?:price-new|price--new|new-price|price_new)[^"]*">(\d+(?:[.,]\d+)?)', html, _re.IGNORECASE)
                            if pm:
                                price_was = pm.group(1)

                    if price_was and new_price_num:
                        # Replace just the number part (price may have no currency in HTML)
                        count = html.count(price_was)
                        html = html.replace(price_was, new_price_num)
                        log_lines.append(f'✅ Новая цена: {price_was} → {new_price_num} ({count} замен)')
                    else:
                        log_lines.append(f'⚠️ Цена не найдена в HTML')

                # Replace old/strikethrough price
                if old_price_show and new_price:
                    old_price_num_m = _re.search(r'\d+(?:[.,]\d+)?', old_price_show)
                    old_price_num = old_price_num_m.group(0) if old_price_num_m else ''
                    if old_price_num:
                        pm = _re.search(r'class="[^"]*(?:price-old|price--old|old-price|price_old)[^"]*">(\d+(?:[.,]\d+)?)', html, _re.IGNORECASE)
                        if pm:
                            old_val = pm.group(1)
                            html = html.replace(old_val, old_price_num, 1)
                            log_lines.append(f'✅ Старая цена: {old_val} → {old_price_num}')

                # Replace currency
                if new_currency:
                    # Common currency codes/symbols that may appear in prokla HTML
                    known_currencies = ['EUR','USD','PLN','RON','UAH','MDL','RSD','HUF','CZK','BGN','TRY','GBP','CHF','SEK','NOK','DKK','lei','грн','zł','€','$','£','₴','₽']
                    cur_replaced = False
                    for cur in known_currencies:
                        if cur == new_currency:
                            continue
                        if cur in html:
                            # Only replace inside price blocks to avoid false positives
                            count = html.count(cur)
                            html = html.replace(cur, new_currency)
                            log_lines.append(f'✅ Валюта: {cur} → {new_currency} ({count} замен)')
                            cur_replaced = True
                            break
                    if not cur_replaced:
                        log_lines.append(f'⚠️ Текущая валюта не найдена, добавить {new_currency} вручную')

                with open(index_html, 'w', encoding='utf-8') as f:
                    f.write(html)

                # Replace product image
                new_fname = None
                if img_data:
                    img_bytes = base64.b64decode(img_data.split(',')[1])
                    img_dir = os.path.join(os.path.dirname(index_html), 'images')
                    os.makedirs(img_dir, exist_ok=True)

                    # Find PRODUCT image (not avatars/logos).
                    # Priority: images named product/prod/44/offer/tovar, or largest img in images/
                    img_exts_re = r'(?:png|jpg|jpeg|webp)'
                    prod_patterns = [
                        r'src=["\']([^"\']*images/(?:product|prod|44|offer|tovar|ofer)[^"\']*\.'+img_exts_re+r')["\']',
                        r'class=["\'][^"\']*(?:product|prod|offer|tovar)__img[^"\']*["\'][^>]*src=["\']([^"\']+\.'+img_exts_re+r')["\']',
                        r'src=["\'][^"\']*["\'][^>]*class=["\'][^"\']*(?:product|prod|offer|tovar)__img[^"\']*["\']',
                    ]
                    prod_img_ref = None
                    for pat in prod_patterns:
                        m = _re.search(pat, html, _re.IGNORECASE)
                        if m:
                            prod_img_ref = m.group(1)
                            break
                    # Fallback: largest image file in images/ folder (most likely product shot)
                    if not prod_img_ref:
                        img_files = []
                        if os.path.isdir(img_dir):
                            for f in os.listdir(img_dir):
                                if os.path.splitext(f)[1].lower().lstrip('.') in ('jpg','jpeg','png','webp'):
                                    fp = os.path.join(img_dir, f)
                                    img_files.append((os.path.getsize(fp), f))
                        if img_files:
                            img_files.sort(reverse=True)
                            prod_img_ref = 'images/' + img_files[0][1]

                    if prod_img_ref:
                        orig_fname = prod_img_ref.split('/')[-1]
                        new_fname = orig_fname.rsplit('.',1)[0] + '.' + img_ext
                        with open(os.path.join(img_dir, new_fname), 'wb') as f:
                            f.write(img_bytes)
                        if new_fname != orig_fname:
                            old = os.path.join(img_dir, orig_fname)
                            if os.path.exists(old): os.remove(old)
                        # Replace only this specific filename in HTML
                        html = html.replace(orig_fname, new_fname)
                        with open(index_html, 'w', encoding='utf-8') as f:
                            f.write(html)
                        log_lines.append(f'✅ Фото заменено: {orig_fname} → {new_fname}')
                    else:
                        new_fname = f'44.{img_ext}'
                        with open(os.path.join(img_dir, new_fname), 'wb') as f:
                            f.write(img_bytes)
                        log_lines.append(f'✅ Фото сохранено: {new_fname}')

                # Handle review photos
                review_action = params.get('review_photo_action', 'none')
                if review_action in ('replace', 'delete') and index_html:
                    with open(index_html, 'r', encoding='utf-8', errors='ignore') as f:
                        html_rv = f.read()

                    def is_avatar_img(img_tag, img_dir_path):
                        if _re.search(r'(?:class|id)=["\'][^"\']*(?:avatar|ava|profile|userpic|author-img|user-img|foto-user|commentator-img)[^"\']*["\']', img_tag, _re.IGNORECASE):
                            return True
                        w = _re.search(r'width=["\']?(\d+)', img_tag, _re.IGNORECASE)
                        h = _re.search(r'height=["\']?(\d+)', img_tag, _re.IGNORECASE)
                        if w and int(w.group(1)) <= 80: return True
                        if h and int(h.group(1)) <= 80: return True
                        src_m = _re.search(r'src=["\']([^"\']+)["\']', img_tag, _re.IGNORECASE)
                        if src_m and img_dir_path:
                            src_file = src_m.group(1).split('?')[0].split('/')[-1]
                            fpath = os.path.join(img_dir_path, src_file)
                            if os.path.exists(fpath) and os.path.getsize(fpath) < 15000:
                                return True
                        return False

                    # Find the new product filename to skip it
                    protected_fname = new_fname if new_fname else None

                    def process_img_tag(m):
                        tag = m.group(0)
                        if is_avatar_img(tag, img_dir):
                            return tag
                        # Skip the main product image
                        src_m = _re.search(r'src=["\']([^"\']+)["\']', tag, _re.IGNORECASE)
                        if src_m and protected_fname:
                            src_file = src_m.group(1).split('?')[0].split('/')[-1]
                            if src_file == protected_fname:
                                return tag
                        if review_action == 'delete':
                            return ''
                        else:
                            rv_src = f'images/{protected_fname}' if protected_fname else f'images/44.{img_ext}'
                            return _re.sub(r'(src=)["\'][^"\']*["\']', r'\1"' + rv_src + '"', tag)

                    html_rv = _re.sub(r'<img[^>]*>', process_img_tag, html_rv, flags=_re.IGNORECASE)

                    if review_action == 'delete':
                        log_lines.append('✅ Фото из отзывов удалены (аватарки сохранены)')
                    else:
                        log_lines.append('✅ Фото в отзывах заменены (аватарки сохранены)')
                    with open(index_html, 'w', encoding='utf-8') as f:
                        f.write(html_rv)

                # Replace phone mask
                phone_mask = params.get('phone_mask','').strip()
                if phone_mask and index_html:
                    with open(index_html, 'r', encoding='utf-8', errors='ignore') as f:
                        html3 = f.read()
                    # Try multiple patterns to find phone mask in HTML
                    mask_patterns = [
                        r'(\(\+\d+\)[A-Za-z0-9]+)',          # bare: (+381)099999999
                        r'mask["\']?\s*[:=]\s*["\'](\(\+\d+\)[A-Za-z0-9]+)["\']',  # mask="..." or mask: '...'
                        r'["\'](\(\+\d+\)[A-Za-z0-9]+)["\']', # quoted anywhere
                    ]
                    mask_match = None
                    for pat in mask_patterns:
                        m = _re.search(pat, html3, _re.IGNORECASE)
                        if m:
                            mask_match = m.group(1)
                            break
                    if mask_match:
                        html3 = html3.replace(mask_match, phone_mask)
                        with open(index_html, 'w', encoding='utf-8') as f:
                            f.write(html3)
                        log_lines.append(f'✅ Маска: {mask_match} → {phone_mask}')
                    else:
                        log_lines.append(f'⚠️ Маска телефона не найдена в HTML')

                # Pack ZIP
                out_zip = os.path.join(OUTPUT_DIR, f'prokla_{file_id}.zip')
                with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as zout:
                    for root, _, files in os.walk(extract_dir):
                        for fname in files:
                            fpath = os.path.join(root, fname)
                            arcname = os.path.relpath(fpath, extract_dir)
                            zout.write(fpath, arcname)

                # Save preview copy
                preview_dir = os.path.join(OUTPUT_DIR, f'preview_{file_id}')
                if os.path.exists(preview_dir):
                    shutil.rmtree(preview_dir)
                shutil.copytree(extract_dir, preview_dir)
                # Relative path to index.html from preview_dir (e.g. "mx-yundorix.rest/index.html")
                preview_index_rel = os.path.relpath(index_html, extract_dir).replace('\\','/')
                shutil.rmtree(tmp_dir)

                # Detect VSL and form anchor using already-read html
                is_vsl = bool(_re.search(r'<video(?![^>]*\bcontrols\b)[^>]*>', html, _re.IGNORECASE))
                form_m = _re.search(r'id=["\']([^"\']*(?:form|order|buy|zakaz|checkout)[^"\']*)["\']', html, _re.IGNORECASE)
                form_anchor = '#' + form_m.group(1) if form_m else ''

                log_lines.append('✅ ZIP готов!')
                fname_out = f'{new_name}_prokla.zip' if new_name else 'prokla_edited.zip'
                self.json({'file_id': file_id, 'filename': fname_out, 'log': ' '.join(log_lines), 'is_vsl': is_vsl, 'form_anchor': form_anchor, 'preview_index': preview_index_rel})
            except Exception as e:
                import traceback
                self.json({'error': str(e), 'log': traceback.format_exc()})
        elif path == '/add_project':
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            secret_json = data.get('content', '')
            try:
                parsed = json.loads(secret_json)
                # Support both "installed" and "web" client types
                info = parsed.get('installed') or parsed.get('web') or {}
                client_id = info.get('client_id', '')
                if not client_id:
                    self.json({'ok': False, 'error': 'Неверный файл — client_id не найден'}); return
                proj_id = 'proj_' + hashlib.md5(client_id.encode()).hexdigest()[:8]
                proj_name = data.get('name') or f'Проект {len(load_projects(user))+1}'
                secret_file = os.path.join(BASE_DIR, f'client_secret_{user}_{proj_id}.json')
                with open(secret_file, 'w') as f:
                    json.dump(parsed, f)
                projects = load_projects(user)
                projects[proj_id] = {'name': proj_name, 'file': secret_file, 'client_id': client_id}
                save_projects(user, projects)
                self.json({'ok': True, 'id': proj_id, 'name': proj_name})
            except Exception as e:
                self.json({'ok': False, 'error': str(e)})
        elif path == '/add_channel':
            length = int(self.headers.get('Content-Length', 0))
            ch_params = json.loads(self.rfile.read(length)) if length else {}
            proxy = ch_params.get('proxy', '').strip()
            force_manual = ch_params.get('force_manual', False)
            login_hint = ch_params.get('login_hint', '').strip()
            job_id = uuid.uuid4().hex[:8]
            UPLOAD_JOBS[job_id] = {'status':'pending','log':[],'channel':None,'auth_url':None,'proxy':proxy}
            is_local = self.client_address[0] in ('127.0.0.1', '::1') and not force_manual
            t = threading.Thread(target=add_channel_auth, args=(job_id, user, is_local, proxy, login_hint), daemon=True)
            t.start()
            self.json({'job_id': job_id})
        elif path == '/add_channel_code':
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length))
            job_id = data.get('job_id')
            raw = data.get('code', '').strip()
            flow_data = CHANNEL_AUTH_FLOWS.get(job_id)
            if not flow_data:
                self.json({'ok': False, 'error': 'Сессия не найдена'}); return
            try:
                # Extract code from URL or use raw value
                from urllib.parse import parse_qs as _parse_qs, urlparse as _urlparse2
                if raw.startswith('http'):
                    qs = _parse_qs(_urlparse2(raw).query)
                    code = qs.get('code', [raw])[0]
                else:
                    code = raw
                flow = flow_data['flow']
                import os as _os
                _os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
                flow.fetch_token(code=code)
                creds = flow.credentials
                _finish_channel_auth(job_id, creds, flow_data['user'], flow_data.get('proxy',''), flow_data.get('secret_file'))
                CHANNEL_AUTH_FLOWS.pop(job_id, None)
                self.json({'ok': True})
            except Exception as e:
                UPLOAD_JOBS[job_id]['status'] = 'error'
                UPLOAD_JOBS[job_id]['log'].append(f'❌ Ошибка: {str(e)}')
                self.json({'ok': False, 'error': str(e)})
        elif path == '/ai_generate':
            length = int(self.headers.get('Content-Length',0))
            params = json.loads(self.rfile.read(length))
            topic_raw = params.get('topic','')
            prompt = ''
            if topic_raw.startswith('ADS:'):
                parts = topic_raw[4:].split('|')
                cat = parts[0] if len(parts)>0 else ''
                lang = parts[1] if len(parts)>1 else 'English'
                topic = 'ADS'
                # Детальные боли и примеры по категориям
                import random as _r
                _seed = _r.randint(10000, 99999)

                cat_data = {
                    'Суставы':   ('joints/arthrosis/arthritis', ['Knees crack on stairs?','Cant get up in morning?','Fingers wont bend?','Hip hurts every step?','Joints swollen at night?','Cant bend to pick up?','Shoulder pain lifting arm?','Knees give out suddenly?']),
                    'Диабет':    ('diabetes/blood sugar', ['Sugar 12 every morning?','Feet numb at night?','Constant thirst again?','Tired after every meal?','Wounds wont heal?','Vision getting blurry?','Injections every day?','Sugar spikes ruining sleep?']),
                    'Гипертония':('high blood pressure/hypertension', ['Pressure 160 before rising?','Headache every morning?','Pills stopped working?','Heart pounds at night?','Dizzy standing up?','Ringing ears getting worse?','Stairs leave you breathless?','Stroke fear growing?']),
                    'Похудение': ('weight loss/obesity/slow metabolism', ['Same weight 3 months dieting?','Belly grows eating less?','Every diet has failed?','Hungry again in one hour?','Metabolism completely stopped?','Clothes one size bigger yearly?','Cravings destroy every attempt?']),
                    'Паразиты':  ('parasites/hidden infection', ['Bloated after every meal?','Rash with no clear reason?','Tired despite 9h sleep?','Stomach cramps at night?','Doctors find nothing?','Skin itching at night?','Grinding teeth in sleep?']),
                    'Простатит': ('prostatitis/prostate problems', ['Up 3x a night to urinate?','Burning every single time?','Stream so weak it takes 5min?','Pain when sitting at desk?','Never feel fully empty?','Pressure in groin all day?','Prostate cancer fear growing?']),
                    'Потенция':  ('erectile dysfunction/male performance', ['Failing in bed more often?','Confidence completely gone?','Partner losing patience?','Avoiding intimacy from fear?','Anxiety before every time?','Feeling less of a man?','Relationship at the edge?']),
                    'Цистит':    ('cystitis/bladder infection', ['Burning pain every time you go?','Need toilet every 20 minutes?','Infection back for 3rd time?','Antibiotics not working?','Lower abdomen pain all day?','Scared to go out without toilet?']),
                    'Зрение':    ('vision loss/eye problems', ['Everything blurrier monthly?','Eyes exhausted by noon?','Floaters increasing daily?','Night driving dangerous now?','Screen causes headache fast?','Glasses prescription changed again?']),
                    'Память':    ('memory loss/brain fog/dementia fear', ['Forget names immediately?','Lost keys 3 times today?','Brain fog all day long?','Hard to follow conversation?','Fear of early dementia?','Cant focus more than 10min?']),
                }

                topic_en, pain_list = cat_data.get(cat, cat_data['Суставы'])
                selected = _r.sample(pain_list, min(8, len(pain_list)))
                pains_str = ' | '.join(selected)

                prompt = (
                    f"You are a world-class Google Ads copywriter AND a medical expert. Session: {_seed}.\n\n"
                    f"TASK: Generate 15 headlines + 15 descriptions in {lang} language for: {topic_en}\n"
                    f"Specific pains to reference: {pains_str}\n\n"
                    "HEADLINES - STRICT RULES:\n"
                    "- MAXIMUM 39 characters (count spaces too) - NO EXCEPTIONS\n"
                    "- Every headline must reference the specific health problem ({topic_en})\n"
                    "- Each headline = different symptom or angle\n"
                    "- Mix: questions / provocations / fear triggers / 1-2 intriguing nativka headlines\n"
                    "- Reader must think: THIS IS EXACTLY MY PROBLEM\n"
                    "- FORBIDDEN: treatment, cure, herbs, without medicine, guaranteed\n"
                    "- GOOD examples style: 'Knees crack going up stairs?' / 'Can not sleep from joint pain?' / 'Hip hurts with every step?'\n"
                    "- BAD: vague phrases without clear health problem reference\n\n"
                    "DESCRIPTIONS - STRICT RULES:\n"
                    "- MAXIMUM 85 characters (count spaces too) - NO EXCEPTIONS\n"
                    "- Headlines = PAIN, Descriptions = SOLUTION (this is the formula)\n"
                    "- All 15 must be about SAME category - zero contradictions\n"
                    "- Vary the approach across 15 descriptions:\n"
                    "  Group 1 (desc 1-5): Social proof with numbers - X,000 people restored Y in Z days\n"
                    "  Group 2 (desc 6-10): Urgency - problem worsens every day without action\n"
                    "  Group 3 (desc 11-15): Solution + contrast (before suffering / after relief)\n"
                    "- Be aggressive and punchy - real ad copy, not gray generic text\n"
                    "- FORBIDDEN: money-back guarantee, treatment, cure, herbs\n\n"
                    f"OUTPUT FORMAT (write in {lang}, then hyphen, then Russian translation):\n"
                    "## TITLES:\n"
                    "1. [headline] - [Russian]\n2. [headline] - [Russian]\n3. [headline] - [Russian]\n"
                    "4. [headline] - [Russian]\n5. [headline] - [Russian]\n6. [headline] - [Russian]\n"
                    "7. [headline] - [Russian]\n8. [headline] - [Russian]\n9. [headline] - [Russian]\n"
                    "10. [headline] - [Russian]\n11. [headline] - [Russian]\n12. [headline] - [Russian]\n"
                    "13. [headline] - [Russian]\n14. [headline] - [Russian]\n15. [headline] - [Russian]\n"
                    "## DESCS:\n"
                    "1. [description] - [Russian]\n2. [description] - [Russian]\n3. [description] - [Russian]\n"
                    "4. [description] - [Russian]\n5. [description] - [Russian]\n6. [description] - [Russian]\n"
                    "7. [description] - [Russian]\n8. [description] - [Russian]\n9. [description] - [Russian]\n"
                    "10. [description] - [Russian]\n11. [description] - [Russian]\n12. [description] - [Russian]\n"
                    "13. [description] - [Russian]\n14. [description] - [Russian]\n15. [description] - [Russian]"
                )
            else:
                topic = topic_raw
                import random as _r3
                _seed3 = _r3.randint(10000,99999)
                prompt = (
                    f"You are a YouTube lifestyle vlogger. Session: {_seed3}.\n"
                    "Write a YouTube title and description IN ENGLISH ONLY about daily habits and personal experience.\n\n"
                    "MANDATORY RULES:\n"
                    "- NEVER mention: health, disease, diabetes, blood sugar, prostate, cancer, weight, fat, cholesterol, pressure, parasites, vision, memory, joints, stomach, pain, cure, treat, heal, secret, hidden, doctor, natural, remedy, medication, drug, miracle, breakthrough, guaranteed, manage, reverse, eliminate, boost, control\n"
                    "- Write about: morning routines, habits, productivity, sleep, energy, mindset, lifestyle experiments\n"
                    "- Style: first-person, personal story, conversational\n"
                    "- Title: max 60 chars\n"
                    "- Description: 2 sentences, friendly, no health claims\n\n"
                    "EXAMPLES (use this exact tone):\n"
                    "TITLE: I tried waking up at 5am for 30 days\n"
                    "TITLE: The one habit I stopped that changed everything\n"
                    "TITLE: My honest results after 60 days of this routine\n\n"
                    "Respond EXACTLY:\n"
                    "TITLE: [title]\n"
                    "DESCRIPTION: [description]"
                )
            body = json.dumps({
                'model': 'claude-haiku-4-5-20251001',
                'max_tokens': 3000,
                'messages': [{'role':'user','content':prompt}]
            }).encode()
            import urllib.request
            key = get_anthropic_key()
            req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=body, headers={
                'Content-Type':'application/json',
                'x-api-key': key,
                'anthropic-version':'2023-06-01'
            })
            try:
                with urllib.request.urlopen(req) as r:
                    result = json.loads(r.read())
                self.json({'text': result['content'][0]['text']})
            except Exception as e:
                print("AI ERROR:", str(e))
                self.json({"error": str(e)})
        elif path == '/start':
            length = int(self.headers.get('Content-Length',0))
            params = json.loads(self.rfile.read(length))
            job_id = uuid.uuid4().hex[:8]
            JOBS[job_id] = {'status':'pending','log':[],'files':[]}
            t = threading.Thread(target=process_video, args=(job_id, params), daemon=True)
            t.start()
            self.json({'job_id': job_id})
        elif path == '/yt_upload':
            length = int(self.headers.get('Content-Length',0))
            params = json.loads(self.rfile.read(length))
            job_id = uuid.uuid4().hex[:8]
            UPLOAD_JOBS[job_id] = {'status':'pending','log':[],'links':[]}
            t = threading.Thread(target=upload_to_youtube, args=(
                job_id, params['files'], params['title'],
                params.get('description',''), params.get('privacy','unlisted'),
                params.get('channel_id','auto'), user
            ), daemon=True)
            t.start()
            self.json({'job_id': job_id})
        elif path == '/mass_yt_upload':
            length = int(self.headers.get('Content-Length',0))
            params = json.loads(self.rfile.read(length))
            job_id = uuid.uuid4().hex[:8]
            MASS_UPLOAD_JOBS[job_id] = {'status':'pending','log':[],'sets':[],'total':0,'done':0}
            t = threading.Thread(target=mass_upload_to_youtube, args=(
                job_id, params['files'], params['n_sets'], params['title'],
                params.get('description',''), params.get('privacy','unlisted'), user
            ), daemon=True)
            t.start()
            self.json({'job_id': job_id})
        elif path == '/assign_project':
            length = int(self.headers.get('Content-Length',0))
            params = json.loads(self.rfile.read(length))
            ch_id = params['channel_id']
            proj_id = params['project_id']
            channels = load_channels(user)
            if ch_id in channels:
                channels[ch_id]['project_id'] = proj_id
                save_channels(user, channels)
                self.json({'ok': True})
            else:
                self.json({'ok': False, 'error': 'Канал не найден'})
        elif path == '/auto_upload':
            length = int(self.headers.get('Content-Length',0))
            params = json.loads(self.rfile.read(length))
            job_id = uuid.uuid4().hex[:8]
            MASS_UPLOAD_JOBS[job_id] = {'status':'pending','log':[],'sets':[],'total':0,'done':0}
            t = threading.Thread(target=auto_convert_and_upload, args=(
                job_id, params['src_video'], params.get('n_sets', 1),
                params.get('category','Видео'), params.get('privacy','unlisted'), user
            ), daemon=True)
            t.start()
            self.json({'job_id': job_id})
        elif path == '/ready_upload':
            length = int(self.headers.get('Content-Length',0))
            params = json.loads(self.rfile.read(length))
            job_id = uuid.uuid4().hex[:8]
            MASS_UPLOAD_JOBS[job_id] = {'status':'pending','log':[],'sets':[],'total':0,'done':0}
            t = threading.Thread(target=ready_upload_to_youtube, args=(
                job_id, params['files'], params['n_sets'],
                params.get('category',''), params.get('privacy','unlisted'), user
            ), daemon=True)
            t.start()
            self.json({'job_id': job_id})
        else:
            self.send_response(404); self.end_headers()

    def json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

if __name__ == '__main__':
    # Auto-update on startup
    try:
        import urllib.request as _ur2
        _url2 = 'https://raw.githubusercontent.com/Rodenom/videoeditor-panel/main/app.py'
        raise Exception('skip')  # temp disabled
        import re as _re2
        _nver2 = (_re2.search(rb'VERSION = "([^"]+)"', _new2) or [None,None])[1]
        if _nver2 and _nver2.decode() != VERSION:
            print(f"🔄 Авто-обновление {VERSION} → {_nver2.decode()}")
            with open(os.path.abspath(__file__), 'wb') as _f2:
                _f2.write(_new2)
            sys.exit(42)
    except Exception as _e2:
        pass
    if not shutil.which('ffmpeg'):
        print("❌ FFmpeg не найден. Установи: brew install ffmpeg-full")
        sys.exit(1)
    # client_secret.json не обязателен — байер добавляет проект через панель
    # Migrate old channels.json → channels_pavel.json
    old_ch = os.path.join(BASE_DIR, 'channels.json')
    new_ch = get_channels_file('pavel')
    if os.path.exists(old_ch) and not os.path.exists(new_ch):
        shutil.copy(old_ch, new_ch)
        print("✅ Каналы перенесены в channels_pavel.json")

    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
    port = 7777
    server = ThreadedHTTPServer(('0.0.0.0', port), Handler)
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = '127.0.0.1'
    print(f"\n🎬 Video Editor запущен!")
    print(f"👉 Твоя панель:    http://localhost:{port}")
    print(f"👉 Для друга:      http://{local_ip}:{port}")
    print(f"\nНажми Ctrl+C чтобы остановить\n")
    webbrowser.open(f'http://localhost:{port}')
    server.serve_forever()
