import os
import uuid
import shutil
import logging
from datetime import datetime, timedelta
from flask import Flask, request, render_template, send_file, redirect, url_for, flash
from flask_wtf import FlaskForm
from wtforms import FileField, SubmitField, StringField, PasswordField
from wtforms.validators import DataRequired, Length
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from apscheduler.schedulers.background import BackgroundScheduler
from flask_httpauth import HTTPBasicAuth
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from flask_moment import Moment

load_dotenv()

app = Flask(__name__)

app.config['UPLOAD_FOLDER'] = 'Uploads'
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'super-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///files.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
moment = Moment(app)
socketio = SocketIO(app, async_mode='gevent')

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logger.info(f"SECRET_KEY loaded: {'*****' if app.config['SECRET_KEY'] else 'Not Set (using default)'}")
logger.info(f"DATABASE_URL loaded: {app.config['SQLALCHEMY_DATABASE_URI']}")

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

auth = HTTPBasicAuth()
ADMIN_USER = os.getenv('ADMIN_USER', 'admin')
ADMIN_PASS = os.getenv('ADMIN_PASS', 'admin123')

limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["200 per day", "50 per hour"], storage_uri="memory://")

@auth.verify_password
def verify_password(username, password):
    return username == ADMIN_USER and password == ADMIN_PASS

class File(db.Model):
    id = db.Column(db.String, primary_key=True)
    filename = db.Column(db.String, nullable=False)
    upload_time = db.Column(db.String, nullable=False)
    is_permanent = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f'<File {self.filename}>'

def delete_expired_files():
    with app.app_context():
        ten_minutes_ago = datetime.now() - timedelta(minutes=15)
        expired_files = File.query.filter(File.upload_time < ten_minutes_ago.isoformat(), File.is_permanent == 0).all()
        for file_obj in expired_files:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_obj.id)
            if os.path.exists(file_path):
                os.remove(file_path)
            db.session.delete(file_obj)
            db.session.commit() # Commit deletion before emitting to ensure consistency
            socketio.emit('file_deleted', {'id': file_obj.id})

scheduler = BackgroundScheduler()
scheduler.add_job(delete_expired_files, 'interval', minutes=1)
scheduler.start()

with app.app_context():
    try:
        db.create_all()
        logger.info("Database tables created successfully.")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}", exc_info=True)

class UploadForm(FlaskForm):
    file = FileField('File')
    submit = SubmitField('Upload')

class AdminLoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=20)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6, max=100)])
    submit = SubmitField('Login')

@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(e):
    logger.warning(f"Request entity too large: {e}")
    flash('File too large. Maximum size is 1GB.')
    return redirect(url_for('index'))

@app.errorhandler(429)
def ratelimit_handler(e):
    logger.warning(f"Rate limit exceeded for IP: {get_remote_address()}")
    flash('Too many uploads. Please try again in a minute.')
    return redirect(url_for('index'))

@app.errorhandler(404)
def page_not_found(e):
    logger.warning(f"404 Not Found: {request.path}")
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    logger.error(f"500 Internal Server Error: {e}", exc_info=True)
    return render_template('500.html'), 500

@app.route('/')
def index():
    ten_minutes_ago = (datetime.now() - timedelta(minutes=10)).isoformat()
    files = File.query.filter((File.is_permanent == 1) | (File.upload_time > ten_minutes_ago)).all()
    # Convert upload_time strings to datetime objects for Flask-Moment
    for file_obj in files:
        file_obj.upload_time = datetime.fromisoformat(file_obj.upload_time)
    return render_template('index.html', files=files, form=UploadForm())

@app.route('/upload', methods=['POST'])
@limiter.limit("5 per minute")
def upload_file():
    form = UploadForm()
    if not form.validate_on_submit():
        logger.warning('Invalid form submission for file upload.')
        flash('Invalid form submission')
        return redirect(url_for('index'))
    
    file = form.file.data
    if not file:
        logger.warning('No file selected for upload.')
        flash('No file selected')
        return redirect(url_for('index'))
    
    MIN_FREE_SPACE_GB = int(os.getenv('MIN_FREE_SPACE_GB', 2)) # Default to 2 GB
    total, used, free = shutil.disk_usage(app.config['UPLOAD_FOLDER'])
    if free < MIN_FREE_SPACE_GB * 1024 * 1024 * 1024:
        logger.error(f'Server storage low. Free space: {free / (1024**3):.2f} GB. Required: {MIN_FREE_SPACE_GB} GB.')
        flash(f'Server storage low. Please try again later. Minimum free space required: {MIN_FREE_SPACE_GB} GB.')
        return redirect(url_for('index'))
    
    file_id = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
    try:
        file.save(file_path)
        upload_time = datetime.now().isoformat()
        new_file = File(id=file_id, filename=filename, upload_time=upload_time, is_permanent=0)
        db.session.add(new_file)
        db.session.commit()
        
        socketio.emit('new_file', {'id': file_id, 'filename': filename, 'upload_time': upload_time})
        logger.info(f'File {filename} ({file_id}) uploaded successfully.')
        flash('File uploaded successfully')
    except Exception as e:
        logger.error(f'Error uploading file {filename} ({file_id}): {e}')
        flash('Error uploading file. Please try again.')
    
    return redirect(url_for('index'))

@app.route('/download/<file_id>')
def download_file(file_id):
    file_obj = File.query.get(file_id)
    if not file_obj:
        logger.warning(f'Attempted download of non-existent or expired file: {file_id}')
        flash('File not found or expired')
        return redirect(url_for('index'))
    
    if not file_obj.is_permanent and datetime.fromisoformat(file_obj.upload_time) < datetime.now() - timedelta(minutes=10):
        logger.warning(f'Attempted download of expired file: {file_id}')
        flash('File has expired')
        return redirect(url_for('index'))
    
    filename = file_obj.filename
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
    if not os.path.exists(file_path):
        logger.error(f'File {file_id} found in DB but not on disk at {file_path}.')
        flash('File not found')
        return redirect(url_for('index'))
    
    logger.info(f'File {filename} ({file_id}) downloaded.')
    return send_file(file_path, as_attachment=True, download_name=filename)

@app.route('/admin', methods=['GET'])
@auth.login_required
def admin_panel():
    files = File.query.all()
    # Convert upload_time strings to datetime objects for Flask-Moment
    for file_obj in files:
        file_obj.upload_time = datetime.fromisoformat(file_obj.upload_time)
    total, used, free = shutil.disk_usage(app.config['UPLOAD_FOLDER'])
    storage_info = {
        'used': f'{used / (1024**3):.2f} GB',
        'free': f'{free / (1024**3):.2f} GB'
    }
    return render_template('admin.html', files=files, storage_info=storage_info)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    form = AdminLoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        if username == ADMIN_USER and password == ADMIN_PASS:
            flash('Logged in successfully.', 'success')
            return redirect(url_for('admin_panel'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('admin_login.html', form=form)

@app.route('/admin/manage', methods=['POST'])
@auth.login_required
def admin_manage():
    file_id = request.form.get('file_id')
    action = request.form.get('action')
    file_obj = File.query.get(file_id)
    if file_obj:
        if action == 'delete':
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f'Admin deleted file from disk: {file_obj.filename} ({file_id})')
            db.session.delete(file_obj)
            db.session.commit()
            socketio.emit('file_deleted', {'id': file_id})
            flash('File deleted')
            logger.info(f'Admin deleted file record: {file_obj.filename} ({file_id})')
        elif action == 'make_permanent':
            file_obj.is_permanent = 1
            db.session.commit()
            flash('File marked as permanent')
            logger.info(f'Admin marked file as permanent: {file_obj.filename} ({file_id})')
    return redirect(url_for('admin_panel'))

@app.route('/health')
def health_check():
    try:
        # Attempt to query the database to check connection
        db.session.query(File).first()
        return "OK", 200
    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        return "Error", 500

if __name__ == '__main__':
    socketio.run(app, debug=True)