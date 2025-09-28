# TempX-Fresh

A Flask-based public file board for uploading, sharing, and managing files with auto-expiry and admin controls.

## Features
- Upload files (max 1GB each) via web interface
- Files auto-delete after 10 minutes unless marked permanent by admin
- Admin panel for file management (delete, make permanent)
- Real-time updates using Socket.IO
- Rate limiting to prevent abuse
- Basic authentication for admin actions
- Storage usage info for admins

## Usage

### Running Locally
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set environment variables (optional):
   - `SECRET_KEY` (default: `super-secret-key`)
   - `ADMIN_USER` (default: `admin`)
   - `ADMIN_PASS` (default: `admin123`)
3. Start the app:
   ```bash
   python app.py
   ```
   Or with Socket.IO support:
   ```bash
   gunicorn -w 4 --bind 0.0.0.0:5000 app:socketio
   ```

### Deployment
- See `render.yaml` for Render.com deployment configuration.
- Persistent uploads are stored in the `Uploads/` directory.

## File Structure
- `app.py` — Main Flask application
- `requirements.txt` — Python dependencies
- `render.yaml` — Render.com deployment config
- `files.db` — SQLite database for file metadata
- `templates/` — HTML templates (`index.html`, `admin.html`)
- `Uploads/` — Uploaded files

## Security & Limits
- Rate limiting: 5 uploads/minute per user
- Admin authentication via HTTP Basic Auth
- Files >10 minutes old auto-delete unless permanent
- Max file size: 1GB

## License
MIT
