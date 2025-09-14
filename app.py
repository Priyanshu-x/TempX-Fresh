import os
import uuid
import sqlite3
import shutil
from datetime import datetime, timedelta
from flask import Flask, request, render_template, send_file, redirect, url_for, flash
from flask_wtf import FlaskForm
from wtforms import FileField, SubmitField
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from apscheduler.schedulers.background import BackgroundScheduler
from flask_httpauth import HTTPBasicAuth
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'Uploads'
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'super-secret-key')
socketio = SocketIO(app, async_mode='gevent')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

auth = HTTPBasicAuth()
ADMIN_USER = os.getenv('ADMIN_USER', 'admin')
ADMIN_PASS = os.getenv('ADMIN_PASS', 'admin123')

limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["200 per day", "50 per hour"], storage_uri="memory://")

@auth.verify_password
def verify_password(username, password):
    return username == ADMIN_USER and password == ADMIN_PASS

def init_db():
    with sqlite3.connect('files.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS files
                     (id TEXT PRIMARY KEY, filename TEXT, upload_time TEXT, is_permanent INTEGER)''')
        conn.commit()

def delete_expired_files():
    with sqlite3.connect('files.db') as conn:
        c = conn.cursor()
        ten_minutes_ago = (datetime.now() - timedelta(minutes=10)).isoformat()
        c.execute("SELECT id, filename FROM files WHERE upload_time < ? AND is_permanent = 0", (ten_minutes_ago,))
        expired_files = c.fetchall()
        for file_id, filename in expired_files:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
            if os.path.exists(file_path):
                os.remove(file_path)
            c.execute("DELETE FROM files WHERE id = ?", (file_id,))
        conn.commit()
        socketio.emit('file_deleted', {'id': file_id})

scheduler = BackgroundScheduler()
scheduler.add_job(delete_expired_files, 'interval', minutes=1)
scheduler.start()

init_db()

class UploadForm(FlaskForm):
    file = FileField('File')
    submit = SubmitField('Upload')

@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(e):
    flash('File too large. Maximum size is 1GB.')
    return redirect(url_for('index'))

@app.errorhandler(429)
def ratelimit_handler(e):
    flash('Too many uploads. Please try again in a minute.')
    return redirect(url_for('index'))

@app.route('/')
def index():
    with sqlite3.connect('files.db') as conn:
        c = conn.cursor()
        c.execute("SELECT id, filename, upload_time FROM files WHERE is_permanent = 1 OR upload_time > ?",
                  ((datetime.now() - timedelta(minutes=10)).isoformat(),))
        files = c.fetchall()
    return render_template('index.html', files=files, form=UploadForm())

@app.route('/upload', methods=['POST'])
@limiter.limit("5 per minute")
def upload_file():
    form = UploadForm()
    if not form.validate_on_submit():
        flash('Invalid form submission')
        return redirect(url_for('index'))
    
    file = form.file.data
    if not file:
        flash('No file selected')
        return redirect(url_for('index'))
    
    total, used, free = shutil.disk_usage(app.config['UPLOAD_FOLDER'])
    if free < 2 * 1024 * 1024 * 1024:
        flash('Server storage low. Try again later.')
        return redirect(url_for('index'))
    
    file_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
    file.save(file_path)
    
    with sqlite3.connect('files.db') as conn:
        c = conn.cursor()
        upload_time = datetime.now().isoformat()
        c.execute("INSERT INTO files (id, filename, upload_time, is_permanent) VALUES (?, ?, ?, 0)",
                  (file_id, filename, upload_time))
        conn.commit()
    
    socketio.emit('new_file', {'id': file_id, 'filename': filename, 'upload_time': upload_time})
    
    flash('File uploaded successfully')
    return redirect(url_for('index'))

@app.route('/download/<file_id>')
def download_file(file_id):
    with sqlite3.connect('files.db') as conn:
        c = conn.cursor()
        c.execute("SELECT filename, upload_time, is_permanent FROM files WHERE id = ?", (file_id,))
        file_data = c.fetchone()
        if not file_data:
            flash('File not found or expired')
            return redirect(url_for('index'))
        
        filename, upload_time, is_permanent = file_data
        if not is_permanent and datetime.fromisoformat(upload_time) < datetime.now() - timedelta(minutes=10):
            flash('File has expired')
            return redirect(url_for('index'))
        
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
        if not os.path.exists(file_path):
            flash('File not found')
            return redirect(url_for('index'))
        
        return send_file(file_path, as_attachment=True, download_name=filename)

@app.route('/admin', methods=['GET', 'POST'])
@auth.login_required
def admin():
    with sqlite3.connect('files.db') as conn:
        c = conn.cursor()
        if request.method == 'POST':
            file_id = request.form.get('file_id')
            action = request.form.get('action')
            if action == 'delete':
                c.execute("SELECT id, filename FROM files WHERE id = ?", (file_id,))
                file_data = c.fetchone()
                if file_data:
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    c.execute("DELETE FROM files WHERE id = ?", (file_id,))
                    conn.commit()
                    socketio.emit('file_deleted', {'id': file_id})
                    flash('File deleted')
            elif action == 'make_permanent':
                c.execute("UPDATE files SET is_permanent = 1 WHERE id = ?", (file_id,))
                conn.commit()
                flash('File marked as permanent')
        
        c.execute("SELECT id, filename, upload_time, is_permanent FROM files")
        files = c.fetchall()
    
    total, used, free = shutil.disk_usage(app.config['UPLOAD_FOLDER'])
    storage_info = {
        'used': f'{used / (1024**3):.2f} GB',
        'free': f'{free / (1024**3):.2f} GB'
    }
    return render_template('admin.html', files=files, storage_info=storage_info)

if __name__ == '__main__':
    socketio.run(app, debug=True)