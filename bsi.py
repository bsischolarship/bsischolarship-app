import os
from datetime import datetime
from functools import wraps
from io import BytesIO, StringIO

from flask import (
    Flask,
    render_template_string,
    request,
    redirect,
    url_for,
    session,
    flash,
    send_file,
    jsonify,
)
from flask_sqlalchemy import SQLAlchemy
from datetime import timezone, timedelta
WIB = timezone(timedelta(hours=7))

from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from sqlalchemy import func, text

# ============================================================
# LOAD ENV (.env)
# ============================================================

load_dotenv()

# ============================================================
# FLASK CONFIG
# ============================================================

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # safety limit for uploads

db = SQLAlchemy(app)

# ============================================================
# INIT DATABASE (Render + Local)
# ============================================================
def init_db():
    try:
        db.create_all()
        # default setting
        if not Setting.query.filter_by(key="allow_admin_signup").first():
            s = Setting(key="allow_admin_signup", value="false")
            db.session.add(s)
            db.session.commit()
        print("INIT_DB: OK")
    except Exception as e:
        print("INIT_DB ERROR:", e)

@app.route("/init-db")
def init_db_route():
    try:
        init_db()
        return "Database initialized", 200
    except Exception as e:
        return f"Error: {e}", 500


# ============================================================
# DATABASE MODELS
# ============================================================


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(255), nullable=False)
    student_id = db.Column(db.String(100))  # NIM
    phone = db.Column(db.String(50))
    faculty = db.Column(db.String(255))
    major = db.Column(db.String(255))
    campus = db.Column(db.String(255))  # Kampus / Universitas
    semester = db.Column(db.String(50))
    skills = db.Column(db.Text)  # Keahlian / minat utama
    profile_photo = db.Column(db.String(255))  # nama file foto profil
    role = db.Column(db.String(50), default="user")  # user / admin
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def set_password(self, pw: str) -> None:
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw: str) -> bool:
        return check_password_hash(self.password_hash, pw)


class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=False)


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(255), nullable=False)
    detail = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="logs")




class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100))  # kategori tiket
    attachment_path = db.Column(db.String(255))  # path relatif file gambar
    status = db.Column(db.String(50), default="open")  # open, in_progress, resolved, closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at = db.Column(db.DateTime)  # kapan tiket selesai (in_progress -> resolved)
    admin_note = db.Column(db.Text)

    # admin yang menangani tiket (opsional)
    assigned_admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    user = db.relationship("User", foreign_keys=[user_id], backref="tickets")
    assigned_admin = db.relationship("User", foreign_keys=[assigned_admin_id], backref="assigned_tickets")

    messages = db.relationship("TicketMessage", backref="ticket", lazy="dynamic")



class TicketMessage(db.Model):
    __tablename__ = "ticket_messages"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(WIB))
    is_read_admin = db.Column(db.Boolean, default=False)
    is_read_user = db.Column(db.Boolean, default=False)

    sender = db.relationship("User")


class StudentRecord(db.Model):
    """
    Riwayat prestasi & kegiatan mahasiswa.
    record_type: 'prestasi' atau 'kegiatan'
    Menyimpan juga 1 file lampiran (gambar/PDF) per record langsung di tabel ini.
    """

    __tablename__ = "student_records"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    record_type = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    level = db.Column(db.String(100))  # Tingkatan juara / level kegiatan
    year = db.Column(db.String(10))
    organizer = db.Column(db.String(255))
    description = db.Column(db.Text)
    file_name = db.Column(db.String(255))
    file_mime = db.Column(db.String(100))
    file_size = db.Column(db.Integer)
    file_data = db.Column(db.LargeBinary)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="records")


class ProgramForm(db.Model):
    """
    Form/kuesioner dinamis yang dikelola admin.
    Bisa berisi tautan ke Google Form atau form lain.
    """

    __tablename__ = "program_forms"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    icon = db.Column(db.String(10))
    description = db.Column(db.String(255))
    url = db.Column(db.String(500))  # Tautan form eksternal (jika ada)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    created_by_user = db.relationship(
        "User", backref="program_forms", foreign_keys=[created_by]
    )


class Post(db.Model):
    """
    Postingan kabar / news / dokumentasi kegiatan.
    category: 'news' atau 'dokumentasi' (bebas dipakai admin).
    """

    __tablename__ = "posts"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text)
    category = db.Column(db.String(50))  # news / dokumentasi / dll
    image_url = db.Column(db.String(500))
    video_url = db.Column(db.String(500))
    is_published = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    created_by_user = db.relationship(
        "User", backref="posts", foreign_keys=[created_by]
    )


class PostRegistration(db.Model):
    """
    Pendaftaran user ke sebuah postingan (event/program).
    """

    __tablename__ = "post_registrations"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")
    post = db.relationship("Post")
class PostComment(db.Model):
    """
    Komentar pada postingan, mendukung balasan (thread sederhana).
    """

    __tablename__ = "post_comments"

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("post_comments.id"), nullable=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    post = db.relationship("Post", backref="comments")
    user = db.relationship("User")
    parent = db.relationship("PostComment", remote_side=[id], backref="replies")


class PostReaction(db.Model):
    """
    Like / dislike pada postingan.
    """

    __tablename__ = "post_reactions"

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reaction_type = db.Column(db.String(20), nullable=False)  # like / dislike
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    post = db.relationship("Post", backref="reactions")
    user = db.relationship("User")


class PostBookmark(db.Model):
    """
    Menyimpan postingan yang di-bookmark oleh user.
    """

    __tablename__ = "post_bookmarks"

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    post = db.relationship("Post", backref="bookmarks")
    user = db.relationship("User")




# ============================================================
# HELPERS
# ============================================================


def get_setting(key: str, default: str = "false") -> str:
    s = Setting.query.filter_by(key=key).first()
    return s.value if s else default


def set_setting(key: str, value: str) -> None:
    s = Setting.query.filter_by(key=key).first()
    if not s:
        s = Setting(key=key, value=value)
        db.session.add(s)
    else:
        s.value = value
    db.session.commit()


def log_action(user_id: int | None, action: str, detail: str = "") -> None:
    db.session.add(ActivityLog(user_id=user_id, action=action, detail=detail))
    db.session.commit()


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return User.query.get(uid)

def format_ticket_number(ticket: "Ticket") -> str:
    """Generate human-readable ticket number: YYYYMMDD + 3-digit increment.
    Date uses GMT+7 (WIB) based on ticket.created_at.
    """
    dt = ticket.created_at
    if dt is None:
        dt = datetime.now(WIB)
    else:
        try:
            dt = dt.astimezone(WIB)
        except Exception:
            try:
                from datetime import timezone as _tz
                dt = dt.replace(tzinfo=_tz.utc).astimezone(WIB)
            except Exception:
                pass
    prefix = dt.strftime("%Y%m%d")
    return f"{prefix}{ticket.id:03d}"



# ============================================================
# AUTH DECORATORS
# ============================================================


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or user.role != "admin":
            flash("Anda tidak memiliki akses admin.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return wrapper


# ============================================================
# SUPER APP STYLE BASE HTML + THEME TOGGLE
# ============================================================

BASE_HTML = """
<!doctype html>
<html lang=\"id\">
<head>
  <meta charset=\"utf-8\">
  <title>{{ title or \"BSI Scholarship\" }}</title>
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1, maximum-scale=1\">
  <style>
    :root {
      --bg: #f3f4f6;
      --bg-soft: #e5e7eb;
      --card-bg: #ffffff;
      --primary: #0055a5; /* BSI blue */
      --primary-soft: rgba(0, 85, 165, 0.12);
      --primary-grad: linear-gradient(135deg, #0055a5, #00a3e0);
      --danger: #ef4444;
      --text-main: #111827;
      --text-muted: #6b7280;
      --border-soft: #e5e7eb;
      --radius-lg: 20px;
    }
    .theme-dark {
      --bg: #020617;
      --bg-soft: #020617;
      --card-bg: #020617;
      --primary: #0055a5;
      --primary-soft: rgba(0, 85, 165, 0.18);
      --primary-grad: linear-gradient(135deg, #0055a5, #00a3e0);
      --danger: #ef4444;
      --text-main: #e5e7eb;
      --text-muted: #9ca3af;
      --border-soft: rgba(148,163,184,0.4);
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif;
      background: var(--bg);
      color: var(--text-main);
      -webkit-font-smoothing: antialiased;
    }
    a { color: #0055a5; text-decoration: none; }
    a:hover { text-decoration: underline; }

    .theme-dark body {
      background: radial-gradient(circle at top, #1f2937 0, #020617 55%, #000 100%);
    }

    .shell { min-height: 100vh; }

    /* NAVBAR */
    .navbar {
      position: sticky;
      top: 0;
      z-index: 20;
      backdrop-filter: blur(14px);
      background: rgba(255,255,255,0.9);
      border-bottom: 1px solid var(--border-soft);
    }
    .theme-dark .navbar {
      background: rgba(15,23,42,0.9);
      border-bottom-color: rgba(148,163,184,0.35);
    }
    .navbar-inner {
      max-width: 100%;
      width: 100%;
      margin: 0;
      padding: 0.6rem 1.4rem;
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 0.55rem;
      flex: 0 0 auto;
    }
    .brand-logo {
      width: 30px;
      height: 30px;
      border-radius: 999px;
      background-image: var(--primary-grad);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.7rem;
      font-weight: 700;
      color: white;
      text-transform: uppercase;
    }
    .brand-text { display: flex; flex-direction: column; }
    .brand-title {
      font-size: 0.95rem;
      font-weight: 700;
      letter-spacing: 0.02em;
    }
    .brand-sub {
      font-size: 0.65rem;
      color: var(--text-muted);
    }

    .nav-links {
      display: flex;
      gap: 1.1rem;
      font-size: 0.85rem;
      align-items: center;
      justify-content: center;
      flex: 1 1 auto;
    }
    .nav-links a {
      color: var(--text-muted);
      font-weight: 500;
      position: relative;
      padding-bottom: 3px;
    }
    .nav-links a.active {
      color: var(--text-main);
    }
    .nav-links a.active::after {
      content: \"\";
      position: absolute;
      left: 0;
      bottom: 0;
      width: 100%;
      height: 2px;
      border-radius: 999px;
      background-image: var(--primary-grad);
    }

    .nav-user {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.8rem;
      margin-left: auto;
    }
    .avatar {
      width: 30px;
      height: 30px;
      border-radius: 999px;
      background: radial-gradient(circle at 30% 0, #facc15, #0055a5 55%, #0f172a 100%);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.85rem;
      font-weight: 700;
      color: #f9fafb;
      flex-shrink: 0;
    }
    .nav-user-meta {
      display: flex;
      flex-direction: column;
      max-width: 160px;
    }
    .nav-user-name {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      color: var(--text-main);
      font-weight: 600;
    }
    .nav-user-campus {
      font-size: 0.7rem;
      color: var(--text-muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0.45rem 0.9rem;
      border-radius: 999px;
      border: none;
      font-size: 0.78rem;
      font-weight: 600;
      cursor: pointer;
      background: transparent;
      color: var(--text-main);
    }
    .btn-primary {
      background-image: none;
      background: #0055a5;
      color: #ffffff;
      box-shadow: none;
    }
    .btn-primary:hover {
      filter: brightness(1.05);
    }
    .btn-chat {
      background: #8b5cf6;
      color: #ffffff;
    }
    .btn-chat:hover {
      background: #7c3aed;
      color: #ffffff;
    }
    .btn-ghost {
      background: transparent;
      color: var(--text-muted);
    }
    .btn-ghost:hover {
      background: var(--bg-soft);
    }
    .theme-dark .btn-ghost:hover {
      background: rgba(15,23,42,0.7);
      color: #e5e7eb;
    }
    .btn-danger {
      background: #ef4444;
      color: white;
      box-shadow: none;
    }
    .btn-icon {
      padding: 0.35rem 0.55rem;
      border-radius: 999px;
      background: var(--bg-soft);
      border: 1px solid var(--border-soft);
      cursor: pointer;
      font-size: 0.8rem;
    }
    .theme-dark .btn-icon {
      background: rgba(15,23,42,0.9);
      border-color: rgba(148,163,184,0.6);
      color: #e5e7eb;
    }

    .theme-toggle {
      display: inline-flex;
      align-items: center;
      gap: 0.15rem;
      font-size: 0.8rem;
    }

    .nav-toggle {
      display: none;
      border: none;
      background: transparent;
      font-size: 1.1rem;
      cursor: pointer;
      padding: 0.2rem 0.4rem;
    }

    /* PAGE LAYOUT */
    .page {
  max-width: 100%;
  width: 100%;
  margin: 0;
  padding: 1.4rem 1rem 1.8rem;
}
    .page-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 0.75rem;
      margin-bottom: 1.2rem;
    }
    .page-title {
      font-size: 1.25rem;
      font-weight: 700;
      letter-spacing: 0.01em;
    }
    .page-subtitle {
      font-size: 0.85rem;
      color: var(--text-muted);
      margin-top: 0.25rem;
    }

    .surface {
      background: var(--card-bg);
      border-radius: 24px;
      border: 1px solid var(--border-soft);
      box-shadow: 0 12px 28px rgba(15,23,42,0.06);
      padding: 1.2rem 1.1rem 1.4rem;
      margin-bottom: 1.3rem;
    }
    .theme-dark .surface {
      background: #020617;
      box-shadow: 0 24px 60px rgba(15,23,42,0.9);
      border-color: rgba(148,163,184,0.45);
    }

    .alert {
      padding: 0.65rem 0.9rem;
      border-radius: 999px;
      font-size: 0.8rem;
      margin-bottom: 0.9rem;
      border: 1px solid transparent;
    }
    .alert-success {
      background: #dcfce7;
      color: #166534;
      border-color: #4ade80;
    }
    .alert-danger {
      background: #fee2e2;
      color: #991b1b;
      border-color: #fca5a5;
    }
    .theme-dark .alert-success {
      background: rgba(22,163,74,0.16);
      color: #bbf7d0;
      border-color: rgba(34,197,94,0.65);
    }
    .theme-dark .alert-danger {
      background: rgba(239,68,68,0.16);
      color: #fecaca;
      border-color: rgba(248,113,113,0.65);
    }

    .form-card, .card {
      background: var(--card-bg);
      border-radius: 22px;
      padding: 1.2rem 1.1rem 1.4rem;
      box-shadow: 0 10px 22px rgba(15,23,42,0.05);
      border: 1px solid var(--border-soft);
      margin-bottom: 1.2rem;
    }
    .theme-dark .form-card, .theme-dark .card {
      background: rgba(15,23,42,0.96);
      box-shadow: 0 20px 45px rgba(15,23,42,0.9);
      border-color: rgba(148,163,184,0.5);
    }

    .auth-card {
      max-width: 520px;
      width: 100%;
      margin: 0 auto;
    }

    .form-group { margin-bottom: 0.9rem; }
    .form-label {
      font-size: 0.8rem;
      font-weight: 600;
      margin-bottom: 0.25rem;
      display: block;
      color: var(--text-main);
    }
    .form-input, .form-select, textarea.form-input {
      width: 100%;
      padding: 0.55rem 0.7rem;
      border-radius: 0.9rem;
      border: 1px solid #d1d5db;
      font-size: 0.9rem;
      background: #ffffff;
      color: var(--text-main);
    }
    .theme-dark .form-input, .theme-dark .form-select, .theme-dark textarea.form-input {
      background: rgba(15,23,42,0.9);
      border-color: rgba(55,65,81,0.9);
      color: #e5e7eb;
    }
    .form-input:focus, .form-select:focus, textarea.form-input:focus {
      outline: none;
      border-color: rgba(0,85,165,0.95);
      box-shadow: 0 0 0 1px rgba(0,85,165,0.25);
    }
    .form-help {
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 0.2rem;
    }

    /* DASHBOARD CARDS */
    .cards-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 0.9rem;
    }
    .menu-card {
      position: relative;
      background: var(--card-bg);
      border-radius: 20px;
      padding: 1rem 0.9rem;
      border: 1px solid var(--border-soft);
      cursor: pointer;
      transition: transform 0.08s ease, box-shadow 0.08s ease, border-color 0.08s ease;
      overflow: hidden;
    }
    .menu-card:hover {
      transform: translateY(-2px);
      box-shadow: 0 16px 30px rgba(15,23,42,0.08);
      border-color: rgba(0,85,165,0.5);
    }
    .card-icon {
      width: 36px;
      height: 36px;
      border-radius: 14px;
      background: var(--bg-soft);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.2rem;
      margin-bottom: 0.6rem;
    }
    .card-title {
      font-weight: 600;
      margin-bottom: 0.15rem;
      font-size: 0.9rem;
    }
    .card-text {
      font-size: 0.78rem;
      color: var(--text-muted);
    }

    .kpi-card {
      color: #ffffff;
    }
    .kpi-1 { background: linear-gradient(135deg, #0055a5, #00a3e0); }
    .kpi-2 { background: linear-gradient(135deg, #f97316, #facc15); }
    .kpi-3 { background: linear-gradient(135deg, #16a34a, #22c55e); }
    .kpi-card .card-title { color:#e5e7eb; }
    .kpi-card .kpi-value {
      font-size:1.6rem;
      font-weight:700;
      margin-top:0.3rem;
    }
    .kpi-card .kpi-sub {
      font-size:0.8rem;
      opacity:0.9;
      margin-top:0.1rem;
    }

    /* BADGES */
    .badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0.1rem 0.6rem;
      border-radius: 999px;
      font-size: 0.7rem;
      font-weight: 600;
      letter-spacing: 0.02em;
    }
    .badge-role-admin {
      background: rgba(0,85,165,0.12);
      color: #0055a5;
      border: 1px solid rgba(0,85,165,0.7);
    }
    .badge-role-user {
      background: rgba(148,163,184,0.12);
      color: #4b5563;
      border: 1px solid rgba(148,163,184,0.45);
    }
    .badge-status-active {
      background: rgba(22,163,74,0.16);
      color: #166534;
      border: 1px solid rgba(34,197,94,0.8);
    }
    .badge-status-inactive {
      background: rgba(239,68,68,0.16);
      color: #b91c1c;
      border: 1px solid rgba(248,113,113,0.85);
    }

    .badge-type-prestasi {
      background: rgba(251, 191, 36, 0.18);
      color: #92400e;
      border: 1px solid rgba(251, 191, 36, 0.7);
    }
    .badge-type-kegiatan {
      background: rgba(59, 130, 246, 0.16);
      color: #1d4ed8;
      border: 1px solid rgba(59, 130, 246, 0.7);
    }

    /* TABLE ADMIN */
    .table-surface {
      background: var(--card-bg);
      border-radius: 22px;
      border: 1px solid var(--border-soft);
      box-shadow: 0 16px 36px rgba(15,23,42,0.1);
      padding: 0.6rem 0.1rem 0.6rem;
      overflow: hidden;
    }
    .theme-dark .table-surface {
      background: rgba(15,23,42,0.95);
      box-shadow: 0 20px 45px rgba(15,23,42,0.9);
      border-color: rgba(148,163,184,0.4);
    }
    .table-scroll {
      overflow-x: auto;
      padding: 0 0.5rem 0.3rem;
    }
    table {
      border-collapse: collapse;
      width: 100%;
      font-size: 0.8rem;
      min-width: 720px;
    }
    th, td {
      padding: 0.55rem 0.7rem;
      border-bottom: 1px solid #e5e7eb;
      text-align: left;
      white-space: normal;
    }
    th {
      background: #f9fafb;
      font-weight: 600;
      font-size: 0.75rem;
      color: var(--text-muted);
      position: sticky;
      top: 0;
      z-index: 1;
    }
    tr:hover td { background: #f3f4f6; }
    .theme-dark th {
      background: rgba(15,23,42,0.95);
      border-bottom-color: rgba(31,41,55,0.9);
    }
    .theme-dark th, .theme-dark td {
      border-bottom-color: rgba(31,41,55,0.9);
    }
    .theme-dark tr:hover td {
      background: rgba(15,23,42,0.9);
    }

    /* ADMIN MOBILE LIST */
    .admin-list { display: none; }
    .admin-card {
      border-radius: 18px;
      background: var(--card-bg);
      border: 1px solid var(--border-soft);
      padding: 0.75rem 0.85rem;
      margin-bottom: 0.6rem;
      display: flex;
      flex-direction: column;
      gap: 0.2rem;
      box-shadow: 0 10px 24px rgba(15,23,42,0.06);
    }
    .theme-dark .admin-card {
      background: rgba(15,23,42,0.95);
      border-color: rgba(148,163,184,0.4);
      box-shadow: 0 18px 40px rgba(15,23,42,0.95);
    }
    .admin-card-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.75rem;
    }
    .admin-card-name {
      font-size: 0.9rem;
      font-weight: 600;
    }
    .admin-card-email {
      font-size: 0.75rem;
      color: var(--text-muted);
    }
    .admin-card-meta {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 0.3rem;
      font-size: 0.75rem;
      color: var(--text-muted);
    }

    /* STUDENT PORTFOLIO */
    .record-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 0.8rem;
    }
    .profile-two-col-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1rem;
    }
    @media (max-width: 1024px) {
      .profile-two-col-grid {
        grid-template-columns: 1fr;
      }
    }
    .record-card {
      border-radius: 18px;
      padding: 0.85rem 0.9rem;
      border: 1px solid var(--border-soft);
      box-shadow: 0 10px 26px rgba(15,23,42,0.08);
      position: relative;
      background: radial-gradient(circle at 0 0, rgba(0,85,165,0.08), transparent 60%),
                  radial-gradient(circle at 100% 100%, rgba(251,191,36,0.12), transparent 60%),
                  var(--card-bg);
    }
    .record-title {
      font-size: 0.9rem;
      font-weight: 600;
      margin-bottom: 0.2rem;
    }
    .record-meta {
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-bottom: 0.4rem;
    }
    .record-desc {
      font-size: 0.78rem;
      color: var(--text-main);
      margin-bottom: 0.4rem;
    }
    .record-actions {
      display: flex;
      justify-content: flex-end;
      gap: 0.35rem;
      margin-top: 0.1rem;
    }
    .btn-chip {
      border-radius: 999px;
      padding: 0.25rem 0.6rem;
      font-size: 0.68rem;
      border: none;
      cursor: pointer;
    }
    .btn-chip-danger {
      background: #ef4444;
      color: #ffffff;
    }

    /* MODAL */
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(15,23,42,0.6);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 40;
    }
    .modal-backdrop.active { display: flex; }
    .modal {
      background: var(--card-bg);
      border-radius: 20px;
      padding: 1.1rem 1rem 1.2rem;
      max-width: 520px;
      width: 100%;
      box-shadow: 0 24px 60px rgba(15,23,42,0.35);
      border: 1px solid var(--border-soft);
      max-height: 90vh;
      overflow: auto;
    }
    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.5rem;
      margin-bottom: 0.6rem;
    }
    .modal-title {
      font-size: 0.95rem;
      font-weight: 700;
    }
    .modal-close {
      border: none;
      background: transparent;
      font-size: 1rem;
      cursor: pointer;
      color: var(--text-muted);
    }

    
    /* CHAT MODAL */
    .chat-container {
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
    }
    .chat-ticket-number {
      font-size: 0.8rem;
      color: var(--text-muted);
    }
    .chat-messages {
      border-radius: 14px;
      border: 1px solid var(--border-soft);
      padding: 0.5rem 0.6rem;
      max-height: 260px;
      overflow-y: auto;
      background: var(--bg-soft);
      font-size: 0.78rem;
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
    }
    .chat-bubble {
      max-width: 82%;
      padding: 0.35rem 0.55rem;
      border-radius: 14px;
      line-height: 1.3;
      display: inline-flex;
      flex-direction: column;
      gap: 0.1rem;
    }
    .chat-bubble.me {
      margin-left: auto;
      background: var(--primary-soft);
      color: var(--primary);
    }
    .chat-bubble.other {
      margin-right: auto;
      background: #ffffff;
      color: var(--text-main);
      border: 1px solid var(--border-soft);
    }
    .chat-sender {
      font-weight: 600;
      font-size: 0.72rem;
    }
    .chat-text {
      white-space: pre-wrap;
      word-wrap: break-word;
    }
    .chat-time {
      font-size: 0.68rem;
      color: var(--text-muted);
      margin-top: 0.05rem;
      text-align: right;
    }
    .chat-input-row {
      display: flex;
      gap: 0.4rem;
      align-items: center;
    }
    .chat-input-row .form-input {
      min-width: 0;
    }
    .badge-unread {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 1.1rem;
      height: 1.1rem;
      padding: 0 0.2rem;
      margin-left: 0.25rem;
      border-radius: 999px;
      background: #ef4444;
      color: #ffffff;
      font-size: 0.65rem;
      font-weight: 700;
    }
/* NEWS CARDS */
    .news-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 1rem;
    }
    .news-card {
      border-radius: 18px;
      border: 1px solid var(--border-soft);
      padding: 0.9rem 0.95rem;
      box-shadow: 0 10px 26px rgba(15,23,42,0.08);
      background: var(--card-bg);
    }
    .news-title {
      font-size: 0.95rem;
      font-weight: 600;
      margin-bottom: 0.25rem;
    }
    .news-meta {
      font-size: 0.72rem;
      color: var(--text-muted);
      margin-bottom: 0.45rem;
    }
    .news-content {
      font-size: 0.8rem;
      color: var(--text-main);
      max-height: 4.5em;
      overflow: hidden;
    }

    /* RESPONSIVE */
    @media (max-width: 900px) {
      .nav-links { gap: 0.6rem; }
      .navbar-inner { padding-inline: 0.8rem; }
    }

    @media (max-width: 768px) {
      .navbar-inner { padding-inline: 0.7rem; }
      .page { padding-inline: 0.9rem; }
      .page-header { flex-direction: column; align-items: flex-start; }
      .cards-grid { grid-template-columns: 1fr 1fr; }
      .nav-user-name { max-width: 110px; }
    }

    @media (max-width: 540px) {
      .page { padding-inline: 0.85rem; }
      .cards-grid { grid-template-columns: 1fr; }
      .table-surface { display: none; }
      .admin-list { display: block; }

      .nav-links {
        position: absolute;
        top: 100%;
        left: 0;
        right: 0;
        padding: 0.5rem 0.85rem 0.85rem;
        background: rgba(255,255,255,0.98);
        border-bottom: 1px solid var(--border-soft);
        display: none;
        flex-direction: column;
        align-items: flex-start;
        gap: 0.45rem;
      }
      .theme-dark .nav-links { background: rgba(15,23,42,0.98); }
      body.nav-open .nav-links { display: flex; }

      .nav-toggle { display: inline-flex; }

      .nav-user-meta { max-width: 90px; }
    }
  
    /* Ticket cards & timeline */
    .ticket-ongoing-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 1rem;
    }
    .ticket-card {
      background: var(--card-bg);
      border-radius: 18px;
      padding: 0.9rem 0.95rem 1.1rem;
      border: 1px solid var(--border-soft);
      box-shadow: 0 8px 18px rgba(15,23,42,0.06);
      display: flex;
      flex-direction: column;
      gap: 0.55rem;
    }
    .theme-dark .ticket-card {
      background: rgba(15,23,42,0.96);
      box-shadow: 0 18px 40px rgba(15,23,42,0.85);
    }
    .ticket-card-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 0.75rem;
    }
    .ticket-title {
      font-size: 0.9rem;
      font-weight: 600;
      color: var(--text-main);
    }
    .ticket-meta {
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 0.1rem;
    }
    .ticket-body p {
      margin: 0;
      font-size: 0.8rem;
      color: var(--text-main);
    }
    .ticket-status-pill {
      padding: 0.25rem 0.6rem;
      border-radius: 999px;
      font-size: 0.72rem;
      font-weight: 600;
      border: 1px solid transparent;
      white-space: nowrap;
    }
    .ticket-status-pill.status-open {
      background: rgba(251, 191, 36, 0.15);
      color: #92400e;
      border-color: rgba(251, 191, 36, 0.7);
    }
    .ticket-status-pill.status-in_progress {
      background: rgba(59, 130, 246, 0.16);
      color: #1d4ed8;
      border-color: rgba(59, 130, 246, 0.7);
    }
    .ticket-status-pill.status-resolved {
      background: rgba(34, 197, 94, 0.16);
      color: #166534;
      border-color: rgba(34, 197, 94, 0.75);
    }
    .ticket-status-pill.status-closed {
      background: rgba(107, 114, 128, 0.14);
      color: #374151;
      border-color: rgba(107, 114, 128, 0.6);
    }

    .badge-status-open {
      background: rgba(251, 191, 36, 0.18);
      color: #92400e;
      border-radius: 999px;
      padding: 0.1rem 0.5rem;
      font-size: 0.72rem;
      border: 1px solid rgba(251, 191, 36, 0.7);
    }
    .badge-status-in_progress {
      background: rgba(59, 130, 246, 0.18);
      color: #1d4ed8;
      border-radius: 999px;
      padding: 0.1rem 0.5rem;
      font-size: 0.72rem;
      border: 1px solid rgba(59, 130, 246, 0.7);
    }
    .badge-status-resolved {
      background: rgba(34, 197, 94, 0.18);
      color: #166534;
      border-radius: 999px;
      padding: 0.1rem 0.5rem;
      font-size: 0.72rem;
      border: 1px solid rgba(34, 197, 94, 0.75);
    }
    .badge-status-closed {
      background: rgba(107, 114, 128, 0.16);
      color: #374151;
      border-radius: 999px;
      padding: 0.1rem 0.5rem;
      font-size: 0.72rem;
      border: 1px solid rgba(107, 114, 128, 0.6);
    }

    .ticket-timeline {
      display: flex;
      gap: 0.4rem;
      margin-top: 0.2rem;
    }
    .ticket-step {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      position: relative;
    }
    .ticket-step-dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      border: 2px solid var(--border-soft);
      background: #e5e7eb;
      position: relative;
      z-index: 1;
    }
    .ticket-step::before {
      content: "";
      position: absolute;
      top: 5px;
      left: -50%;
      width: 100%;
      height: 2px;
      background: #e5e7eb;
      z-index: 0;
    }
    .ticket-step:first-child::before {
      display: none;
    }
    .ticket-step-label {
      margin-top: 0.2rem;
      font-size: 0.68rem;
      color: var(--text-muted);
      text-align: center;
      white-space: nowrap;
    }
    .ticket-step-done .ticket-step-dot {
      background: #22c55e;
      border-color: #16a34a;
    }
    .ticket-step-done .ticket-step-label {
      color: #16a34a;
      font-weight: 600;
    }
    .ticket-step-current .ticket-step-dot {
      background: #3b82f6;
      border-color: #1d4ed8;
    }
    .ticket-step-current .ticket-step-label {
      color: #1d4ed8;
      font-weight: 600;
    }
    .ticket-step-future .ticket-step-dot {
      background: #e5e7eb;
      border-color: var(--border-soft);
    }

    .btn-sm {
      padding: 0.3rem 0.7rem;
      font-size: 0.75rem;
    }
    .btn-status-accept {
      background: rgba(34, 197, 94, 0.16);
      color: #166534;
      border-radius: 999px;
      border: 1px solid rgba(34, 197, 94, 0.8);
    }
    .btn-status-complete {
      background: rgba(59, 130, 246, 0.18);
      color: #1d4ed8;
      border-radius: 999px;
      border: 1px solid rgba(59, 130, 246, 0.8);
    }
    .btn-status-close {
      background: rgba(239, 68, 68, 0.18);
      color: #b91c1c;
      border-radius: 999px;
      border: 1px solid rgba(239, 68, 68, 0.85);
    }
    .btn-status-accept[disabled],
    .btn-status-complete[disabled],
    .btn-status-close[disabled] {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .filter-pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0.18rem 0.7rem;
      border-radius: 999px;
      background: var(--bg-soft);
      font-size: 0.76rem;
      color: var(--text-muted);
      border: 1px solid var(--border-soft);
      text-decoration: none;
    }
    .filter-pill-active {
      background: var(--primary-soft);
      color: var(--primary);
      border-color: rgba(0, 85, 165, 0.8);
    }
    .filter-row {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 0.5rem;
      margin-top: 0.6rem;
    }
    .filter-row-left {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.35rem;
      font-size: 0.8rem;
    }
    .filter-row-right {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
    }

    /* Responsive ticket tables */
    .tickets-table th.col-created { width: 10%; }
    .tickets-table th.col-ticket { width: 10%; }
    .tickets-table th.col-category { width: 8%; }
    .tickets-table th.col-user { width: 8%; }
    .tickets-table th.col-admin { width: 8%; }
    .tickets-table th.col-desc { width: 20%; }
    .tickets-table th.col-status { width: 8%; }
    .tickets-table th.col-completed { width: 10%; }
    .tickets-table th.col-notes { width: 6%; }
    .tickets-table th.col-actions { width: 14%; }

    .admin-tickets-table td,
    .admin-tickets-table th {
      white-space: normal;
    }

@media (max-width: 1024px) {
      .table-scroll {
        overflow-x: hidden;
      }
      table {
        min-width: 100% !important;
        font-size: 0.72rem;
      }
      th, td {
        white-space: normal;
      }
      .tickets-table td {
        vertical-align: top;
      }
      .tickets-table .btn,
      .tickets-table .btn-sm {
        font-size: 0.7rem;
        padding: 0.25rem 0.5rem;
      }
    }
</style>
  <script>
    (function() {
      function applyTheme(theme) {
        const root = document.documentElement;
        root.classList.remove('theme-dark');
        if (theme === 'dark') {
          root.classList.add('theme-dark');
        } else if (theme === 'auto') {
          const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
          if (prefersDark) root.classList.add('theme-dark');
        }
      }
      const saved = localStorage.getItem('sh_theme') || 'auto';
      window.__sh_theme__ = saved;
      window.addEventListener('DOMContentLoaded', function() {
        applyTheme(saved);
        const label = document.getElementById('theme-label');
        if (label) {
          label.textContent = saved === 'dark' ? 'Gelap' : (saved === 'light' ? 'Terang' : 'Otomatis');
        }
      });
      window.toggleTheme = function() {
        const current = window.__sh_theme__ || 'auto';
        const next = current === 'auto' ? 'dark' : (current === 'dark' ? 'light' : 'auto');
        window.__sh_theme__ = next;
        localStorage.setItem('sh_theme', next);
        applyTheme(next);
        const label = document.getElementById('theme-label');
        if (label) {
          label.textContent = next === 'dark' ? 'Gelap' : (next === 'light' ? 'Terang' : 'Otomatis');
        }
      };
    })();
    window.toggleNav = function() {
      document.body.classList.toggle('nav-open');
    };
    window.openModal = function(id) {
      var el = document.getElementById(id);
      if (el) el.classList.add('active');
    };
    window.closeModal = function(id) {
      var el = document.getElementById(id);
      if (el) el.classList.remove('active');
    };

    // Simple HTML escape for chat messages
    function shEscapeHtml(str) {
      if (!str) return '';
      return str.replace(/[&<>"']/g, function(c) {
        return {'&':'&amp;','<':'&lt;','>':'&gt','"':'&quot;',"'":'&#39;'}[c] || c;
      });
    }

    // Ticket chat state & helpers
    window.__ticketChatState = { ticketId: null, ticketNo: '', poll: null };

    window.openTicketChat = function(ticketId, ticketNo) {
      var st = window.__ticketChatState;
      st.ticketId = ticketId;
      st.ticketNo = ticketNo || '';
      var titleEl = document.getElementById('chat-ticket-number');
      if (titleEl) {
        titleEl.textContent = ticketNo ? ('Ticket ' + ticketNo) : '';
      }
      window.loadTicketMessages();
      openModal('modal-ticket-chat');
      if (st.poll) {
        clearInterval(st.poll);
      }
      st.poll = setInterval(window.loadTicketMessages, 4000);
    };

    window.closeTicketChat = function() {
      var st = window.__ticketChatState;
      if (st.poll) {
        clearInterval(st.poll);
        st.poll = null;
      }
      closeModal('modal-ticket-chat');
    };

    window.loadTicketMessages = function() {
      var st = window.__ticketChatState;
      if (!st.ticketId) return;
      fetch('/ticket/' + st.ticketId + '/messages')
        .then(function(r) { return r.json(); })
        .then(function(list) {
          var box = document.getElementById('chat-messages');
          if (!box) return;
          box.innerHTML = '';
          (list || []).forEach(function(m) {
            var wrapper = document.createElement('div');
            wrapper.className = 'chat-bubble ' + (m.me ? 'me' : 'other');
            var sender = document.createElement('div');
            sender.className = 'chat-sender';
            sender.textContent = m.sender || '';
            var text = document.createElement('div');
            text.className = 'chat-text';
            text.textContent = m.text || '';
            var time = document.createElement('div');
            time.className = 'chat-time';
            time.textContent = m.time || '';
            wrapper.appendChild(sender);
            wrapper.appendChild(text);
            wrapper.appendChild(time);
            box.appendChild(wrapper);
          });
          box.scrollTop = box.scrollHeight;
        })
        .catch(function(err) { console && console.warn && console.warn(err); });
    };

    window.sendTicketMessage = function() {
      var st = window.__ticketChatState;
      if (!st.ticketId) return;
      var input = document.getElementById('chat-input');
      if (!input) return;
      var msg = (input.value || '').trim();
      if (!msg) return;
      var form = new FormData();
      form.append('message', msg);
      fetch('/ticket/' + st.ticketId + '/send', { method: 'POST', body: form })
        .then(function(r) { return r.json(); })
        .then(function(res) {
          if (res && res.success) {
            input.value = '';
            window.loadTicketMessages();
          }
        })
        .catch(function(err) { console && console.warn && console.warn(err); });
    };
  
    // Ticket notes viewer
    window.openTicketNotes = function(ticketId) {
      if (!ticketId) return;
      fetch('/admin/tickets/' + ticketId + '/notes')
        .then(function(r) { return r.json(); })
        .then(function(res) {
          var titleEl = document.getElementById('ticket-notes-title');
          var bodyEl = document.getElementById('ticket-notes-body');
          if (titleEl) {
            var no = res && res.ticket_no ? res.ticket_no : '';
            titleEl.textContent = no ? ('Catatan Ticket ' + no) : 'Catatan Ticket';
          }
          if (bodyEl) {
            var notes = (res && res.notes) ? String(res.notes) : '';
            if (!notes.trim()) {
              bodyEl.innerHTML = "<p style='font-size:0.8rem;color:var(--text-muted);margin:0;'>Belum ada catatan admin.</p>";
            } else {
              var escaped = notes
                .replace(/&/g,'&amp;')
                .replace(/</g,'&lt;')
                .replace(/>/g,'&gt;');
              bodyEl.innerHTML = "<pre style='white-space:pre-wrap;font-size:0.8rem;margin:0;'>" + escaped + "</pre>";
            }
          }
          openModal('modal-ticket-notes');
        })
        .catch(function(err) { console && console.warn && console.warn(err); });
    };
</script>
</head>
<body>
  <div class=\"shell\">
    <div class=\"navbar\">
      <div class=\"navbar-inner\">
        <div class=\"brand\">
          <div class=\"brand-logo\">BSI</div>
          <div class=\"brand-text\">
            <div class=\"brand-title\">BSI Scholarship</div>
            <div class=\"brand-sub\">Portal Beasiswa Mahasiswa & Admin</div>
          </div>
        </div>
        <button class=\"nav-toggle\" type=\"button\" onclick=\"toggleNav()\">☰</button>
        <div class=\"nav-links\">
{% if admin_mode %}
    <a href='{{ url_for("admin_overview") }}'>Dashboard</a>
    <a href='{{ url_for("admin_users") }}'>Users</a>
    <a href='{{ url_for("admin_forms") }}'>Forms</a>
    <a href='{{ url_for("admin_posts") }}'>Posts</a>
    <a href='{{ url_for("admin_tickets") }}'>Tickets</a>
    <a href='{{ url_for("admin_raw_data") }}'>Data</a>
    <a href='{{ url_for("dashboard") }}' class='btn btn-ghost btn-sm' style='border:1px solid #0055a5;color:#0055a5;padding:0.35rem 1rem;border-radius:999px;'>Exit Admin</a>
{% else %}
    <a href='{{ url_for("dashboard") }}'>Home</a>
    <a href='{{ url_for("news_list") }}'>News</a>
    <a href='{{ url_for("profile") }}'>Profile</a>
    <a href='{{ url_for("tickets") }}'>Incident</a>
    {% if user.role=='admin' %}
      <a href='{{ url_for("admin_overview") }}'>Admin Panel</a>
    {% endif %}
{% endif %}
</div>
        <div class=\"nav-user\">
          <div class=\"theme-toggle\">
            <button class=\"btn-icon\" type=\"button\" onclick=\"toggleTheme()\">🌓</button>
            <span id=\"theme-label\" style=\"font-size:0.75rem;color:var(--text-muted);\">Auto</span>
          </div>
          {% if user %}
            {% if user.profile_photo %}
              <img src=\"{{ url_for('static', filename='uploads/profiles/' ~ user.profile_photo) }}\" class=\"avatar\" style=\"width:30px;height:30px;border-radius:999px;object-fit:cover;\">
            {% else %}
              <div class=\"avatar\">{{ user.full_name[:1] if user.full_name else 'U' }}</div>
            {% endif %}
            <div class=\"nav-user-meta\">
              <span class=\"nav-user-name\">{{ user.full_name }}</span>
              <span class=\"nav-user-campus\">{{ user.campus or '' }}</span>
            </div>
            <form method=\"post\" action=\"{{ url_for('logout') }}\" style=\"margin:0;\">
              <button class=\"btn btn-danger\" type=\"submit\">Keluar</button>
            </form>
          {% else %}
            <a href=\"{{ url_for('login') }}\" class=\"btn btn-ghost\">Masuk</a>
            <a href=\"{{ url_for('register') }}\" class=\"btn btn-primary\">Daftar</a>
          {% endif %}
        </div>
      </div>
    </div>

    <main class=\"page\">
      {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
          {% for category, message in messages %}
            <div class=\"alert alert-{{ 'danger' if category == 'danger' else 'success' }}\">
              {{ message }}
            </div>
          {% endfor %}
        {% endif %}
      {% endwith %}

      {{ body|safe }}

      <div class="modal-backdrop" id="modal-ticket-chat">
        <div class="modal">
          <div class="modal-header">
            <div class="modal-title">Percakapan Ticket</div>
            <button type="button" class="modal-close" onclick="closeTicketChat()">✕</button>
          </div>
          <div class="chat-container">
            <div id="chat-ticket-number" class="chat-ticket-number"></div>
            <div id="chat-messages" class="chat-messages"></div>
            <div class="chat-input-row">
              <input id="chat-input" class="form-input" placeholder="Tulis pesan..." onkeydown="if(event.key==='Enter'){event.preventDefault();sendTicketMessage();}">
              <button type="button" class="btn btn-primary btn-sm" onclick="sendTicketMessage()">Kirim</button>
            </div>
          </div>
        </div>
      </div>

      <div class="modal-backdrop" id="modal-ticket-notes">
        <div class="modal">
          <div class="modal-header">
            <div class="modal-title" id="ticket-notes-title">Catatan Ticket</div>
            <button type="button" class="modal-close" onclick="closeModal('modal-ticket-notes')">✕</button>
          </div>
          <div id="ticket-notes-body" style="max-height:300px;overflow:auto;padding:0.25rem 0.25rem 0.5rem 0.25rem;"></div>
        </div>
      </div>

    </main>
  </div>
</body>
</html>
"""


def render_page(body_html: str, **context):
    user = current_user()
    admin_mode = request.path.startswith("/admin")

    return render_template_string(BASE_HTML, admin_mode=admin_mode,
        body=body_html,
        user=user,
        **context,
    )


# ============================================================
# STATIC MENU ITEMS (DASAR) UNTUK MAHASISWA
# ============================================================

MENU_ITEMS = [
    {
        "slug": "lupa-absen",
        "title": "Lupa Mengisi Daftar Hadir",
        "icon": "📅",
        "description": "Ajukan permohonan jika Anda lupa mengisi daftar hadir kegiatan.",
    },
    {
        "slug": "tugas-pengganti",
        "title": "Tugas Pengganti",
        "icon": "📄",
        "description": "Kumpulkan tugas pengganti untuk kegiatan yang tidak dapat dihadiri.",
    },
    {
        "slug": "kehadiran-pembinaan",
        "title": "Kehadiran Pembinaan",
        "icon": "📋",
        "description": "Catat kehadiran pembinaan rutin beasiswa.",
    },
    {
        "slug": "pre-post-test",
        "title": "Pre dan Post Test",
        "icon": "✅",
        "description": "Akses form pre-test dan post-test pembinaan.",
    },
    {
        "slug": "midline-eval",
        "title": "Midline Evaluation",
        "icon": "📊",
        "description": "Isi evaluasi tengah program sebagai bahan monitoring.",
    },
]


# ============================================================
# ROUTES: AUTH
# ============================================================


@app.route("/register", methods=["GET", "POST"])
def register():
    allow_admin_signup = get_setting("allow_admin_signup", "false") == "true"

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        student_id = request.form.get("student_id", "").strip()
        phone = request.form.get("phone", "").strip()
        faculty = request.form.get("faculty", "").strip()
        major = request.form.get("major", "").strip()
        campus = request.form.get("campus", "").strip()
        semester = request.form.get("semester", "").strip()
        skills = request.form.get("skills", "").strip()
        role = "user"

        if allow_admin_signup and request.form.get("register_as_admin") == "on":
            role = "admin"

        if not full_name or not email or not password:
            flash("Nama lengkap, email, dan password wajib diisi.", "danger")
            return redirect(url_for("register"))

        if password != password2:
            flash("Konfirmasi password tidak sama.", "danger")
            return redirect(url_for("register"))

        existing = User.query.filter_by(email=email).first()
        if existing:
            flash("Email sudah terdaftar. Silakan masuk.", "danger")
            return redirect(url_for("login"))

        user = User(
            full_name=full_name,
            email=email,
            student_id=student_id,
            phone=phone,
            faculty=faculty,
            major=major,
            campus=campus,
            semester=semester,
            skills=skills,
            role=role,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        log_action(user.id, "register", f"Role={role}")
        flash("Pendaftaran berhasil. Silakan masuk.", "success")
        return redirect(url_for("login"))

    checkbox_admin_html = ""
    if allow_admin_signup:
        checkbox_admin_html = """
        <div class="form-group">
          <label class="form-label">Daftar sebagai Admin?</label>
          <label style="font-size:0.8rem;">
            <input type="checkbox" name="register_as_admin"> Ya, saya mendaftar sebagai admin.
          </label>
          <div class="form-help">Gunakan hanya untuk pengelola program beasiswa.</div>
        </div>
        """



    body = f"""
    <div style="min-height:70vh;display:flex;align-items:center;justify-content:center;padding:1rem;">
      <div class="form-card auth-card">
        <h1 class="page-title" style="font-size:1.2rem;margin-bottom:0.3rem;">Buat Akun</h1>
        <p class="page-subtitle" style="margin-bottom:0.9rem;">Registrasi mahasiswa & admin.</p>
        <form method="post">
          <div class="form-group">
            <label class="form-label">Nama Lengkap</label>
            <input name="full_name" class="form-input" required>
          </div>
          <div class="form-group">
            <label class="form-label">Email</label>
            <input type="email" name="email" class="form-input" required>
          </div>
          <div class="form-group">
            <label class="form-label">Password</label>
            <input type="password" name="password" class="form-input" required>
          </div>
          <div class="form-group">
            <label class="form-label">Ulangi Password</label>
            <input type="password" name="password2" class="form-input" required>
          </div>

          <hr style="margin: 1rem 0; border:none; border-top:1px dashed rgba(148,163,184,0.5);">

          <div class="form-group">
            <label class="form-label">NIM / Nomor Induk Mahasiswa</label>
            <input name="student_id" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">No. HP</label>
            <input name="phone" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Kampus / Universitas</label>
            <input name="campus" class="form-input" placeholder="contoh: Universitas BSI Jakarta">
          </div>
          <div class="form-group">
            <label class="form-label">Fakultas</label>
            <input name="faculty" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Program Studi / Jurusan</label>
            <input name="major" class="form-input">
          </div>
          <div class="form-group">
            <label class="form-label">Semester</label>
            <input name="semester" class="form-input" placeholder="contoh: 3">
          </div>
          <div class="form-group">
            <label class="form-label">Keahlian / Minat Utama</label>
            <textarea name="skills" class="form-input" style="min-height:60px;" placeholder="contoh: public speaking, desain grafis, data analysis"></textarea>
          </div>
          {checkbox_admin_html}

          <div style="margin-top:1.1rem; display:flex; justify-content:space-between; align-items:center; gap:0.5rem;">
            <button class="btn btn-primary" type="submit">Daftar</button>
            <a href="{url_for('login')}" style="font-size:0.8rem; color:#0055a5;">Sudah punya akun? Masuk</a>
          </div>
        </form>
      </div>
    </div>
    """
    return render_page(body, title="Daftar Akun", active_nav=None)




@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Email atau password salah.", "danger")
            return redirect(url_for("login"))

        if not user.is_active:
            flash("Akun Anda dinonaktifkan. Hubungi admin.", "danger")
            return redirect(url_for("login"))

        session["user_id"] = user.id
        log_action(user.id, "login")
        flash("Selamat datang kembali 👋", "success")
        return redirect(url_for("dashboard"))

    body = f"""
    <div style="min-height:70vh;display:flex;align-items:center;justify-content:center;padding:1rem;">
      <div class="form-card auth-card">
        <h1 class="page-title" style="font-size:1.2rem;margin-bottom:0.3rem;">Masuk</h1>
        <p class="page-subtitle" style="margin-bottom:0.9rem;">Gunakan email dan password terdaftar.</p>
        <form method="post">
          <div class="form-group">
            <label class="form-label">Email</label>
            <input type="email" name="email" class="form-input" required>
          </div>
          <div class="form-group">
            <label class="form-label">Password</label>
            <input type="password" name="password" class="form-input" required>
          </div>
          <div style="margin-top:1.1rem; display:flex; justify-content:space-between; align-items:center; gap:0.5rem;">
            <button class="btn btn-primary" type="submit">Masuk</button>
            <a href="{url_for('register')}" style="font-size:0.8rem; color:#0055a5;">Belum punya akun? Daftar</a>
          </div>
        </form>
      </div>
    </div>
    """
    return render_page(body, title="Masuk", active_nav=None)




@app.post("/logout")
def logout():
    uid = session.pop("user_id", None)
    if uid:
        log_action(uid, "logout")
    flash("Anda telah keluar.", "success")
    return redirect(url_for("login"))


# ============================================================
# DASHBOARD & MENU
# ============================================================


@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()

    # Static cards
    cards_html = ""
    for c in MENU_ITEMS:
        cards_html += f"""
        <div class='menu-card' onclick=\"window.location.href='{url_for('menu_detail', slug=c['slug'])}'\">
          <div class='card-icon'>{c['icon']}</div>
          <div class='card-title'>{c['title']}</div>
          <div class='card-text'>{c['description']}</div>
        </div>
        """

    # Dynamic forms dari admin
    dynamic_cards_html = ""
    forms = ProgramForm.query.filter_by(is_active=True).order_by(ProgramForm.created_at.desc()).all()
    for fobj in forms:
        icon = fobj.icon or "📝"
        href = url_for("form_detail", slug=fobj.slug)
        dynamic_cards_html += f"""
        <div class='menu-card' onclick=\"window.location.href='{href}'\">
          <div class='card-icon'>{icon}</div>
          <div class='card-title'>{fobj.title}</div>
          <div class='card-text'>{fobj.description or "Form & kuesioner beasiswa."}</div>
        </div>
        """

    body = f"""
    <div class=\"surface\">
      <div class=\"page-header\">
        <div>
          <h1 class=\"page-title\">Dashboard Mahasiswa</h1>
          <p class=\"page-subtitle\">Akses semua form & aktivitas BSI Scholarship dalam satu tampilan super app.</p>
        </div>
        <div>
          <a href=\"{url_for('profile')}\" class=\"btn btn-primary\">Lihat Profil</a>
        </div>
      </div>

      <h2 class=\"page-subtitle\" style=\"font-weight:600;margin-bottom:0.5rem;\">Menu Utama</h2>
      <div class=\"cards-grid\">
        {cards_html}
      </div>

      <h2 class=\"page-subtitle\" style=\"font-weight:600;margin:1.4rem 0 0.5rem;\">Form & Kuesioner dari Admin</h2>
      <div class=\"cards-grid\">
        {dynamic_cards_html or "<p style='font-size:0.8rem;color:var(--text-muted);'>Belum ada form khusus dari admin.</p>"}
      </div>
    </div>
    """
    return render_page(body, title="Dashboard", active_nav="home")


@app.route("/menu/<slug>")
@login_required
def menu_detail(slug):
    card = next((c for c in MENU_ITEMS if c["slug"] == slug), None)
    if not card:
        flash("Menu tidak ditemukan.", "danger")
        return redirect(url_for("dashboard"))

    log_action(session.get("user_id"), f"open_menu:{slug}", card["title"])

    body = f"""
    <div class=\"surface\">
      <div class=\"card\">
        <h1 class=\"page-title\">{card['title']}</h1>
        <p class=\"page-subtitle\">{card['description']}</p>
        <p class=\"card-text\" style=\"font-size:0.8rem;\">
          Halaman ini masih berupa placeholder. Nantinya bisa diarahkan ke Google Form
          atau form internal sesuai kebutuhan program.
        </p>
      </div>
    </div>
    """
    return render_page(body, title=card["title"], active_nav="home")


@app.route("/form/<slug>")
@login_required
def form_detail(slug):
    form_obj = ProgramForm.query.filter_by(slug=slug).first()
    if not form_obj or not form_obj.is_active:
        flash("Form tidak ditemukan atau tidak aktif.", "danger")
        return redirect(url_for("dashboard"))

    log_action(session.get("user_id"), f"open_form:{slug}", form_obj.title)

    open_btn = ""
    if form_obj.url:
        open_btn = f"<a href='{form_obj.url}' target='_blank' class='btn btn-primary'>Buka Form</a>"
    else:
        open_btn = "<p style='font-size:0.8rem;color:var(--text-muted);'>Tautan form belum diisi oleh admin.</p>"

    body = f"""
    <div class=\"surface\">
      <div class=\"card\">
        <h1 class=\"page-title\">{form_obj.title}</h1>
        <p class=\"page-subtitle\">{form_obj.description or "Form & kuesioner program beasiswa."}</p>
        <p class=\"card-text\" style=\"font-size:0.8rem;margin-top:0.6rem;\">
          Slug form: <strong>{form_obj.slug}</strong>
        </p>
        <div style=\"margin-top:1rem;\">
          {open_btn}
        </div>
      </div>
    </div>
    """
    return render_page(body, title=form_obj.title, active_nav="home")


# ============================================================
# PROFILE & PORTFOLIO
# ============================================================


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user()

    if request.method == "POST":
        user.full_name = request.form.get("full_name", "").strip() or user.full_name
        user.student_id = request.form.get("student_id", "").strip()
        user.phone = request.form.get("phone", "").strip()
        user.faculty = request.form.get("faculty", "").strip()
        user.major = request.form.get("major", "").strip()
        user.campus = request.form.get("campus", "").strip()
        user.semester = request.form.get("semester", "").strip()
        user.skills = request.form.get("skills", "").strip()

        # Foto profil
        file = request.files.get("profile_photo")
        if file and file.filename:
            from werkzeug.utils import secure_filename as _secure
            filename = _secure(file.filename)
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext in {"jpg", "jpeg", "png"}:
                upload_dir = os.path.join(app.root_path, "static", "uploads", "profiles")
                os.makedirs(upload_dir, exist_ok=True)
                final_name = f"user_{user.id}.{ext}"
                file_path = os.path.join(upload_dir, final_name)
                file.save(file_path)
                user.profile_photo = final_name

        db.session.commit()
        log_action(user.id, "update_profile")
        flash("Profil berhasil diperbarui.", "success")
        return redirect(url_for("profile"))

    prestasi_list = (
        StudentRecord.query.filter_by(user_id=user.id, record_type="prestasi")
        .order_by(StudentRecord.year.desc(), StudentRecord.created_at.desc())
        .all()
    )
    kegiatan_list = (
        StudentRecord.query.filter_by(user_id=user.id, record_type="kegiatan")
        .order_by(StudentRecord.year.desc(), StudentRecord.created_at.desc())
        .all()
    )

    # Ticket history for this user
    tickets_all = (
        Ticket.query.filter_by(user_id=user.id)
        .order_by(Ticket.created_at.desc())
        .all()
    )

    ticket_history_rows = ""
    for t in tickets_all:
        created = t.created_at.astimezone(WIB).strftime("%d %b %Y, %H:%M") if t.created_at else "-"
        updated = t.updated_at.astimezone(WIB).strftime("%d %b %Y, %H:%M") if t.updated_at else "-"
        status_label = t.status.replace("_", " ").title()
        last_note = (t.admin_note or "").splitlines()[-1] if t.admin_note else "-"
        ticket_no = format_ticket_number(t)
        ticket_history_rows += f"""<tr>
          <td>{ticket_no}</td>
          <td>{t.title}</td>
          <td><span class='badge badge-status-{t.status}'>{status_label}</span></td>
          <td>{last_note}</td>
          <td>{created}</td>
          <td>{updated}</td>
        </tr>"""

    ongoing_tickets = [t for t in tickets_all if t.status in ("open", "in_progress")]

    ongoing_cards = ""
    steps = ["open", "in_progress", "resolved", "closed"]
    for t in ongoing_tickets:
        created = t.created_at.astimezone(WIB).strftime("%d %b %Y, %H:%M") if t.created_at else "-"
        ticket_no = format_ticket_number(t)
        status_label = t.status.replace("_", " ").title()
        # build timeline
        current_index = steps.index(t.status) if t.status in steps else 0
        steps_html = ""
        for idx, s in enumerate(steps):
            label = s.replace("_", " ").title()
            if idx < current_index:
                cls = "done"
            elif idx == current_index:
                cls = "current"
            else:
                cls = "future"
            steps_html += f"<div class='ticket-step ticket-step-{cls}'><div class='ticket-step-dot'></div><div class='ticket-step-label'>{label}</div></div>"

        short_desc = (t.description or "").strip().replace("\n", " ")
        if len(short_desc) > 160:
            short_desc = short_desc[:160] + "..."

        ongoing_cards += f"""<div class='ticket-card'>
          <div class='ticket-card-header'>
            <div>
              <div class='ticket-title'>#{ticket_no} — {t.title}</div>
              <div class='ticket-meta'>Dibuat: {created}</div>
            </div>
            <div class='ticket-status-pill status-{t.status}'>{status_label}</div>
          </div>
          <div class='ticket-body'>
            <p>{short_desc}</p>
          </div>
          <div class='ticket-timeline'>
            {steps_html}
          </div>
        </div>"""

    prestasi_cards = ""
    for r in prestasi_list:
        lampiran_html = ""
        if r.file_name:
            lampiran_html = f"<div class='record-meta' style='margin-top:0.2rem;'><a href='{url_for('record_file', record_id=r.id)}' style='font-size:0.75rem;'>📎 Lihat lampiran</a></div>"
        desc_html = (r.description or "").replace("\n", "<br>")
        prestasi_cards += f"""
        <div class='record-card'>
          <div style='display:flex;justify-content:space-between;align-items:flex-start;gap:0.5rem;'>
            <span class='badge badge-type-prestasi'>Prestasi</span>
            <span class='record-meta'>{r.year or "-"}</span>
          </div>
          <div class='record-title'>{r.title}</div>
          <div class='record-meta'>
            Tingkat: {r.level or "-"} • Penyelenggara: {r.organizer or "-"}
          </div>
          <div class='record-desc'>{desc_html}</div>
          {lampiran_html}
          <div class='record-actions'>
            <form method='post' action='{url_for('profile_record_delete', record_id=r.id)}' onsubmit="return confirm('Hapus data prestasi ini?');">
              <button class='btn-chip btn-chip-danger' type='submit'>Hapus</button>
            </form>
          </div>
        </div>
        """

    kegiatan_cards = ""
    for r in kegiatan_list:
        lampiran_html = ""
        if r.file_name:
            lampiran_html = f"<div class='record-meta' style='margin-top:0.2rem;'><a href='{url_for('record_file', record_id=r.id)}' style='font-size:0.75rem;'>📎 Lihat lampiran</a></div>"
        desc_html = (r.description or "").replace("\n", "<br>")
        kegiatan_cards += f"""
        <div class='record-card'>
          <div style='display:flex;justify-content:space-between;align-items:flex-start;gap:0.5rem;'>
            <span class='badge badge-type-kegiatan'>Kegiatan</span>
            <span class='record-meta'>{r.year or "-"}</span>
          </div>
          <div class='record-title'>{r.title}</div>
          <div class='record-meta'>
            Peran/Tingkat: {r.level or "-"} • Penyelenggara: {r.organizer or "-"}
          </div>
          <div class='record-desc'>{desc_html}</div>
          {lampiran_html}
          <div class='record-actions'>
            <form method='post' action='{url_for('profile_record_delete', record_id=r.id)}' onsubmit="return confirm('Hapus data kegiatan ini?');">
              <button class='btn-chip btn-chip-danger' type='submit'>Hapus</button>
            </form>
          </div>
        </div>
        """

    # Avatar HTML: gunakan foto jika ada, kalau tidak inisial
    if user.profile_photo:
        avatar_html = f"<img src='{url_for('static', filename='uploads/profiles/' + user.profile_photo)}' class='avatar' style='width:55px;height:55px;border-radius:999px;object-fit:cover;'>"
    else:
        avatar_html = f"<div class='avatar' style='width:55px;height:55px;font-size:1.4rem;'>{(user.full_name or 'U')[:1]}</div>"

    body = f"""
    <div class="surface">
      <h1 class="page-title">Profil Mahasiswa</h1>
      <p class="page-subtitle">Profil singkat dan portofolio prestasi & kegiatan Anda di program BSI Scholarship.</p>

      <div class="card">
        <div style="display:flex;align-items:center;gap:1rem;">
          {avatar_html}
          <div>
            <h2 style="margin:0;font-size:1.1rem;">{user.full_name}</h2>
            <p style="margin:0;font-size:0.8rem;color:var(--text-muted);">{user.campus or '-'}</p>
          </div>
        </div>

        <div style="margin-top:1rem;font-size:0.85rem;">
          <div style="display:grid;grid-template-columns:150px auto;row-gap:0.2rem;">
            <div><strong>Email</strong></div><div>: {user.email}</div>
            <div><strong>NIM</strong></div><div>: {user.student_id or '-'}</div>
            <div><strong>Program Studi</strong></div><div>: {user.major or '-'}</div>
            <div><strong>Semester</strong></div><div>: {user.semester or '-'}</div>
            <div><strong>No HP</strong></div><div>: {user.phone or '-'}</div>
            <div><strong>Fakultas</strong></div><div>: {user.faculty or '-'}</div>
            <div><strong>Kampus</strong></div><div>: {user.campus or '-'}</div>
            <div><strong>Keahlian</strong></div><div>: {user.skills or '-'}</div>
          </div>
        </div>

        <div style="margin-top:1.2rem;">
          <button class="btn btn-primary" type="button" onclick="openModal('modal-edit-profile')">Perbarui Profil</button>
        </div>
      </div>

      <div class="profile-two-col-grid" style="margin-top:1.2rem;">
        <div class="form-card">
          <h2 class="page-title" style="font-size:1rem;">Riwayat Prestasi</h2>
          <p class="page-subtitle">Prestasi akademik/non-akademik lengkap dengan tingkatan, tahun, dan penyelenggara.</p>
          <div style="margin-top:0.8rem;display:flex;justify-content:flex-end;">
            <button class="btn btn-primary" type="button" onclick="openModal('modal-prestasi')">+ Tambah Prestasi</button>
          </div>
          <div style="margin-top:1.1rem;">
            <div class="record-grid">
              {prestasi_cards or "<p style='font-size:0.8rem;color:var(--text-muted);'>Belum ada prestasi yang tercatat.</p>"}
            </div>
          </div>
        </div>

        <div class="form-card">
          <h2 class="page-title" style="font-size:1rem;">Riwayat Kegiatan & Organisasi</h2>
          <p class="page-subtitle">Pengalaman organisasi, kepanitiaan, dan kegiatan pengembangan diri.</p>
          <div style="margin-top:0.8rem;display:flex;justify-content:flex-end;">
            <button class="btn btn-primary" type="button" onclick="openModal('modal-kegiatan')">+ Tambah Kegiatan</button>
          </div>
          <div style="margin-top:1.1rem;">
            <div class="record-grid">
              {kegiatan_cards or "<p style='font-size:0.8rem;color:var(--text-muted);'>Belum ada kegiatan yang tercatat.</p>"}
            </div>
          </div>
        </div>
      </div>


      <div class="form-card" style="margin-top:1.4rem;">
        <h2 class="page-title" style="font-size:1rem;">Riwayat Kendala Sistem Ticketing</h2>
        <p class="page-subtitle">Lihat progres laporan kendala sistem yang pernah Anda kirimkan.</p>

        <div class="ticket-ongoing-grid" style="margin-top:0.8rem;">
          {ongoing_cards or "<p style='font-size:0.8rem;color:var(--text-muted);'>Saat ini tidak ada kendala yang sedang diproses.</p>"}
        </div>

        <div class="table-surface" style="margin-top:1.2rem;">
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>No. Tiket</th>
                  <th>Judul</th>
                  <th>Status</th>
                  <th>Catatan Terakhir</th>
                  <th>Dibuat</th>
                  <th>Update Terakhir</th>
                </tr>
              </thead>
              <tbody>
                {ticket_history_rows or "<tr><td colspan='7' style='text-align:center;font-size:0.8rem;color:var(--text-muted);'>Belum ada tiket kendala yang tercatat.</td></tr>"}
              </tbody>
            </table>
          </div>
        </div>

        <div style="margin-top:0.8rem;text-align:right;">
          <a href="{url_for('tickets')}" class="btn btn-ghost btn-sm">Buka halaman Kendala Sistem &raquo;</a>
        </div>
      </div>
      <!-- Modal Edit Profil -->
      <div class="modal-backdrop" id="modal-edit-profile">
        <div class="modal">
          <div class="modal-header">
            <div class="modal-title">Perbarui Profil</div>
            <button type="button" class="modal-close" onclick="closeModal('modal-edit-profile')">✕</button>
          </div>

          <form method="post" enctype="multipart/form-data">
            <div class="form-group">
              <label class="form-label">Nama Lengkap</label>
              <input name="full_name" class="form-input" value="{user.full_name}" required>
            </div>

            <div class="form-group">
              <label class="form-label">Email (tidak bisa diubah)</label>
              <input class="form-input" value="{user.email}" disabled>
            </div>

            <div class="form-group">
              <label class="form-label">NIM / Nomor Induk Mahasiswa</label>
              <input name="student_id" class="form-input" value="{user.student_id or ''}">
            </div>

            <div class="form-group">
              <label class="form-label">No. HP</label>
              <input name="phone" class="form-input" value="{user.phone or ''}">
            </div>

            <div class="form-group">
              <label class="form-label">Kampus / Universitas</label>
              <input name="campus" class="form-input" value="{user.campus or ''}">
            </div>

            <div class="form-group">
              <label class="form-label">Fakultas</label>
              <input name="faculty" class="form-input" value="{user.faculty or ''}">
            </div>

            <div class="form-group">
              <label class="form-label">Program Studi / Jurusan</label>
              <input name="major" class="form-input" value="{user.major or ''}">
            </div>

            <div class="form-group">
              <label class="form-label">Semester</label>
              <input name="semester" class="form-input" value="{user.semester or ''}">
            </div>

            <div class="form-group">
              <label class="form-label">Keahlian / Minat Utama</label>
              <textarea name="skills" class="form-input" style="min-height:60px;">{user.skills or ""}</textarea>
            </div>

            <div class="form-group">
              <label class="form-label">Foto Profil</label>
              <input type="file" name="profile_photo" class="form-input" accept=".jpg,.jpeg,.png">
              <div class="form-help">Opsional, maks. 1 MB. Bentuk lingkaran seperti avatar Instagram.</div>
            </div>

            <div style="margin-top:1.1rem;display:flex;justify-content:flex-end;gap:0.5rem;">
              <button type="button" class="btn btn-ghost" onclick="closeModal('modal-edit-profile')">Batal</button>
              <button class="btn btn-primary" type="submit">Simpan Perubahan</button>
            </div>
          </form>
        </div>
      </div>

      <!-- Modal Tambah Prestasi -->
      <div class="modal-backdrop" id="modal-prestasi">
        <div class="modal">
          <div class="modal-header">
            <div class="modal-title">Tambah Prestasi</div>
            <button type="button" class="modal-close" onclick="closeModal('modal-prestasi')">✕</button>
          </div>

          <form method="post" action="{url_for('profile_record_add')}" enctype="multipart/form-data">
            <input type="hidden" name="record_type" value="prestasi">

            <div class="form-group">
              <label class="form-label">Nama Prestasi</label>
              <input name="title" class="form-input" placeholder="Contoh: Juara 1 Lomba Debat Nasional" required>
            </div>

            <div class="form-group">
              <label class="form-label">Tingkatan / Level</label>
              <input name="level" class="form-input" placeholder="Internasional/Nasional/Provinsi/Kampus/dll">
            </div>

            <div class="form-group">
              <label class="form-label">Tahun</label>
              <input name="year" class="form-input" placeholder="Contoh: 2025">
            </div>

            <div class="form-group">
              <label class="form-label">Penyelenggara</label>
              <input name="organizer" class="form-input" placeholder="Contoh: Kemendikbud, BSI, dll">
            </div>

            <div class="form-group">
              <label class="form-label">Deskripsi Singkat</label>
              <textarea name="description" class="form-input" style="min-height:60px;" placeholder="Ringkas capaian, peran, dan highlight prestasi."></textarea>
            </div>

            <div class="form-group">
              <label class="form-label">Lampiran (gambar/PDF, maks. 1 MB)</label>
              <input type="file" name="file" class="form-input" accept=".jpg,.jpeg,.png,.pdf">
              <div class="form-help">Opsional: sertifikat, piagam, dokumentasi.</div>
            </div>

            <div style="margin-top:1rem;display:flex;justify-content:flex-end;gap:0.5rem;">
              <button type="button" class="btn btn-ghost" onclick="closeModal('modal-prestasi')">Batal</button>
              <button class="btn btn-primary" type="submit">Simpan</button>
            </div>
          </form>
        </div>
      </div>

      <!-- Modal Tambah Kegiatan -->
      <div class="modal-backdrop" id="modal-kegiatan">
        <div class="modal">
          <div class="modal-header">
            <div class="modal-title">Tambah Kegiatan / Organisasi</div>
            <button type="button" class="modal-close" onclick="closeModal('modal-kegiatan')">✕</button>
          </div>

          <form method="post" action="{url_for('profile_record_add')}" enctype="multipart/form-data">
            <input type="hidden" name="record_type" value="kegiatan">

            <div class="form-group">
              <label class="form-label">Nama Kegiatan / Jabatan</label>
              <input name="title" class="form-input" placeholder="Contoh: Ketua Panitia Seminar Nasional" required>
            </div>

            <div class="form-group">
              <label class="form-label">Peran / Tingkatan</label>
              <input name="level" class="form-input" placeholder="Ketua, Wakil, Anggota, Volunteer, dll">
            </div>

            <div class="form-group">
              <label class="form-label">Tahun</label>
              <input name="year" class="form-input" placeholder="Contoh: 2025">
            </div>

            <div class="form-group">
              <label class="form-label">Penyelenggara</label>
              <input name="organizer" class="form-input" placeholder="Contoh: BEM, UKM, komunitas, dll">
            </div>

            <div class="form-group">
              <label class="form-label">Deskripsi Singkat</label>
              <textarea name="description" class="form-input" style="min-height:60px;" placeholder="Uraikan kegiatan, peran, dan dampaknya."></textarea>
            </div>

            <div class="form-group">
              <label class="form-label">Lampiran (gambar/PDF, maks. 1 MB)</label>
              <input type="file" name="file" class="form-input" accept=".jpg,.jpeg,.png,.pdf">
              <div class="form-help">Opsional: dokumentasi, sertifikat kepanitiaan, dsb.</div>
            </div>

            <div style="margin-top:1rem;display:flex;justify-content:flex-end;gap:0.5rem;">
              <button type="button" class="btn btn-ghost" onclick="closeModal('modal-kegiatan')">Batal</button>
              <button class="btn btn-primary" type="submit">Simpan</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    """
    return render_page(body, title="Profil", active_nav="profile")





@app.route("/profile/record/add", methods=["POST"])
@login_required
def profile_record_add():
    user = current_user()
    record_type = request.form.get("record_type", "prestasi")
    title = request.form.get("title", "").strip()
    if not title:
        flash("Judul tidak boleh kosong.", "danger")
        return redirect(url_for("profile"))

    level = request.form.get("level", "").strip()
    year = request.form.get("year", "").strip()
    organizer = request.form.get("organizer", "").strip()
    description = request.form.get("description", "").strip()

    file = request.files.get("file")
    file_name = None
    file_mime = None
    file_size = None
    file_data = None

    if file and file.filename:
        filename = secure_filename(file.filename)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        allowed_ext = {"jpg", "jpeg", "png", "pdf"}
        if ext not in allowed_ext:
            flash("Format file tidak diizinkan. Hanya jpg, jpeg, png, atau pdf.", "danger")
            return redirect(url_for("profile"))

        data = file.read()
        size = len(data or b"")
        if size > 1 * 1024 * 1024:
            flash("Ukuran file maksimal 1 MB.", "danger")
            return redirect(url_for("profile"))

        file_name = filename
        file_mime = file.mimetype or "application/octet-stream"
        file_size = size
        file_data = data

    rec = StudentRecord(
        user_id=user.id,
        record_type=record_type,
        title=title,
        level=level,
        year=year,
        organizer=organizer,
        description=description,
        file_name=file_name,
        file_mime=file_mime,
        file_size=file_size,
        file_data=file_data,
    )
    db.session.add(rec)
    db.session.commit()
    log_action(user.id, "add_record", f"{record_type}:{title}")
    flash("Data berhasil ditambahkan.", "success")
    return redirect(url_for("profile"))


@app.route("/profile/record/<int:record_id>/delete", methods=["POST"])
@login_required
def profile_record_delete(record_id: int):
    user = current_user()
    rec = StudentRecord.query.get_or_404(record_id)
    if rec.user_id != user.id and user.role != "admin":
        flash("Anda tidak berhak menghapus data ini.", "danger")
        return redirect(url_for("profile"))

    db.session.delete(rec)
    db.session.commit()
    log_action(user.id, "delete_record", f"{rec.record_type}:{rec.title}")
    flash("Data berhasil dihapus.", "success")
    return redirect(url_for("profile"))


@app.route("/record/<int:record_id>/file")
@login_required
def record_file(record_id: int):
    user = current_user()
    rec = StudentRecord.query.get_or_404(record_id)
    if rec.user_id != user.id and (not user or user.role != "admin"):
        flash("Anda tidak berhak mengakses lampiran ini.", "danger")
        return redirect(url_for("profile"))
    if not rec.file_data:
        flash("Lampiran tidak ditemukan.", "danger")
        return redirect(url_for("profile"))

    return send_file(
        BytesIO(rec.file_data),
        mimetype=rec.file_mime or "application/octet-stream",
        as_attachment=True,
        download_name=rec.file_name or "lampiran"
    )


# ============================================================
# ADMIN - USERS & SETTINGS & DASHBOARD & DATA
# ============================================================


@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()

    # Hitung aktivitas terakhir tiap user
    for u in users:
        last_log = ActivityLog.query.filter_by(user_id=u.id).order_by(ActivityLog.created_at.desc()).first()
        if last_log and last_log.created_at:
            u._last_active = last_log.created_at.astimezone(WIB).strftime("%d %b %Y, %H:%M")
        else:
            u._last_active = "-"

    table_rows = ""
    for u in users:
        status_badge = (
            "<span class='badge badge-status-active'>Aktif</span>"
            if u.is_active
            else "<span class='badge badge-status-inactive'>Nonaktif</span>"
        )
        role_badge = (
            "<span class='badge badge-role-admin'>Admin</span>"
            if u.role == "admin"
            else "<span class='badge badge-role-user'>User</span>"
        )
        created = u.created_at.astimezone(WIB).strftime("%d %b %Y") if u.created_at else ""
        table_rows += f"""
        <tr>
          <td>{u.full_name}</td>
          <td>{u.email}</td>
          <td>{u.student_id or '-'}</td>
          <td>{u.campus or '-'}</td>
          <td>{u.major or '-'}</td>
          <td>{role_badge}</td>
          <td>{status_badge}</td>
          <td>{created}</td>
          <td><a href='{url_for('admin_user_edit', user_id=u.id)}' style='color:#0055a5;'>Kelola</a></td>
          <td>{u._last_active}</td>
          <td><a href='{url_for('admin_user_logs', user_id=u.id)}' style='color:#0055a5;'>Riwayat</a></td>
        </tr>
        """

    mobile_cards = ""
    for u in users:
        status_text = "Aktif" if u.is_active else "Nonaktif"
        status_class = "badge-status-active" if u.is_active else "badge-status-inactive"
        role_class = "badge-role-admin" if u.role == "admin" else "badge-role-user"
        created = u.created_at.astimezone(WIB).strftime("%d %b %Y") if u.created_at else ""
        campus = u.campus or "-"
        mobile_cards += f"""
        <div class="admin-card">
          <div class="admin-card-top">
            <div>
              <div class="admin-card-name">{u.full_name}</div>
              <div class="admin-card-email">{u.email}</div>
              <div class="admin-card-email" style="margin-top:0.1rem;">Kampus: {campus}</div>
            </div>
            <div style="display:flex; flex-direction:column; gap:0.25rem; align-items:flex-end;">
              <span class="badge {role_class}">{u.role.title()}</span>
              <span class="badge {status_class}">{status_text}</span>
            </div>
          </div>
          <div class="admin-card-meta">
            <span>NIM: {u.student_id or '-'}</span>
            <span style="font-size:0.72rem;">{created}</span>
          </div>
          <div class="admin-card-actions" style="margin-top:0.25rem;">
            <a href="{url_for('admin_user_edit', user_id=u.id)}">Kelola akun</a>
          </div>
        </div>
        """

    body = f"""
    <div class=\"surface\">
      <div class=\"page-header\">
        <div>
          <h1 class=\"page-title\">Admin — Manajemen User</h1>
          <p class=\"page-subtitle\">Kelola akun mahasiswa dan admin.</p>
        </div>
        <div>
          <a href=\"{url_for('register')}\" class=\"btn btn-primary\">Tambah User Baru</a>
        </div>
      </div>

      <div class=\"table-surface\">
        <div class=\"table-scroll\">
          <table>
            <thead>
              <tr>
                <th>Nama</th>
                <th>Email</th>
                <th>NIM</th>
                <th>Kampus</th>
                <th>Prodi</th>
                <th>Role</th>
                <th>Status</th>
                <th>Dibuat</th>
                <th>Aksi</th>
                <th>Last Aktif</th>
                <th>Riwayat</th>
              </tr>
            </thead>
            <tbody>
              {table_rows}
            </tbody>
          </table>
        </div>
      </div>

      <div class=\"admin-list\">
        {mobile_cards}
      </div>
    </div>
    """
    return render_page(body, title="Admin - Users", active_nav="admin_users")


@app.route("/admin/users/<int:user_id>", methods=["GET", "POST"])
@login_required
@admin_required
def admin_user_edit(user_id: int):
    user_obj = User.query.get_or_404(user_id)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "delete":
            log_action(current_user().id, "admin_delete_user", user_obj.email)
            db.session.delete(user_obj)
            db.session.commit()
            flash("User berhasil dihapus.", "success")
            return redirect(url_for("admin_users"))

        user_obj.full_name = request.form.get("full_name", "").strip() or user_obj.full_name
        user_obj.email = request.form.get("email", "").strip().lower() or user_obj.email
        user_obj.student_id = request.form.get("student_id", "").strip()
        user_obj.phone = request.form.get("phone", "").strip()
        user_obj.faculty = request.form.get("faculty", "").strip()
        user_obj.major = request.form.get("major", "").strip()
        user_obj.campus = request.form.get("campus", "").strip()
        user_obj.semester = request.form.get("semester", "").strip()
        user_obj.skills = request.form.get("skills", "").strip()
        user_obj.role = request.form.get("role", "user")
        user_obj.is_active = request.form.get("is_active") == "on"

        if request.form.get("reset_password"):
            new_pw = request.form.get("new_password", "").strip()
            if new_pw:
                user_obj.set_password(new_pw)

        db.session.commit()
        log_action(current_user().id, "admin_update_user", user_obj.email)
        flash("Data user berhasil diperbarui.", "success")
        return redirect(url_for("admin_user_edit", user_id=user_obj.id))

    checked = "checked" if user_obj.is_active else ""
    role_user_selected = "selected" if user_obj.role == "user" else ""
    role_admin_selected = "selected" if user_obj.role == "admin" else ""

    last_log = (
        ActivityLog.query.filter_by(user_id=user_obj.id)
        .order_by(ActivityLog.created_at.desc())
        .first()
    )
    last_access_str = last_log.created_at.astimezone(WIB).strftime("%d %b %Y, %H:%M") if last_log else "-"
    logs = (
        ActivityLog.query.filter_by(user_id=user_obj.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(30)
        .all()
    )

    log_items = ""
    for lg in logs:
        ts = lg.created_at.astimezone(WIB).strftime("%d %b %Y, %H:%M") if lg.created_at else "-"
        detail = f" — {lg.detail}" if lg.detail else ""
        log_items += f"<li style='font-size:0.78rem;margin-bottom:0.25rem;'><strong>{ts}</strong> • {lg.action}{detail}</li>"

    body = f"""
    <div class=\"surface\">
      <div class=\"page-header\">
        <div>
          <h1 class=\"page-title\">Kelola Akun</h1>
          <p class=\"page-subtitle\">Edit data, role, status akun, dan lihat riwayat aktivitas user.</p>
        </div>
        <div style=\"display:flex;gap:0.5rem;\">
          <a href=\"{url_for('admin_users')}\" class=\"btn btn-ghost\">Kembali ke Daftar User</a>
        </div>
      </div>

      <div class=\"form-card\">
        <div style=\"display:flex;justify-content:space-between;align-items:center;margin-bottom:0.8rem;\">
          <div>
            <div style=\"font-size:0.9rem;font-weight:600;\">{user_obj.full_name}</div>
            <div style=\"font-size:0.8rem;color:var(--text-muted);\">{user_obj.email}</div>
            <div style=\"font-size:0.75rem;color:var(--text-muted);margin-top:0.2rem;\">Last akses: {last_access_str}</div>
          </div>
          <button class=\"btn btn-primary\" type=\"button\" onclick=\"openModal('modal-log')\">Riwayat Aktivitas</button>
        </div>

        <form method=\"post\">
          <div class=\"form-group\">
            <label class=\"form-label\">Nama Lengkap</label>
            <input name=\"full_name\" class=\"form-input\" value=\"{user_obj.full_name}\" required>
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">Email</label>
            <input name=\"email\" type=\"email\" class=\"form-input\" value=\"{user_obj.email}\" required>
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">NIM</label>
            <input name=\"student_id\" class=\"form-input\" value=\"{user_obj.student_id or ''}\">
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">No. HP</label>
            <input name=\"phone\" class=\"form-input\" value=\"{user_obj.phone or ''}\">
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">Kampus</label>
            <input name=\"campus\" class=\"form-input\" value=\"{user_obj.campus or ''}\">
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">Fakultas</label>
            <input name=\"faculty\" class=\"form-input\" value=\"{user_obj.faculty or ''}\">
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">Program Studi / Jurusan</label>
            <input name=\"major\" class=\"form-input\" value=\"{user_obj.major or ''}\">
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">Semester</label>
            <input name=\"semester\" class=\"form-input\" value=\"{user_obj.semester or ''}\">
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">Keahlian / Minat Utama</label>
            <textarea name=\"skills\" class=\"form-input\" style=\"min-height:60px;\">{user_obj.skills or ""}</textarea>
          </div>

          <div class=\"form-group\">
            <label class=\"form-label\">Role</label>
            <select name=\"role\" class=\"form-select\">
              <option value=\"user\" {role_user_selected}>User</option>
              <option value=\"admin\" {role_admin_selected}>Admin</option>
            </select>
          </div>

          <div class=\"form-group\">
            <label class=\"form-label\">Status</label>
            <label style=\"font-size:0.8rem;\">
              <input type=\"checkbox\" name=\"is_active\" {checked}> Akun aktif
            </label>
          </div>

          <hr style=\"margin: 1rem 0; border:none; border-top:1px dashed rgba(148,163,184,0.5);\">

          <div class=\"form-group\">
            <label class=\"form-label\">Reset Password (opsional)</label>
            <input name=\"new_password\" class=\"form-input\" placeholder=\"Isi jika ingin reset password\">
            <label style=\"font-size:0.8rem; margin-top:0.2rem;\">
              <input type=\"checkbox\" name=\"reset_password\">
              Terapkan password baru
            </label>
          </div>

          <div style=\"margin-top:1.1rem; display:flex; justify-content:space-between; align-items:center; gap:0.75rem;\">
            <button class=\"btn btn-primary\" type=\"submit\" name=\"action\" value=\"save\">Simpan Perubahan</button>
            <button class=\"btn btn-danger\" type=\"submit\" name=\"action\" value=\"delete\" onclick=\"return confirm('Yakin hapus user ini?');\">Hapus User</button>
          </div>
        </form>
      </div>

      <!-- Modal Riwayat Aktivitas -->
      <div class=\"modal-backdrop\" id=\"modal-log\">
        <div class=\"modal\">
          <div class=\"modal-header\">
            <div class=\"modal-title\">Riwayat Aktivitas User</div>
            <button type=\"button\" class=\"modal-close\" onclick=\"closeModal('modal-log')\">✕</button>
          </div>
          <ul style=\"padding-left:1.1rem;max-height:320px;overflow:auto;\">
            {log_items or "<li style='font-size:0.8rem;'>Belum ada aktivitas tercatat.</li>"}
          </ul>
        </div>
      </div>
    </div>
    """
    return render_page(body, title="Admin - Edit User", active_nav="admin_users")


@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
@admin_required
def admin_settings():
    allow_admin_signup = get_setting("allow_admin_signup", "false") == "true"

    if request.method == "POST":
        allow = request.form.get("allow_admin_signup") == "on"
        set_setting("allow_admin_signup", "true" if allow else "false")
        log_action(
            current_user().id,
            "admin_update_setting",
            f"allow_admin_signup={allow}",
        )
        flash("Pengaturan berhasil disimpan.", "success")
        return redirect(url_for("admin_settings"))

    checked = "checked" if allow_admin_signup else ""

    body = f"""
    <div class=\"surface\">
      <h1 class=\"page-title\">Pengaturan Admin</h1>
      <p class=\"page-subtitle\">Atur perilaku pendaftaran dan fitur portal.</p>
      <div class=\"form-card\">
        <form method=\"post\">
          <div class=\"form-group\">
            <label class=\"form-label\">Pendaftaran sebagai Admin</label>
            <label style=\"font-size:0.8rem;\">
              <input type=\"checkbox\" name=\"allow_admin_signup\" {checked}>
              Izinkan pilihan \"Daftar sebagai Admin\" di halaman pendaftaran.
            </label>
            <div class=\"form-help\">
              Jika dimatikan, role admin hanya bisa diberikan dari halaman manajemen user.
            </div>
          </div>

          <div style=\"margin-top:1.1rem;\">
            <button class=\"btn btn-primary\" type=\"submit\">Simpan Pengaturan</button>
          </div>
        </form>
      </div>
    </div>
    """
    return render_page(
        body,
        title="Admin - Pengaturan",
        active_nav="admin_settings",
    )


@app.route("/admin/overview")
@login_required
@admin_required
def admin_overview():
    total_mahasiswa = User.query.filter_by(role="user").count()
    total_admin = User.query.filter_by(role="admin").count()
    total_records = StudentRecord.query.count()
    total_prestasi = StudentRecord.query.filter_by(record_type="prestasi").count()
    total_kegiatan = StudentRecord.query.filter_by(record_type="kegiatan").count()

    top_prestasi = (
        db.session.query(User, func.count(StudentRecord.id).label("cnt"))
        .join(StudentRecord, (StudentRecord.user_id == User.id) & (StudentRecord.record_type == "prestasi"))
        .filter(User.role == "user")
        .group_by(User.id)
        .order_by(func.count(StudentRecord.id).desc())
        .limit(5)
        .all()
    )

    top_kegiatan = (
        db.session.query(User, func.count(StudentRecord.id).label("cnt"))
        .join(StudentRecord, (StudentRecord.user_id == User.id) & (StudentRecord.record_type == "kegiatan"))
        .filter(User.role == "user")
        .group_by(User.id)
        .order_by(func.count(StudentRecord.id).desc())
        .limit(5)
        .all()
    )

    skill_users = (
        User.query.filter(User.role == "user", User.skills.isnot(None), User.skills != "")
        .order_by(User.created_at.desc())
        .limit(10)
        .all()
    )

    list_top_prestasi = ""
    for idx, (u, cnt) in enumerate(top_prestasi, start=1):
        list_top_prestasi += f"<li style='font-size:0.8rem;margin-bottom:0.2rem;'>{idx}. {u.full_name} — <strong>{cnt} prestasi</strong> ({u.campus or '-'})</li>"

    list_top_kegiatan = ""
    for idx, (u, cnt) in enumerate(top_kegiatan, start=1):
        list_top_kegiatan += f"<li style='font-size:0.8rem;margin-bottom:0.2rem;'>{idx}. {u.full_name} — <strong>{cnt} kegiatan</strong> ({u.campus or '-'})</li>"

    list_skills = ""
    for u in skill_users:
        skills_text = (u.skills or "").replace("\n", " / ")
        list_skills += f"""
        <li style="font-size:0.8rem;margin-bottom:0.4rem;">
          <strong>{u.full_name}</strong> ({u.campus or '-'})<br>
          <span style="font-size:0.75rem;color:var(--text-muted);">{skills_text}</span>
        </li>
        """

    body = f"""
    <div class=\"surface\">
      <div class=\"page-header\">
        <div>
          <h1 class=\"page-title\">Dashboard Admin BSI Scholarship</h1>
          <p class=\"page-subtitle\">Ringkasan cepat mahasiswa, prestasi, dan kegiatan.</p>
        </div>
      </div>

      <div class=\"cards-grid\" style=\"margin-bottom:1.3rem;\">
        <div class=\"card kpi-card kpi-1\" onclick=\"window.location.href='{url_for('admin_raw_data')}'\" style=\"cursor:pointer;\">
          <div class=\"card-title\">Total Mahasiswa</div>
          <div class=\"kpi-value\">{total_mahasiswa}</div>
          <div class=\"kpi-sub\">Klik untuk lihat data detail portofolio</div>
        </div>
        <div class=\"card kpi-card kpi-2\" onclick=\"window.location.href='{url_for('admin_users')}'\" style=\"cursor:pointer;\">
          <div class=\"card-title\">Total Admin</div>
          <div class=\"kpi-value\">{total_admin}</div>
          <div class=\"kpi-sub\">Klik untuk kelola akun admin</div>
        </div>
        <div class=\"card kpi-card kpi-3\" onclick=\"window.location.href='{url_for('admin_raw_data')}'\" style=\"cursor:pointer;\">
          <div class=\"card-title\">Total Portofolio</div>
          <div class=\"kpi-value\">{total_records}</div>
          <div class=\"kpi-sub\">{total_prestasi} prestasi • {total_kegiatan} kegiatan</div>
        </div>
      </div>

      <div class=\"cards-grid\">
        <div class=\"card\">
          <div class=\"card-title\">Mahasiswa Paling Banyak Prestasi</div>
          <ul style=\"margin-top:0.5rem;padding-left:1.1rem;\">
            {list_top_prestasi or "<li style='font-size:0.8rem;'>Belum ada data prestasi.</li>"}
          </ul>
        </div>
        <div class=\"card\">
          <div class=\"card-title\">Mahasiswa Paling Aktif Kegiatan</div>
          <ul style=\"margin-top:0.5rem;padding-left:1.1rem;\">
            {list_top_kegiatan or "<li style='font-size:0.8rem;'>Belum ada data kegiatan.</li>"}
          </ul>
        </div>
        <div class=\"card\">
          <div class=\"card-title\">Pemetaan Keahlian & Bakat</div>
          <ul style=\"margin-top:0.5rem;padding-left:1.1rem;max-height:220px;overflow:auto;\">
            {list_skills or "<li style='font-size:0.8rem;'>Belum banyak mahasiswa yang mengisi keahlian. Dorong mereka mengisi profil.</li>"}
          </ul>
        </div>
      </div>
    </div>
    """
    return render_page(body, title="Admin Dashboard", active_nav="admin_overview")


@app.route("/admin/raw-data")
@login_required
@admin_required
def admin_raw_data():
    year = request.args.get("year", "").strip()
    rtype = request.args.get("record_type", "").strip()

    base_q = db.session.query(StudentRecord, User).join(User, StudentRecord.user_id == User.id)
    if year:
        base_q = base_q.filter(StudentRecord.year == year)
    if rtype:
        base_q = base_q.filter(StudentRecord.record_type == rtype)

    records = base_q.order_by(StudentRecord.created_at.desc()).all()

    total_records = StudentRecord.query.count()
    total_prestasi = StudentRecord.query.filter_by(record_type="prestasi").count()
    total_kegiatan = StudentRecord.query.filter_by(record_type="kegiatan").count()

    rows = ""
    for rec, u in records:
        created = rec.created_at.astimezone(WIB).strftime("%d %b %Y") if rec.created_at else ""
        lampiran = ""
        if rec.file_name:
            lampiran = f"<a href='{url_for('record_file', record_id=rec.id)}' style='font-size:0.75rem;'>📎 Lihat</a>"
        else:
            lampiran = "-"
        rows += f"""
        <tr>
          <td>{u.full_name}</td>
          <td>{u.campus or '-'}</td>
          <td>{rec.record_type.title()}</td>
          <td>{rec.title}</td>
          <td>{rec.level or '-'}</td>
          <td>{rec.year or '-'}</td>
          <td>{rec.organizer or '-'}</td>
          <td>{lampiran}</td>
          <td>{created}</td>
        </tr>
        """

    body = f"""
    <div class=\"surface\">
      <div class=\"page-header\">
        <div>
          <h1 class=\"page-title\">Data Portofolio Mahasiswa</h1>
          <p class=\"page-subtitle\">Summary KPI dan raw data prestasi & kegiatan yang bisa difilter dan diunduh.</p>
        </div>
        <div>
          <a href=\"{url_for('admin_raw_data_export', year=year, record_type=rtype)}\" class=\"btn btn-primary\">Download Excel</a>
        </div>
      </div>

      <div class=\"cards-grid\" style=\"margin-bottom:1rem;\">
        <div class=\"card\">
          <div class=\"card-title\">Total Portofolio</div>
          <div style=\"font-size:1.4rem;font-weight:700;margin-top:0.3rem;\">{total_records}</div>
        </div>
        <div class=\"card\">
          <div class=\"card-title\">Total Prestasi</div>
          <div style=\"font-size:1.4rem;font-weight:700;margin-top:0.3rem;\">{total_prestasi}</div>
        </div>
        <div class=\"card\">
          <div class=\"card-title\">Total Kegiatan</div>
          <div style=\"font-size:1.4rem;font-weight:700;margin-top:0.3rem;\">{total_kegiatan}</div>
        </div>
      </div>

      <div class=\"form-card\">
        <form method=\"get\" style=\"display:flex;flex-wrap:wrap;gap:0.6rem;align-items:flex-end;\">
          <div class=\"form-group\" style=\"min-width:120px;\">
            <label class=\"form-label\">Tahun</label>
            <input name=\"year\" class=\"form-input\" placeholder=\"contoh: 2025\" value=\"{year}\">
          </div>
          <div class=\"form-group\" style=\"min-width:150px;\">
            <label class=\"form-label\">Jenis</label>
            <select name=\"record_type\" class=\"form-select\">
              <option value=\"\">Semua</option>
              <option value=\"prestasi\" {'selected' if rtype=='prestasi' else ''}>Prestasi</option>
              <option value=\"kegiatan\" {'selected' if rtype=='kegiatan' else ''}>Kegiatan</option>
            </select>
          </div>
          <div>
            <button class=\"btn btn-primary\" type=\"submit\">Terapkan Filter</button>
          </div>
        </form>
      </div>

      <div class=\"table-surface\">
        <div class=\"table-scroll\">
          <table>
            <thead>
              <tr>
                <th>Nama</th>
                <th>Kampus</th>
                <th>Jenis</th>
                <th>Judul</th>
                <th>Tingkat/Peran</th>
                <th>Tahun</th>
                <th>Penyelenggara</th>
                <th>Lampiran</th>
                <th>Dibuat</th>
              </tr>
            </thead>
            <tbody>
              {rows}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    """
    return render_page(body, title="Admin - Data", active_nav="admin_raw_data")


@app.route("/admin/raw-data/export")
@login_required
@admin_required
def admin_raw_data_export():
    from openpyxl import Workbook
    year = request.args.get("year", "").strip()
    rtype = request.args.get("record_type", "").strip()

    base_q = db.session.query(StudentRecord, User).join(User, StudentRecord.user_id == User.id)
    if year:
        base_q = base_q.filter(StudentRecord.year == year)
    if rtype:
        base_q = base_q.filter(StudentRecord.record_type == rtype)

    records = base_q.order_by(StudentRecord.created_at.desc()).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Portofolio"
    header = ["Nama", "Kampus", "Jenis", "Judul", "Tingkat/Peran", "Tahun", "Penyelenggara", "Dibuat"]
    ws.append(header)

    for rec, u in records:
        created = rec.created_at.astimezone(WIB).strftime("%Y-%m-%d %H:%M:%S") if rec.created_at else ""
        row = [
            u.full_name or "",
            u.campus or "",
            rec.record_type,
            rec.title or "",
            rec.level or "",
            rec.year or "",
            rec.organizer or "",
            created,
        ]
        ws.append(row)

    mem = BytesIO()
    wb.save(mem)
    mem.seek(0)
    filename = "bsi_scholarship_portofolio.xlsx"
    return send_file(
        mem,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )





# ============================================================
# ADMIN - FORMS DINAMIS
# ============================================================



@app.route("/admin/users/<int:user_id>/logs")
@login_required
@admin_required
def admin_user_logs(user_id: int):
    user_obj = User.query.get_or_404(user_id)
    logs = (
        ActivityLog.query.filter_by(user_id=user_obj.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(100)
        .all()
    )

    log_items = ""
    for log in logs:
        when = log.created_at.astimezone(WIB).strftime("%d %b %Y, %H:%M") if log.created_at else ""
        log_items += f"""<tr>
          <td>{when}</td>
          <td>{log.action}</td>
          <td>{log.detail or '-'}</td>
        </tr>"""

    body = f"""
    <div class=\"surface\">
      <div class=\"page-header\">
        <div>
          <h1 class=\"page-title\">Riwayat Aktivitas</h1>
          <p class=\"page-subtitle\">Log aktivitas untuk {user_obj.full_name} ({user_obj.email}).</p>
        </div>
        <div>
          <a href=\"{url_for('admin_users')}\" class=\"btn btn-ghost\">Kembali ke Daftar User</a>
        </div>
      </div>

      <div class=\"table-surface\">
        <div class=\"table-scroll\">
          <table>
            <thead>
              <tr>
                <th>Waktu</th>
                <th>Aksi</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {log_items}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    """
    return render_page(body, title="Riwayat Aktivitas User", active_nav="admin_users")

@app.route("/admin/forms", methods=["GET", "POST"])
@login_required
@admin_required
def admin_forms():
    admin = current_user()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        slug = request.form.get("slug", "").strip()
        description = request.form.get("description", "").strip()
        icon = request.form.get("icon", "").strip()
        url_form = request.form.get("url", "").strip()

        if not title or not slug:
            flash("Judul dan slug wajib diisi.", "danger")
            return redirect(url_for("admin_forms"))

        existing = ProgramForm.query.filter_by(slug=slug).first()
        if existing:
            flash("Slug sudah digunakan, pilih slug lain.", "danger")
            return redirect(url_for("admin_forms"))

        pf = ProgramForm(
            title=title,
            slug=slug,
            icon=icon or "📝",
            description=description,
            url=url_form,
            is_active=True,
            created_by=admin.id,
        )
        db.session.add(pf)
        db.session.commit()
        log_action(admin.id, "admin_add_form", slug)
        flash("Form berhasil ditambahkan.", "success")
        return redirect(url_for("admin_forms"))

    forms = ProgramForm.query.order_by(ProgramForm.created_at.desc()).all()

    rows = ""
    for fobj in forms:
        status = "Aktif" if fobj.is_active else "Nonaktif"
        created = fobj.created_at.astimezone(WIB).strftime("%d %b %Y") if fobj.created_at else ""
        rows += f"""
        <tr>
          <td>{fobj.title}</td>
          <td>{fobj.slug}</td>
          <td>{fobj.icon or ''}</td>
          <td>{fobj.url or '-'}</td>
          <td>{status}</td>
          <td>{created}</td>
        </tr>
        """

    body = f"""
    <div class=\"surface\">
      <div class=\"page-header\">
        <div>
          <h1 class=\"page-title\">Admin — Form & Tautan</h1>
          <p class=\"page-subtitle\">Buat menu form dinamis (misalnya Google Form) yang akan muncul di Dashboard mahasiswa.</p>
        </div>
      </div>

      <div class=\"form-card\">
        <h2 class=\"page-title\" style=\"font-size:1rem;\">Tambah Form Baru</h2>
        <form method=\"post\" style=\"margin-top:0.6rem;\">
          <div class=\"form-group\">
            <label class=\"form-label\">Judul Form</label>
            <input name=\"title\" class=\"form-input\" required>
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">Slug (unik, tanpa spasi)</label>
            <input name=\"slug\" class=\"form-input\" placeholder=\"contoh: evaluasi-midline\" required>
            <div class=\"form-help\">Slug akan digunakan pada URL internal: /form/&lt;slug&gt;</div>
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">Emoji/Icon</label>
            <input name=\"icon\" class=\"form-input\" placeholder=\"contoh: 📝\">
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">Deskripsi Singkat</label>
            <input name=\"description\" class=\"form-input\" placeholder=\"Tampilkan tujuan form di kartu Dashboard.\">
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">Tautan Form (opsional)</label>
            <input name=\"url\" class=\"form-input\" placeholder=\"contoh: https://forms.gle/...\">
          </div>
          <button class=\"btn btn-primary\" type=\"submit\">Simpan Form</button>
        </form>
      </div>

      <div class=\"table-surface\">
        <div class=\"table-scroll\">
          <table>
            <thead>
              <tr>
                <th>Judul</th>
                <th>Slug</th>
                <th>Icon</th>
                <th>Tautan</th>
                <th>Status</th>
                <th>Dibuat</th>
              </tr>
            </thead>
            <tbody>
              {rows}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    """
    return render_page(body, title="Admin - Forms", active_nav="admin_forms")


# ============================================================
# ADMIN - POSTINGAN KABAR & DOKUM

@app.route("/tickets")
@login_required
def tickets():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    # Semua tiket user
    tickets_all = (
        Ticket.query.filter_by(user_id=user.id)
        .order_by(Ticket.created_at.desc())
        .all()
    )

    # Pisahkan tiket yang masih berjalan (open & in_progress)
    ongoing_tickets = [t for t in tickets_all if t.status in ("open", "in_progress")]

    steps = ["open", "in_progress", "resolved", "closed"]

    ongoing_cards = ""
    for t in ongoing_tickets:
        created = t.created_at.astimezone(WIB).strftime("%d %b %Y, %H:%M") if t.created_at else "-"
        ticket_no = format_ticket_number(t)
        status_label = t.status.replace("_", " ").title()

        # timeline
        current_index = steps.index(t.status) if t.status in steps else 0
        steps_html = ""
        for idx, s in enumerate(steps):
            label = s.replace("_", " ").title()
            if idx < current_index:
                cls = "done"
            elif idx == current_index:
                cls = "current"
            else:
                cls = "future"
            steps_html += f"<div class='ticket-step ticket-step-{cls}'><div class='ticket-step-dot'></div><div class='ticket-step-label'>{label}</div></div>"

        short_desc = (t.description or "").strip().replace("\n", " ")
        if len(short_desc) > 200:
            short_desc = short_desc[:200] + "..."

        ongoing_cards += f"""<div class='ticket-card'>
      <div class='ticket-card-header'>
        <div>
          <div class='ticket-title'>#{ticket_no} — {t.title}</div>
          <div class='ticket-meta'>Dibuat: {created}</div>
        </div>
        <div class='ticket-status-pill status-{t.status}'>{status_label}</div>
      </div>
      <div class='ticket-body'>
        <p>{short_desc}</p>
      </div>
      <div class='ticket-timeline'>
        {steps_html}
      </div>
    </div>"""


    # Tabel riwayat semua tiket
    
    # Tabel riwayat semua tiket + hitung pesan belum dibaca
    ticket_ids = [t.id for t in tickets_all]
    unread_map = {}
    if ticket_ids:
        for msg in TicketMessage.query.filter(TicketMessage.ticket_id.in_(ticket_ids)).all():
            if not msg.is_read_user and msg.sender_id != user.id:
                unread_map[msg.ticket_id] = unread_map.get(msg.ticket_id, 0) + 1

    
    history_rows = ""
    for t in tickets_all:
        ticket_no = format_ticket_number(t)
        created = t.created_at.astimezone(WIB).strftime("%d %b %Y, %H:%M") if t.created_at else "-"
        updated = t.updated_at.astimezone(WIB).strftime("%d %b %Y, %H:%M") if t.updated_at else "-"
        completed = t.completed_at.astimezone(WIB).strftime("%d %b %Y, %H:%M") if getattr(t, "completed_at", None) else "-"
        status_label = t.status.replace("_", " ").title()
        unread = unread_map.get(t.id, 0)
        unread_html = f"<span class='badge-unread'>{unread}</span>" if unread else ""
        category = t.category or "-"
        short_desc = (t.description or "").strip().replace("\n", " ")
        if len(short_desc) > 160:
            short_desc = short_desc[:160] + "..."

        history_rows += f"""<tr>
          <td>{created}</td>
          <td>{ticket_no}</td>
          <td>{category}</td>
          <td><span class='badge badge-status-{t.status}'>{status_label}</span></td>
          <td>{short_desc}</td>
          <td>{completed}</td>
          <td>{updated}</td>
          <td><button class='btn btn-chat btn-sm' type='button' onclick="openTicketChat({t.id}, '{ticket_no}')">Chat{(' ' + unread_html) if unread_html else ''}</button></td>
        </tr>"""
    body = f"""
    <div class=\"surface\">
      <div class=\"page-header\">
        <div>
          <h1 class=\"page-title\">Kendala Sistem Ticketing</h1>
          <p class=\"page-subtitle\">Laporkan kendala sistem ticketing dan pantau progres penanganannya.</p>
        </div>
        <div>
          <a href=\"{url_for('ticket_new')}\" class=\"btn btn-primary\">Buat Laporan</a>
        </div>
      </div>

      <div class=\"form-card\">
        <h2 class=\"page-title\" style=\"font-size:1rem;\">Tiket Berjalan</h2>
        <p class=\"page-subtitle\">Hanya menampilkan tiket yang masih dalam status Open atau In Progress.</p>
        <div class=\"ticket-ongoing-grid\" style=\"margin-top:0.8rem;\">
          {ongoing_cards or "<p style='font-size:0.8rem;color:var(--text-muted);'>Saat ini tidak ada tiket berjalan.</p>"}
        </div>
      </div>

      <div class=\"table-surface\" style=\"margin-top:1.4rem;\">
        <div class=\"table-scroll\">
          
          <table class="tickets-table user-tickets-table">
            <thead>
              <tr>
                <th class="col-created">Created</th>
                <th class="col-ticket">No. Ticket</th>
                <th class="col-category">Kategori</th>
                <th class="col-status">Status</th>
                <th class="col-desc">Deskripsi</th>
                <th class="col-completed">Completed</th>
                <th class="col-updated">Update Terakhir</th>
                <th class="col-actions">Chat</th>
              </tr>
</thead>
            <tbody>
              {history_rows or "<tr><td colspan='7' style='text-align:center;font-size:0.8rem;color:var(--text-muted);'>Belum ada tiket yang tercatat.</td></tr>"}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    """
    return render_page(body, title="Kendala Sistem", active_nav="tickets")



@app.route("/tickets/new", methods=["GET", "POST"])
@login_required
def ticket_new():
    user = current_user()
    if not user:
        return redirect(url_for("login"))

    if request.method == "POST":
        category = (request.form.get("category") or "").strip()
        description = (request.form.get("description") or "").strip()
        attachment = request.files.get("attachment")

        if not description:
            flash("Deskripsi kendala wajib diisi.", "danger")
        else:
            # gunakan kalimat pertama sebagai judul singkat
            short_title = description.strip().split("\n")[0]
            if len(short_title) > 120:
                short_title = short_title[:120] + "..."

            ticket = Ticket(
                user_id=user.id,
                title=short_title,
                description=description,
                category=category or None,
                status="open",
            )
            db.session.add(ticket)
            db.session.commit()

            # handle lampiran (opsional), hanya gambar dan maks 300 KB
            if attachment and attachment.filename:
                filename = secure_filename(attachment.filename)
                ext = os.path.splitext(filename)[1].lower()
                allowed_ext = {".png", ".jpg", ".jpeg"}
                data = attachment.read()
                if ext not in allowed_ext:
                    flash("File lampiran harus berupa gambar (PNG/JPG).", "danger")
                elif len(data) > 300 * 1024:
                    flash("Ukuran file lampiran maksimal 300 KB.", "danger")
                else:
                    upload_dir = os.path.join(app.static_folder, "uploads", "tickets", str(ticket.id))
                    os.makedirs(upload_dir, exist_ok=True)
                    save_path = os.path.join(upload_dir, filename)
                    with open(save_path, "wb") as f:
                        f.write(data)
                    rel_path = os.path.relpath(save_path, app.static_folder).replace(os.path.sep, "/")
                    ticket.attachment_path = rel_path
                    db.session.commit()

            log_action(user.id, "ticket_create", short_title)
            flash("Laporan kendala berhasil dikirim.", "success")
            return redirect(url_for("tickets"))

    body = f"""
    <div class=\"surface\">
      <div class=\"page-header\">
        <div>
          <h1 class=\"page-title\">Buat Laporan Kendala</h1>
          <p class=\"page-subtitle\">Ceritakan kendala yang Anda alami pada sistem ticketing.</p>
        </div>
        <div>
          <a href=\"{url_for('tickets')}\" class=\"btn btn-ghost\">Kembali ke Daftar Laporan</a>
        </div>
      </div>

      <div class=\"form-card\">
        <form method=\"post\" enctype=\"multipart/form-data\">
          <div class=\"form-group\">
            <label for=\"category\" class=\"form-label\">Kategori Kendala</label>
            <select id=\"category\" name=\"category\" class=\"form-select\">
              <option value=\"\">Pilih Kategori (Wajib)</option>
              <option value=\"Kehadiran Pembinaan\">Kehadiran Pembinaan</option>
              <option value=\"Kehadiran mentoring\">Kehadiran mentoring</option>
              <option value=\"Pre-Post Test\">Pre-Post Test</option>
              <option value=\"Ganti Nomor HP\">Ganti Nomor HP</option>
              <option value=\"Tugas\">Tugas</option>
            </select>
          </div>
          <div class=\"form-group\">
            <label for=\"description\" class=\"form-label\">Deskripsi Kendala</label>
            <textarea id=\"description\" name=\"description\" rows=\"5\" class=\"form-input\" placeholder=\"Jelaskan masalah yang terjadi secara singkat dan jelas...\" required></textarea>
          </div>
          <div class=\"form-group\">
            <label for=\"attachment\" class=\"form-label\">Lampiran Gambar (maks. 300 KB)</label>
            <input type=\"file\" id=\"attachment\" name=\"attachment\" class=\"form-input\" accept=\"image/*\" />
            <p style=\"font-size:0.75rem;color:var(--text-muted);margin-top:0.25rem;\">Opsional. Unggah screenshot pendukung jika perlu.</p>
          </div>
          <div class=\"form-actions\" style=\"margin-top:1rem;display:flex;justify-content:flex-end;gap:0.5rem;\">
            <a href=\"{url_for('tickets')}\" class=\"btn btn-ghost\">Batal</a>
            <button class=\"btn btn-primary\" type=\"submit\">Kirim Laporan</button>
          </div>
        </form>
      </div>
    </div>
    """
    return render_page(body, title="Laporan Kendala Baru", active_nav="tickets")



@app.route("/admin/tickets", methods=["GET", "POST"])
@login_required
@admin_required
def admin_tickets():
    admin = current_user()

    # === Handle actions (POST) ===
    if request.method == "POST":
        action = request.form.get("action")
        ticket_id = request.form.get("ticket_id")
        admin_note = (request.form.get("admin_note") or "").strip()

        if not admin_note:
            flash("Catatan admin wajib diisi sebelum melakukan aksi pada tiket.", "danger")
            return redirect(url_for("admin_tickets"))

        ticket = Ticket.query.get(ticket_id)
        if not ticket:
            flash("Ticket not found.", "danger")
            return redirect(url_for("admin_tickets"))

        # Assign admin automatically on any action if not yet assigned
        if ticket.assigned_admin_id is None:
            ticket.assigned_admin_id = admin.id

        # Closed ticket cannot be changed further
        if ticket.status == "closed":
            flash("Ticket is already closed and cannot be modified.", "danger")
            return redirect(url_for("admin_tickets"))

        if action == "accept":
            if ticket.status == "open":
                ticket.status = "in_progress"
            log_action(admin.id, "ticket_update_status", f"{ticket.id}:in_progress")
        elif action == "complete":
            if ticket.status in ("in_progress", "resolved"):
                # set completed_at saat pertama kali selesai
                if ticket.status != "resolved" and getattr(ticket, "completed_at", None) is None:
                    ticket.completed_at = datetime.now(WIB)
                ticket.status = "resolved"
            log_action(admin.id, "ticket_update_status", f"{ticket.id}:resolved")
        elif action == "close":
            if ticket.status != "closed":
                ticket.status = "closed"
            log_action(admin.id, "ticket_update_status", f"{ticket.id}:closed")

        # Append admin note as running log
        if admin_note:
            timestamp = datetime.now(WIB).strftime("%d %b %Y, %H:%M WIB")
            prefix = f"[{timestamp}] "
            existing = (ticket.admin_note or "").strip()
            if existing:
                ticket.admin_note = existing + "\n" + prefix + admin_note
            else:
                ticket.admin_note = prefix + admin_note

        db.session.commit()
        flash("Ticket updated successfully.", "success")
        return redirect(url_for("admin_tickets"))

    # === GET: list & filters ===
    status_filter = request.args.get("status", "all").strip().lower()
    user_filter = (request.args.get("user") or "").strip().lower()
    admin_filter = (request.args.get("admin") or "").strip().lower()
    title_filter = (request.args.get("title") or "").strip().lower()
    year_filter = (request.args.get("year") or "").strip()

    q = Ticket.query

    if status_filter != "all":
        q = q.filter_by(status=status_filter)

    tickets = q.order_by(Ticket.created_at.desc()).all()

    # In-memory filters for name/title/year to keep query simple
    filtered_tickets = []
    for t in tickets:
        u_name = (t.user.full_name if t.user and t.user.full_name else "").lower()
        a_name = (t.assigned_admin.full_name if getattr(t, "assigned_admin", None) and t.assigned_admin.full_name else "").lower()
        title = (t.title or "").lower()
        year_str = t.created_at.astimezone(WIB).strftime("%Y") if t.created_at else ""

        if user_filter and user_filter not in u_name:
            continue
        if admin_filter and admin_filter not in a_name:
            continue
        if title_filter and title_filter not in title:
            continue
        if year_filter and year_filter != year_str:
            continue
        filtered_tickets.append(t)

    tickets = filtered_tickets

    # KPI summary
    total_tickets = Ticket.query.count()
    open_count = Ticket.query.filter_by(status="open").count()
    in_progress_count = Ticket.query.filter_by(status="in_progress").count()
    resolved_count = Ticket.query.filter_by(status="resolved").count()
    closed_count = Ticket.query.filter_by(status="closed").count()
    unassigned_count = Ticket.query.filter(Ticket.assigned_admin_id.is_(None)).count()
    my_count = Ticket.query.filter_by(assigned_admin_id=admin.id).count()


    # Hitung jumlah pesan belum dibaca per ticket untuk admin
    ticket_ids = [t.id for t in tickets]
    unread_map = {}
    if ticket_ids:
        for msg in TicketMessage.query.filter(TicketMessage.ticket_id.in_(ticket_ids)).all():
            if admin.role == "admin" and not msg.is_read_admin and msg.sender_id != admin.id:
                unread_map[msg.ticket_id] = unread_map.get(msg.ticket_id, 0) + 1

    def status_label(s: str) -> str:
        return s.replace("_", " ").title()


    
    rows = ""
    for t in tickets:
        created = t.created_at.astimezone(WIB).strftime("%d %b %Y, %H:%M") if t.created_at else "-"
        completed = t.completed_at.astimezone(WIB).strftime("%d %b %Y, %H:%M") if getattr(t, "completed_at", None) else "-"
        assigned_name = t.assigned_admin.full_name if getattr(t, "assigned_admin", None) else "-"
        user_name = t.user.full_name if t.user else "-"
        ticket_no = format_ticket_number(t)
        unread = unread_map.get(t.id, 0)
        unread_html = f"<span class='badge-unread'>{unread}</span>" if unread else ""
        category = t.category or "-"
        short_desc = (t.description or "").strip().replace("\n", " ")
        if len(short_desc) > 160:
            short_desc = short_desc[:160] + "..."

        accept_disabled = "disabled" if t.status != "open" else ""
        complete_disabled = "disabled" if t.status != "in_progress" else ""
        close_disabled = "disabled" if t.status != "resolved" else ""

        rows += f"""
        <tr>
          <td>{created}</td>
          <td>{ticket_no}</td>
          <td>{category}</td>
          <td>{user_name}</td>
          <td>{assigned_name}</td>
          <td>{short_desc}</td>
          <td><span class='badge badge-status-{t.status}'>{status_label(t.status)}</span></td>
          <td>{completed}</td>
          <td>
            <form method='post' style='display:flex;flex-direction:column;gap:0.35rem;min-width:220px;'>
              <input type='hidden' name='ticket_id' value='{t.id}' />
              <div style='display:flex;flex-wrap:wrap;gap:0.35rem;align-items:center;'>
                <button class='btn btn-chat btn-sm' type='button' onclick="openTicketChat({t.id}, '{ticket_no}')">
                  Chat{(' ' + unread_html) if unread_html else ''}
                </button>
                <button class='btn btn-sm btn-status-accept' type='submit' name='action' value='accept' {accept_disabled}>Accepted</button>
                <button class='btn btn-sm btn-status-complete' type='submit' name='action' value='complete' {complete_disabled}>Completed</button>
                <button class='btn btn-sm btn-status-close' type='submit' name='action' value='close' {close_disabled}>Closed</button>
                <button class='btn btn-primary btn-sm' type='button' onclick="openTicketNotes({t.id})">
                  Notes
                </button>
              </div>
              <div style='display:flex;gap:0.25rem;'>
                <input type='text' name='admin_note' placeholder='Catatan admin / progres ...' class='form-input' style='flex:1;min-width:130px;font-size:0.78rem;' required />
              </div>
            </form>
          </td>
        </tr>
        """
# Status filter pills
    base_url = url_for("admin_tickets")
    def status_link(label_key, label_text):
        active = "filter-pill-active" if status_filter == label_key else ""
        href = f"{base_url}?status={label_key}" if label_key != "all" else base_url
        return f"<a href='{href}' class='filter-pill {active}'>{label_text}</a>"

    filters_html = " ".join([
        status_link("all", "Semua"),
        status_link("open", "Open"),
        status_link("in_progress", "In Progress"),
        status_link("resolved", "Resolved"),
        status_link("closed", "Closed"),
    ])

    body = f"""
    <div class=\"surface\">
      <div class=\"page-header\">
        <div>
          <h1 class=\"page-title\">Admin — Kendala Sistem Ticketing</h1>
          <p class=\"page-subtitle\">Manage and monitor student system issue reports.</p>
        </div>
      </div>

      <div class=\"cards-grid\" style=\"margin-bottom:1rem;\">
        <div class=\"card\">
          <div class=\"card-title\">Total Tickets</div>
          <div style=\"font-size:1.4rem;font-weight:700;margin-top:0.3rem;\">{total_tickets}</div>
        </div>
        <div class=\"card\">
          <div class=\"card-title\">Open</div>
          <div style=\"font-size:1.4rem;font-weight:700;margin-top:0.3rem;\">{open_count}</div>
        </div>
        <div class=\"card\">
          <div class=\"card-title\">In Progress</div>
          <div style=\"font-size:1.4rem;font-weight:700;margin-top:0.3rem;\">{in_progress_count}</div>
        </div>
        <div class=\"card\">
          <div class=\"card-title\">Resolved</div>
          <div style=\"font-size:1.4rem;font-weight:700;margin-top:0.3rem;\">{resolved_count}</div>
        </div>
        <div class=\"card\">
          <div class=\"card-title\">Closed</div>
          <div style=\"font-size:1.4rem;font-weight:700;margin-top:0.3rem;\">{closed_count}</div>
        </div>
        <div class=\"card\">
          <div class=\"card-title\">Unassigned</div>
          <div style=\"font-size:1.4rem;font-weight:700;margin-top:0.3rem;\">{unassigned_count}</div>
        </div>
        <div class=\"card\">
          <div class=\"card-title\">Assigned to Me</div>
          <div style=\"font-size:1.4rem;font-weight:700;margin-top:0.3rem;\">{my_count}</div>
        </div>
      </div>

      
<div class=\"form-card\">
        <form id=\"ticket-filter-form\" method=\"get\" style=\"display:flex;flex-wrap:wrap;gap:0.6rem;align-items:flex-end;\">
          <div class=\"form-group\" style=\"min-width:120px;\">
            <label class=\"form-label\">Tahun</label>
            <input name=\"year\" class=\"form-input\" placeholder=\"contoh: 2025\" value=\"{year_filter}\" />
          </div>
          <div class=\"form-group\" style=\"min-width:120px;\">
            <label class=\"form-label\">User</label>
            <input name=\"user\" class=\"form-input\" placeholder=\"Nama user\" value=\"{request.args.get('user', '')}\" />
          </div>
          <div class=\"form-group\" style=\"min-width:120px;\">
            <label class=\"form-label\">Admin</label>
            <input name=\"admin\" class=\"form-input\" placeholder=\"Nama admin\" value=\"{request.args.get('admin', '')}\" />
          </div>
          <div class=\"form-group\" style=\"min-width:160px;\">
            <label class=\"form-label\">Title</label>
            <input name=\"title\" class=\"form-input\" placeholder=\"Judul mengandung...\" value=\"{request.args.get('title', '')}\" />
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">Status</label>
            <select name=\"status\" class=\"form-select\">
              <option value=\"all\" {'selected' if status_filter == 'all' else ''}>Semua</option>
              <option value=\"open\" {'selected' if status_filter == 'open' else ''}>Open</option>
              <option value=\"in_progress\" {'selected' if status_filter == 'in_progress' else ''}>In Progress</option>
              <option value=\"resolved\" {'selected' if status_filter == 'resolved' else ''}>Resolved</option>
              <option value=\"closed\" {'selected' if status_filter == 'closed' else ''}>Closed</option>
            </select>
          </div>
        </form>

        <div class=\"filter-row\">
          <div class=\"filter-row-left\">
            <span style=\"color:var(--text-muted);\">Quick status filter:</span>
            {filters_html}
          </div>
          <div class=\"filter-row-right\">
            <button class=\"btn btn-primary btn-sm\" type=\"submit\" form=\"ticket-filter-form\">Apply Filter</button>
            <a href=\"{url_for('admin_tickets')}\" class=\"btn btn-ghost btn-sm\">Reset Filter</a>
            <a href=\"{url_for('admin_tickets_export', status=status_filter, year=year_filter, user=request.args.get('user',''), admin=request.args.get('admin',''), title=request.args.get('title',''))}\" class=\"btn btn-ghost btn-sm\">Download Excel</a>
          </div>
        </div>
      </div><div class=\"table-surface\">
        <div class=\"table-scroll\">
          
          <table class="tickets-table admin-tickets-table">
            <thead>
              <tr>
                <th class="col-created">Created</th>
                <th class="col-ticket">No. Ticket</th>
                <th class="col-category">Kategori</th>
                <th class="col-user">User</th>
                <th class="col-admin">Admin</th>
                <th class="col-desc">Deskripsi</th>
                <th class="col-status">Status</th>
                <th class="col-completed">Completed</th>
                <th class="col-actions">Actions</th>
              </tr>
</thead>
            <tbody>
              {rows}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    """
    return render_page(body, title="Admin — Kendala Sistem", active_nav="admin_tickets")



@app.route("/admin/tickets/<int:ticket_id>/notes")
@login_required
@admin_required
def admin_ticket_notes(ticket_id):
    """Return admin notes for a ticket as JSON (used by modal viewer)."""
    ticket = Ticket.query.get_or_404(ticket_id)
    return jsonify(
        {
            "ticket_id": ticket.id,
            "ticket_no": format_ticket_number(ticket),
            "notes": ticket.admin_note or "",
        }
    )


@app.route("/admin/tickets/export")
@login_required
@admin_required
def admin_tickets_export():
    from openpyxl import Workbook

    status_filter = request.args.get("status", "all").strip().lower()
    user_filter = (request.args.get("user") or "").strip().lower()
    admin_filter = (request.args.get("admin") or "").strip().lower()
    title_filter = (request.args.get("title") or "").strip().lower()
    year_filter = (request.args.get("year") or "").strip()

    q = Ticket.query
    if status_filter != "all":
        q = q.filter_by(status=status_filter)

    tickets = q.order_by(Ticket.created_at.desc()).all()

    filtered = []
    for tkt in tickets:
        u_name = (tkt.user.full_name if tkt.user and tkt.user.full_name else "").lower()
        a_name = (tkt.assigned_admin.full_name if getattr(tkt, "assigned_admin", None) and tkt.assigned_admin.full_name else "").lower()
        title = (tkt.title or "").lower()
        year_str = tkt.created_at.astimezone(WIB).strftime("%Y") if tkt.created_at else ""

        if user_filter and user_filter not in u_name:
            continue
        if admin_filter and admin_filter not in a_name:
            continue
        if title_filter and title_filter not in title:
            continue
        if year_filter and year_filter != year_str:
            continue
        filtered.append(tkt)

    wb = Workbook()
    ws = wb.active
    ws.title = "Tickets"
    header = [
        "TicketNumber",
        "User",
        "Admin",
        "Title",
        "Status",
        "CreatedWIB",
        "UpdatedWIB",
        "LastNote",
    ]
    ws.append(header)

    for tkt in filtered:
        created_wib = tkt.created_at.astimezone(WIB).strftime("%Y-%m-%d %H:%M:%S") if tkt.created_at else ""
        updated_wib = tkt.updated_at.astimezone(WIB).strftime("%Y-%m-%d %H:%M:%S") if tkt.updated_at else ""
        last_note = (tkt.admin_note or "").splitlines()[-1] if tkt.admin_note else ""
        row = [
            format_ticket_number(tkt),
            tkt.user.full_name if tkt.user else "",
            tkt.assigned_admin.full_name if getattr(tkt, "assigned_admin", None) else "",
            tkt.title or "",
            tkt.status.replace("_", " ").title(),
            created_wib,
            updated_wib,
            last_note,
        ]
        ws.append(row)

    mem = BytesIO()
    wb.save(mem)
    mem.seek(0)
    filename = "bsi_scholarship_tickets_admin.xlsx"
    return send_file(
        mem,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )

@app.route("/admin/posts", methods=["GET", "POST"])
@login_required
@admin_required
def admin_posts():
    admin = current_user()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip() or "news"
        content = request.form.get("content", "").strip()
        image_url = request.form.get("image_url", "").strip()
        video_url = request.form.get("video_url", "").strip()
        if not title:
            flash("Judul wajib diisi.", "danger")
            return redirect(url_for("admin_posts"))

        post = Post(
            title=title,
            category=category,
            content=content,
            image_url=image_url,
            video_url=video_url,
            is_published=True,
            created_by=admin.id,
        )
        db.session.add(post)
        db.session.commit()
        log_action(admin.id, "admin_add_post", f"{category}:{title}")
        flash("Postingan berhasil ditambahkan.", "success")
        return redirect(url_for("admin_posts"))

    posts = Post.query.order_by(Post.created_at.desc()).all()

    rows = ""
    for p in posts:
        created = p.created_at.astimezone(WIB).strftime("%d %b %Y") if p.created_at else ""
        reg_count = PostRegistration.query.filter_by(post_id=p.id).count()
        rows += f"""
        <tr>
          <td>{p.title}</td>
          <td>{p.category or '-'}</td>
          <td>{"Ya" if p.is_published else "Tidak"}</td>
          <td>{created}</td>
          <td>{reg_count} pendaftar</td>
        </tr>
        """

    body = f"""
    <div class=\"surface\">
      <div class=\"page-header\">
        <div>
          <h1 class=\"page-title\">Admin — Postingan Kabar & Dokumentasi</h1>
          <p class=\"page-subtitle\">Posting pengumuman, info program, dan dokumentasi kegiatan yang tampil di menu Info.</p>
        </div>
      </div>

      <div class=\"form-card\">
        <h2 class=\"page-title\" style=\"font-size:1rem;\">Buat Postingan Baru</h2>
        <form method=\"post\" style=\"margin-top:0.6rem;\">
          <div class=\"form-group\">
            <label class=\"form-label\">Judul</label>
            <input name=\"title\" class=\"form-input\" required>
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">Kategori</label>
            <select name=\"category\" class=\"form-select\">
              <option value=\"news\">Kabar / News</option>
              <option value=\"dokumentasi\">Dokumentasi Kegiatan</option>
            </select>
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">Isi / Deskripsi</label>
            <textarea name=\"content\" class=\"form-input\" style=\"min-height:80px;\" placeholder=\"Tuliskan informasi lengkap atau ringkasan kegiatan.\"></textarea>
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">URL Gambar (opsional)</label>
            <input name=\"image_url\" class=\"form-input\" placeholder=\"contoh: https://... .jpg\">
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">URL Video (opsional)</label>
            <input name=\"video_url\" class=\"form-input\" placeholder=\"contoh: tautan YouTube / Drive\">
          </div>
          <div class=\"form-group\">
            <label class=\"form-label\">Berlaku Sampai</label>
            <input name=\"valid_until_text\" class=\"form-input\" placeholder=\"contoh: 31 Des 2025 atau s/d pengumuman berikutnya\">
          </div>
          <button class=\"btn btn-primary\" type=\"submit\">Publikasikan</button>
        </form>
      </div>

      <div class=\"table-surface\">
        <div class=\"table-scroll\">
          <table>
            <thead>
              <tr>
                <th>Judul</th>
                <th>Kategori</th>
                <th>Dipublikasikan</th>
                <th>Dibuat</th>
                <th>Pendaftar</th>
              </tr>
            </thead>
            <tbody>
              {rows}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    """
    return render_page(body, title="Admin - Postingan", active_nav="admin_posts")


# ============================================================
# NEWS / INFO UNTUK MAHASISWA + PENDAFTARAN POSTINGAN
# ============================================================


@app.route("/news")
@login_required
def news_list():
    posts = (
        Post.query.filter_by(is_published=True)
        .order_by(Post.created_at.desc())
        .all()
    )

    user = current_user()

    cards = ""
    for p in posts:
        created = p.created_at.astimezone(WIB).strftime("%d %b %Y") if p.created_at else ""
        category = p.category.title() if p.category else "News"
        image_html = ""
        if p.image_url:
            image_html = f"<div style='margin-bottom:0.45rem;'><img src='{p.image_url}' alt='gambar' style='width:100%;border-radius:12px;max-height:160px;object-fit:cover;'></div>"
        video_html = ""
        if p.video_url:
            video_html = f"<div style='margin-top:0.35rem;font-size:0.75rem;'><a href='{p.video_url}' target='_blank'>Lihat video / dokumentasi »</a></div>"

        content_text = (p.content or "").replace("\n", " ")
        if len(content_text) > 220:
            content_preview = content_text[:220] + "..."
        else:
            content_preview = content_text

        reg_count = PostRegistration.query.filter_by(post_id=p.id).count()
        already_reg = False
        if user:
            already_reg = PostRegistration.query.filter_by(post_id=p.id, user_id=user.id).first() is not None

        daftar_btn = ""
        if already_reg:
            daftar_btn = "<span style='font-size:0.75rem;color:var(--text-muted);'>Anda sudah mendaftar.</span>"
        else:
            daftar_btn = f"""
            <form method='post' action='{url_for('news_register', post_id=p.id)}' style='margin-top:0.5rem;'>
              <button class='btn btn-primary' type='submit'>Daftar</button>
            </form>
            """

        # Reactions & bookmarks
        like_count = PostReaction.query.filter_by(post_id=p.id, reaction_type="like").count()
        dislike_count = PostReaction.query.filter_by(post_id=p.id, reaction_type="dislike").count()
        user_reaction = None
        user_bookmark = None
        if user:
            user_reaction = PostReaction.query.filter_by(post_id=p.id, user_id=user.id).first()
            user_bookmark = PostBookmark.query.filter_by(post_id=p.id, user_id=user.id).first()

        like_active = "font-weight:700;" if (user_reaction and user_reaction.reaction_type == "like") else ""
        dislike_active = "font-weight:700;" if (user_reaction and user_reaction.reaction_type == "dislike") else ""
        bookmark_label = "Disimpan" if user_bookmark else "Simpan"

        # Comments
        comments = PostComment.query.filter_by(post_id=p.id).order_by(PostComment.created_at.asc()).all()
        replies_by_parent = {}
        for c in comments:
            if c.parent_id:
                replies_by_parent.setdefault(c.parent_id, []).append(c)

        def render_comment(c, indent_level=0):
            pad = 0.0 + 1.2 * indent_level
            ts = c.created_at.astimezone(WIB).strftime("%d %b %Y, %H:%M") if c.created_at else ""
            name = c.user.full_name if c.user and c.user.full_name else "User"
            content_html = c.content.replace("\n","<br>")
            return f"""
            <div style="margin-top:0.35rem;padding:0.4rem 0.5rem;border-radius:10px;background:rgba(148,163,184,0.08);margin-left:{pad}rem;">
              <div style="font-size:0.78rem;font-weight:600;">{name}</div>
              <div style="font-size:0.7rem;color:var(--text-muted);margin-bottom:0.2rem;">{ts}</div>
              <div style="font-size:0.8rem;">{content_html}</div>
              <div style="margin-top:0.25rem;">
                <form method='post' action='{url_for('news_comment', post_id=p.id)}' style="display:inline-flex;gap:0.25rem;align-items:center;">
                  <input type="hidden" name="parent_id" value="{c.id}">
                  <input type="text" name="content" class="form-input" style="font-size:0.75rem;padding:0.15rem 0.4rem;height:28px;" placeholder="Balas..." required>
                  <button class="btn btn-primary" type="submit" style="padding:0.2rem 0.6rem;font-size:0.7rem;">Kirim</button>
                </form>
              </div>
            </div>
            """

        comments_html = ""
        top_comments = [c for c in comments if c.parent_id is None]
        for c in top_comments:
            comments_html += render_comment(c, indent_level=0)
            for r in replies_by_parent.get(c.id, []):
                comments_html += render_comment(r, indent_level=1)

        comment_count = len(comments)

        comment_block = f"""
        <div style="margin-top:0.6rem;border-top:1px solid var(--border-soft);padding-top:0.45rem;">
          <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.3rem;">
            💬 {comment_count} komentar
          </div>
          <div>
            {comments_html or "<p style='font-size:0.75rem;color:var(--text-muted);'>Belum ada komentar. Jadilah yang pertama memberikan tanggapan.</p>"}
          </div>
          <div style="margin-top:0.45rem;">
            <form method="post" action="{url_for('news_comment', post_id=p.id)}">
              <input type="hidden" name="parent_id" value="">
              <textarea name="content" class="form-input" style="min-height:40px;font-size:0.78rem;" placeholder="Tulis komentar Anda..." required></textarea>
              <div style="margin-top:0.3rem;display:flex;justify-content:flex-end;">
                <button class="btn btn-primary" type="submit">Kirim Komentar</button>
              </div>
            </form>
          </div>
        </div>
        """

        reaction_block = f"""
        <div style="margin-top:0.55rem;display:flex;align-items:center;justify-content:space-between;font-size:0.78rem;">
          <div style="display:flex;gap:0.4rem;align-items:center;">
            <form method="post" action="{url_for('news_react', post_id=p.id)}">
              <input type="hidden" name="reaction" value="like">
              <button type="submit" class="btn btn-ghost" style="padding:0.2rem 0.45rem;font-size:0.75rem;{like_active}">👍 {like_count}</button>
            </form>
            <form method="post" action="{url_for('news_react', post_id=p.id)}">
              <input type="hidden" name="reaction" value="dislike">
              <button type="submit" class="btn btn-ghost" style="padding:0.2rem 0.45rem;font-size:0.75rem;{dislike_active}">👎 {dislike_count}</button>
            </form>
          </div>
          <div style="display:flex;gap:0.3rem;align-items:center;">
            <form method="post" action="{url_for('news_bookmark', post_id=p.id)}">
              <button type="submit" class="btn btn-ghost" style="padding:0.2rem 0.55rem;font-size:0.75rem;">
                ⭐ {bookmark_label}
              </button>
            </form>
          </div>
        </div>
        """

        cards += f"""
        <div class="news-card">
          {image_html}
          <div class="news-title">{p.title}</div>
          <div class="news-meta">{category} • Diposting: {created}</div>
          <div class="news-content">{content_preview}</div>
          {video_html}
          <div style="margin-top:0.5rem;font-size:0.75rem;color:var(--text-muted);">
            {reg_count} pendaftar
          </div>
          {daftar_btn}
          {reaction_block}
          {comment_block}
        </div>
        """

    body = f"""
    <div class=\"surface\">
      <h1 class=\"page-title\">Info Program & Dokumentasi Kegiatan</h1>
      <p class=\"page-subtitle\">Lihat pengumuman terbaru, info kegiatan, daftar program, dan berdiskusi melalui komentar.</p>

      <div class=\"news-grid\" style=\"margin-top:1rem;\">
        {cards or "<p style='font-size:0.8rem;color:var(--text-muted);'>Belum ada kabar atau dokumentasi yang dipublikasikan.</p>"}
      </div>
    </div>
    """
    return render_page(body, title="Info Beasiswa", active_nav="news")



@app.route("/news/register/<int:post_id>", methods=["POST"])
@login_required
def news_register(post_id: int):
    user = current_user()
    post = Post.query.get_or_404(post_id)

    existing = PostRegistration.query.filter_by(post_id=post.id, user_id=user.id).first()
    if existing:
        flash("Anda sudah terdaftar pada postingan ini.", "success")
        return redirect(url_for("news_list"))

    reg = PostRegistration(user_id=user.id, post_id=post.id)
    db.session.add(reg)
    db.session.commit()
    log_action(user.id, "register_post", f"{post.id}:{post.title}")
    flash("Pendaftaran berhasil dicatat.", "success")
    return redirect(url_for("news_list"))

@app.route("/news/<int:post_id>/comment", methods=["POST"])
@login_required
def news_comment(post_id: int):
    user = current_user()
    post = Post.query.get_or_404(post_id)
    content = request.form.get("content", "").strip()
    parent_id_raw = request.form.get("parent_id", "").strip()
    parent_id = int(parent_id_raw) if parent_id_raw.isdigit() else None

    if not content:
        flash("Komentar tidak boleh kosong.", "danger")
        return redirect(url_for("news_list"))

    if parent_id:
        parent = PostComment.query.filter_by(id=parent_id, post_id=post.id).first()
        if not parent:
            parent_id = None

    cmt = PostComment(
        post_id=post.id,
        user_id=user.id,
        parent_id=parent_id,
        content=content,
    )
    db.session.add(cmt)
    db.session.commit()
    log_action(user.id, "comment_post", f"{post.id}:{post.title}")
    flash("Komentar berhasil dikirim.", "success")
    return redirect(url_for("news_list"))


@app.route("/news/<int:post_id>/react", methods=["POST"])
@login_required
def news_react(post_id: int):
    user = current_user()
    post = Post.query.get_or_404(post_id)
    reaction = request.form.get("reaction", "like")
    if reaction not in ("like", "dislike"):
        flash("Aksi tidak dikenali.", "danger")
        return redirect(url_for("news_list"))

    existing = PostReaction.query.filter_by(post_id=post.id, user_id=user.id).first()
    if existing:
        if existing.reaction_type == reaction:
            db.session.delete(existing)
            action = "remove_reaction"
        else:
            existing.reaction_type = reaction
            action = "update_reaction"
    else:
        new_react = PostReaction(post_id=post.id, user_id=user.id, reaction_type=reaction)
        db.session.add(new_react)
        action = "add_reaction"

    db.session.commit()
    log_action(user.id, action, f"{reaction}:{post.id}")
    return redirect(url_for("news_list"))


@app.route("/news/<int:post_id>/bookmark", methods=["POST"])
@login_required
def news_bookmark(post_id: int):
    user = current_user()
    post = Post.query.get_or_404(post_id)

    existing = PostBookmark.query.filter_by(post_id=post.id, user_id=user.id).first()
    if existing:
        db.session.delete(existing)
        action = "remove_bookmark"
    else:
        bm = PostBookmark(post_id=post.id, user_id=user.id)
        db.session.add(bm)
        action = "add_bookmark"

    db.session.commit()
    log_action(user.id, action, str(post.id))
    return redirect(url_for("news_list"))



# ============================================================
# INIT + SIMPLE AUTO MIGRATION (TABLE + COLUMN)
# ============================================================


def run_migrations():
    """
    Simple, idempotent auto-migration.
    - Membuat tabel jika belum ada (CREATE TABLE IF NOT EXISTS)
    - Menambahkan kolom yang belum ada (ALTER TABLE ... ADD COLUMN IF NOT EXISTS)
    Tidak menghapus atau mengubah tipe kolom yang sudah ada.
    """
    stmts = [
        # USERS
        """CREATE TABLE IF NOT EXISTS users (
            id              SERIAL PRIMARY KEY,
            email           VARCHAR(255) UNIQUE NOT NULL,
            password_hash   VARCHAR(255) NOT NULL,
            full_name       VARCHAR(255) NOT NULL,
            student_id      VARCHAR(100),
            phone           VARCHAR(50),
            faculty         VARCHAR(255),
            major           VARCHAR(255),
            campus          VARCHAR(255),
            semester        VARCHAR(50),
            skills          TEXT,
            profile_photo   VARCHAR(255),
            role            VARCHAR(50) DEFAULT 'user',
            is_active       BOOLEAN DEFAULT TRUE,
            created_at      TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_at      TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )""",

        "ALTER TABLE users ADD COLUMN IF NOT EXISTS student_id VARCHAR(100)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(50)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS faculty VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS major VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS campus VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS semester VARCHAR(50)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS skills TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_photo VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'user'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()",

        # SETTINGS
        """CREATE TABLE IF NOT EXISTS settings (
            id      SERIAL PRIMARY KEY,
            key     VARCHAR(100) UNIQUE NOT NULL,
            value   VARCHAR(255) NOT NULL
        )""",

        # ACTIVITY LOGS
        """CREATE TABLE IF NOT EXISTS activity_logs (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER,
            action      VARCHAR(255) NOT NULL,
            detail      TEXT,
            created_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )""",

        # STUDENT RECORDS
        """CREATE TABLE IF NOT EXISTS student_records (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER NOT NULL,
            record_type VARCHAR(50) NOT NULL,
            title       VARCHAR(255) NOT NULL,
            level       VARCHAR(100),
            year        VARCHAR(10),
            organizer   VARCHAR(255),
            description TEXT,
            file_name   VARCHAR(255),
            file_mime   VARCHAR(100),
            file_size   INTEGER,
            file_data   BYTEA,
            created_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )""",

        # PROGRAM FORMS
        """CREATE TABLE IF NOT EXISTS program_forms (
            id          SERIAL PRIMARY KEY,
            title       VARCHAR(255) NOT NULL,
            slug        VARCHAR(100) UNIQUE NOT NULL,
            icon        VARCHAR(10),
            description VARCHAR(255),
            url         VARCHAR(500),
            is_active   BOOLEAN DEFAULT TRUE,
            created_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            created_by  INTEGER
        )""",

        # POSTS
        """CREATE TABLE IF NOT EXISTS posts (
            id           SERIAL PRIMARY KEY,
            title        VARCHAR(255) NOT NULL,
            content      TEXT,
            category     VARCHAR(50),
            image_url    VARCHAR(500),
            video_url    VARCHAR(500),
            is_published BOOLEAN DEFAULT TRUE,
            created_at   TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            created_by   INTEGER
        )""",

        # POST REGISTRATIONS
        """CREATE TABLE IF NOT EXISTS post_registrations (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER NOT NULL,
            post_id     INTEGER NOT NULL,
            created_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )""",

        # POST COMMENTS
        """CREATE TABLE IF NOT EXISTS post_comments (
            id          SERIAL PRIMARY KEY,
            post_id     INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            parent_id   INTEGER,
            content     TEXT NOT NULL,
            created_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )""",

        # POST REACTIONS
        """CREATE TABLE IF NOT EXISTS post_reactions (
            id            SERIAL PRIMARY KEY,
            post_id       INTEGER NOT NULL,
            user_id       INTEGER NOT NULL,
            reaction_type VARCHAR(20) NOT NULL,
            created_at    TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )""",

        
        # TICKETS
        """CREATE TABLE IF NOT EXISTS tickets (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER NOT NULL,
            title       VARCHAR(255) NOT NULL,
            description TEXT NOT NULL,
            status      VARCHAR(50) DEFAULT 'open',
            created_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            admin_note  TEXT
        )""",
        "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS assigned_admin_id INTEGER",
# POST BOOKMARKS
        """CREATE TABLE IF NOT EXISTS post_bookmarks (
            id          SERIAL PRIMARY KEY,
            post_id     INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            created_at  TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )""",

    ]

    # Eksekusi satu per satu, abaikan error kecil supaya tidak mengganggu startup
    with db.engine.begin() as conn:
        for sql in stmts:
            try:
                conn.execute(text(sql))
            except Exception as e:  # pragma: no cover - hanya logging ringan
                print(f"[MIGRATION WARN] {e}")


def init_db():

    # Auto-add missing columns
    from sqlalchemy import text as _text
    with db.engine.connect() as conn:
        conn.execute(_text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='tickets' AND column_name='category'
            ) THEN
                ALTER TABLE tickets ADD COLUMN category VARCHAR(100);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='tickets' AND column_name='attachment_path'
            ) THEN
                ALTER TABLE tickets ADD COLUMN attachment_path VARCHAR(255);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='tickets' AND column_name='completed_at'
            ) THEN
                ALTER TABLE tickets ADD COLUMN completed_at TIMESTAMP;
            END IF;
        END$$;
        """))

    # Buat semua tabel dari model (aman jika sudah ada)
    db.create_all()
    # Jalankan auto-migration sederhana untuk kolom/tabel yang mungkin belum ada
    run_migrations()
    # Inisialisasi setting default
    if not Setting.query.filter_by(key="allow_admin_signup").first():
        set_setting("allow_admin_signup", "false")

# Chat API routes added
@app.route("/ticket/<int:ticket_id>/messages")
@login_required
def chat_messages(ticket_id):
    user = current_user()
    ticket = Ticket.query.get_or_404(ticket_id)
    # Hanya admin atau pemilik tiket yang boleh mengakses
    if user.role != "admin" and ticket.user_id != user.id:
        return jsonify([])
    msgs = TicketMessage.query.filter_by(ticket_id=ticket_id).order_by(TicketMessage.created_at.asc()).all()

    # Tandai pesan sebagai sudah dibaca untuk sisi yang membuka percakapan
    changed = False
    if user.role == "admin":
        for m in msgs:
            if m.sender_id != user.id and not m.is_read_admin:
                m.is_read_admin = True
                changed = True
    else:
        for m in msgs:
            if m.sender_id != user.id and not m.is_read_user:
                m.is_read_user = True
                changed = True
    if changed:
        db.session.commit()

    return jsonify([
        {
            "sender": m.sender.full_name if m.sender else "",
            "me": m.sender_id == user.id,
            "text": m.message,
            "time": m.created_at.astimezone(WIB).strftime("%d %b %Y, %H:%M WIB") if m.created_at else ""
        }
        for m in msgs
    ])


@app.route("/ticket/<int:ticket_id>/send", methods=["POST"])
@login_required
def chat_send(ticket_id):
    user = current_user()
    ticket = Ticket.query.get_or_404(ticket_id)
    # Hanya admin atau pemilik tiket yang boleh mengirim pesan
    if user.role != "admin" and ticket.user_id != user.id:
        return jsonify({"success": False})
    msg = (request.form.get("message") or "").strip()
    if not msg:
        return jsonify({"success": False})
    m = TicketMessage(ticket_id=ticket_id, sender_id=user.id, message=msg)
    # Pesan baru otomatis belum dibaca oleh sisi lain
    if user.role == "admin":
        m.is_read_admin = True
        m.is_read_user = False
    else:
        m.is_read_admin = False
        m.is_read_user = True
    db.session.add(m)
    db.session.commit()
    return jsonify({"success": True})


# ============================================================
# INITIALIZE DATABASE AT STARTUP (RENDER + LOCAL)
# ============================================================

with app.app_context():
    try:
        init_db()
    except Exception as e:
        print("INIT_DB ERROR:", e)


# ============================================================
# LOCAL DEVELOPMENT ENTRYPOINT
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

    with app.app_context():
        init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, port=port)
