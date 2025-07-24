from flask import Flask, request, render_template, send_from_directory, redirect, url_for, jsonify
import yt_dlp
import os
import subprocess
import shutil
from werkzeug.utils import secure_filename
from datetime import datetime
import json
import torchaudio

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clave-secreta-por-defecto-cambiar-en-produccion')

# Configuración de la aplicación
PREMIUM_CODE = os.environ.get('PREMIUM_CODE', "123-456-789")
MAX_PLAYLISTS_FREE = 1
MAX_SONGS_FREE = 10
MAX_SEPARATIONS_FREE = 3

# Configuración de rutas seguras para Windows y Render
def safe_path(path):
    """Normaliza rutas para compatibilidad multiplataforma"""
    return path.replace('\\', '/').strip()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CORUTUBE_DIR = safe_path(os.path.join(BASE_DIR, 'corutube_descargas'))
INDIVIDUAL_FOLDER = safe_path(os.path.join(CORUTUBE_DIR, 'individuales'))
PROCESADAS_FOLDER = safe_path(os.path.join(CORUTUBE_DIR, 'procesadas'))
PLAYLIST_FOLDER = safe_path(os.path.join(CORUTUBE_DIR, 'playlists'))
CONFIG_FILE = safe_path(os.path.join(CORUTUBE_DIR, 'config.json'))

# Crear carpetas principales
os.makedirs(INDIVIDUAL_FOLDER, exist_ok=True)
os.makedirs(PROCESADAS_FOLDER, exist_ok=True)
os.makedirs(PLAYLIST_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = INDIVIDUAL_FOLDER
app.config['ALLOWED_EXTENSIONS'] = {'mp3'}

def load_config():
    """Carga la configuración desde el archivo JSON"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error al cargar configuración: {str(e)}")
    return {
        'premium': False,
        'last_playlist_date': None,
        'playlist_count': 0,
        'last_separation_date': None,
        'separation_count': 0
    }

def save_config(config):
    """Guarda la configuración en el archivo JSON"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def reset_daily_counts_if_needed(config):
    """Reinicia los contadores diarios si es necesario"""
    today = datetime.now().date().strftime('%Y-%m-%d')
    
    if config.get('last_playlist_date') != today:
        config['playlist_count'] = 0
        config['last_playlist_date'] = today
    
    if config.get('last_separation_date') != today:
        config['separation_count'] = 0
        config['last_separation_date'] = today
    
    return config

@app.route('/')
def index():
    """Página principal de la aplicación"""
    config = load_config()
    config = reset_daily_counts_if_needed(config)
    save_config(config)
    
    archivos = [f for f in os.listdir(INDIVIDUAL_FOLDER) if f.endswith('.mp3')]
    error = request.args.get('error')
    return render_template('index.html', archivos=archivos, premium=config['premium'], error=error)

@app.route('/activate_premium', methods=['POST'])
def activate_premium():
    """Activa la versión premium con un código"""
    code = request.form.get('code', '').strip()
    if code == PREMIUM_CODE:
        config = load_config()
        config['premium'] = True
        save_config(config)
        return jsonify({'success': True, 'message': '¡Versión Premium activada correctamente!'})
    return jsonify({'success': False, 'message': 'Código inválido. Intente nuevamente.'})

@app.route('/single_download', methods=['POST'])
def single_download():
    """Descarga un video individual de YouTube como MP3"""
    url = request.form.get('youtube_url', '').strip()
    if not url:
        return redirect(url_for('index', error="URL inválida"))

    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'outtmpl': safe_path(os.path.join(INDIVIDUAL_FOLDER, '%(title)s.%(ext)s')),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'ffmpeg_location': 'ffmpeg',
            'quiet': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            original_file = ydl.prepare_filename(info)
            
            # Renombrar a MP3 si es necesario
            if not original_file.endswith('.mp3'):
                new_file = os.path.splitext(original_file)[0] + '.mp3'
                os.rename(original_file, new_file)

        return redirect(url_for('index'))

    except Exception as e:
        error_msg = f"Error al descargar: {str(e)}"
        print(error_msg)
        return redirect(url_for('index', error=error_msg))

@app.route('/playlist_download', methods=['POST'])
def playlist_download():
    """Descarga una playlist completa de YouTube"""
    config = load_config()
    config = reset_daily_counts_if_needed(config)
    
    if not config['premium'] and config['playlist_count'] >= MAX_PLAYLISTS_FREE:
        return redirect(url_for('index', error=f"Límite diario alcanzado (máximo {MAX_PLAYLISTS_FREE} playlist por día)"))
        
    url = request.form.get('playlist_url', '').strip()
    if not url:
        return redirect(url_for('index', error="URL de playlist inválida"))

    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            playlist_title = info.get('title', 'playlist_sin_nombre').replace('/', '_').replace(' ', '_')
            playlist_path = safe_path(os.path.join(PLAYLIST_FOLDER, playlist_title))
            os.makedirs(playlist_path, exist_ok=True)

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': safe_path(os.path.join(playlist_path, '%(title)s.%(ext)s')),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'ffmpeg_location': 'ffmpeg',
            'quiet': True,
        }

        if not config['premium']:
            ydl_opts['playlistend'] = MAX_SONGS_FREE - 1
            config['playlist_count'] += 1
            save_config(config)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        return redirect(url_for('index'))

    except Exception as e:
        error_msg = f"Error al descargar playlist: {str(e)}"
        print(error_msg)
        return redirect(url_for('index', error=error_msg))

@app.route('/subir_y_separar', methods=['POST'])
def subir_y_separar():
    """Procesa un archivo de audio para separar pistas"""
    config = load_config()
    config = reset_daily_counts_if_needed(config)
    
    if not config['premium'] and config['separation_count'] >= MAX_SEPARATIONS_FREE:
        return redirect(url_for('index', error=f"Límite diario alcanzado (máximo {MAX_SEPARATIONS_FREE} separaciones por día)"))
    
    if 'archivo' not in request.files:
        return redirect(url_for('index', error="No se envió archivo"))

    archivo = request.files['archivo']
    if archivo.filename == '':
        return redirect(url_for('index', error="Archivo vacío"))

    stems_seleccionados = request.form.getlist('stems')
    if not stems_seleccionados:
        return redirect(url_for('index', error="Debes seleccionar al menos una pista"))

    # Validación para versión gratuita
    if not config['premium'] and any(stem in stems_seleccionados for stem in ['other', 'drums', 'bass']):
        return redirect(url_for('index', error="Función exclusiva para versión Premium"))

    try:
        # Guardar archivo subido
        filename = secure_filename(archivo.filename.replace(' ', '_'))
        filepath = safe_path(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        archivo.save(filepath)

        # Configurar comando Demucs
        comando = [
            'demucs',
            '--mp3',  # Forzar salida en MP3
            '--out', PROCESADAS_FOLDER,
            filepath
        ]

        # Modo de dos stems si solo se seleccionaron voces
        if stems_seleccionados == ['vocals']:
            comando.insert(1, '--two-stems')
            comando.insert(2, 'vocals')

        # Ejecutar Demucs
        result = subprocess.run(comando, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"Demucs error: {result.stderr}")

        # Procesar archivos resultantes
        nombre_base = os.path.splitext(filename)[0]
        output_dir = safe_path(os.path.join(PROCESADAS_FOLDER, 'htdemucs', nombre_base))
        destino_final = safe_path(os.path.join(PROCESADAS_FOLDER, nombre_base))
        os.makedirs(destino_final, exist_ok=True)

        # Mover solo los stems seleccionados
        stems_map = {
            'vocals': 'vocals.mp3',
            'drums': 'drums.mp3',
            'bass': 'bass.mp3',
            'other': 'other.mp3'
        }

        for stem in stems_seleccionados:
            if stem in stems_map:
                origen = safe_path(os.path.join(output_dir, stems_map[stem]))
                destino = safe_path(os.path.join(destino_final, stems_map[stem]))
                if os.path.exists(origen):
                    shutil.move(origen, destino)

        # Actualizar contador
        if not config['premium']:
            config['separation_count'] += 1
            save_config(config)

        # Limpieza
        shutil.rmtree(output_dir, ignore_errors=True)
        os.remove(filepath)

        return redirect(url_for('index'))

    except Exception as e:
        # Limpieza en caso de error
        if 'filepath' in locals() and os.path.exists(filepath):
            os.remove(filepath)
        error_msg = f"Error al procesar: {str(e)}"
        print(error_msg)
        return redirect(url_for('index', error=error_msg))

@app.route('/download/<path:filepath>')
def download_file(filepath):
    """Descarga un archivo procesado"""
    try:
        dirpath = safe_path(os.path.dirname(filepath))
        filename = safe_path(os.path.basename(filepath))
        return send_from_directory(dirpath, filename, as_attachment=True)
    except Exception as e:
        print(f"Error al descargar archivo: {str(e)}")
        return redirect(url_for('index', error="Archivo no encontrado"))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)