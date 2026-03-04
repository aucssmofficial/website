from pathlib import Path
import os

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_from_directory,
    session,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import qrcode


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
QR_FOLDER = BASE_DIR / "static" / "qr"


def create_app():
    app = Flask(__name__)

    # Security-related configuration
    app.config["SECRET_KEY"] = os.environ.get(
        "AUCSSM_SECRET_KEY", "change-this-secret-key-in-production"
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(BASE_DIR / "aucssm.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
    app.config["QR_FOLDER"] = str(QR_FOLDER)
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB uploads

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["QR_FOLDER"], exist_ok=True)

    db.init_app(app)

    with app.app_context():
        db.create_all()
        ensure_default_admin()

    register_routes(app)
    return app


db = SQLAlchemy()


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)


class Member(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    roll_number = db.Column(db.String(64), unique=True, nullable=False)
    department = db.Column(db.String(120), nullable=False)
    designation = db.Column(db.String(120), nullable=False)
    session = db.Column(db.String(64), nullable=False)
    picture_filename = db.Column(db.String(255), nullable=True)
    is_verified = db.Column(db.Boolean, default=True, nullable=False)


def ensure_default_admin():
    username = "aucssmadmin"
    plain_password = "usman11chA@"

    admin = Admin.query.filter_by(username=username).first()
    password_hash = generate_password_hash(plain_password)

    # For this small internal tool we always ensure the default
    # credentials exist and are in sync with the configured password.
    if not admin:
        admin = Admin(username=username, password_hash=password_hash)
        db.session.add(admin)
    else:
        admin.password_hash = password_hash

    db.session.commit()


def login_required(view_func):
    from functools import wraps

    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("admin_username"):
            flash("Please login to access this page.", "warning")
            return redirect(url_for("admin_login"))
        return view_func(*args, **kwargs)

    return wrapped


def allowed_image(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in {"png", "jpg", "jpeg", "gif"}


def generate_member_qr(app: Flask, roll_number: str) -> str:
    url = url_for("member_detail", roll_number=roll_number, _external=True)
    qr_img = qrcode.make(url)

    filename = f"{secure_filename(roll_number)}.png"
    qr_path = Path(app.config["QR_FOLDER"]) / filename
    qr_img.save(qr_path)
    return filename


def register_routes(app: Flask):
    @app.route("/")
    def home():
        return render_template("home.html")

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            admin = Admin.query.filter_by(username=username).first()
            if admin and check_password_hash(admin.password_hash, password):
                session.clear()
                session["admin_username"] = admin.username
                return redirect(url_for("admin_dashboard"))

            flash("Invalid username or password.", "danger")

        return render_template("admin_login.html")

    @app.route("/admin/dashboard", methods=["GET", "POST"])
    @login_required
    def admin_dashboard():
        qr_filename = None
        new_member = None

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            roll_number = request.form.get("roll_number", "").strip()
            department = request.form.get("department", "").strip()
            designation = request.form.get("designation", "").strip()
            session_val = request.form.get("session", "").strip()
            picture = request.files.get("picture")

            if not all([name, roll_number, department, designation, session_val]):
                flash("All fields except picture are required.", "danger")
            else:
                existing = Member.query.filter_by(roll_number=roll_number).first()
                if existing:
                    flash("A member with this roll number already exists.", "warning")
                else:
                    picture_filename = None
                    if picture and picture.filename:
                        if allowed_image(picture.filename):
                            safe_name = secure_filename(
                                f"{roll_number}_{picture.filename}"
                            )
                            picture_path = Path(app.config["UPLOAD_FOLDER"]) / safe_name
                            picture.save(picture_path)
                            picture_filename = safe_name
                        else:
                            flash("Invalid image type. Use PNG/JPG/JPEG/GIF.", "danger")
                            return redirect(url_for("admin_dashboard"))

                    new_member = Member(
                        name=name,
                        roll_number=roll_number,
                        department=department,
                        designation=designation,
                        session=session_val,
                        picture_filename=picture_filename,
                        is_verified=True,
                    )
                    db.session.add(new_member)
                    db.session.commit()

                    qr_filename = generate_member_qr(app, roll_number)
                    flash("Member added successfully. QR code generated.", "success")

        members = Member.query.order_by(Member.id.desc()).all()
        return render_template(
            "admin_dashboard.html",
            members=members,
            qr_filename=qr_filename,
            new_member=new_member,
        )

    @app.route("/admin/logout")
    def admin_logout():
        session.clear()
        flash("Logged out successfully.", "info")
        return redirect(url_for("home"))

    @app.route("/member/<roll_number>")
    def member_detail(roll_number):
        member = Member.query.filter_by(roll_number=roll_number).first()
        if not member:
            return render_template("member_not_found.html", roll_number=roll_number), 404
        return render_template("member_card.html", member=member)

    @app.route("/qr/<filename>")
    @login_required
    def download_qr(filename):
        return send_from_directory(
            app.config["QR_FOLDER"],
            secure_filename(filename),
            as_attachment=True,
            download_name=filename,
        )

    @app.route("/admin/member/<int:member_id>/delete", methods=["POST"])
    @login_required
    def delete_member(member_id):
        member = Member.query.get_or_404(member_id)

        # Remove associated picture file if it exists
        if member.picture_filename:
            picture_path = Path(app.config["UPLOAD_FOLDER"]) / member.picture_filename
            if picture_path.exists():
                try:
                    picture_path.unlink()
                except OSError:
                    # Failing to delete the file should not block member removal
                    pass

        # Remove associated QR code file if it exists
        qr_filename = f"{secure_filename(member.roll_number)}.png"
        qr_path = Path(app.config["QR_FOLDER"]) / qr_filename
        if qr_path.exists():
            try:
                qr_path.unlink()
            except OSError:
                pass

        db.session.delete(member)
        db.session.commit()
        flash("Member deleted successfully.", "success")
        return redirect(url_for("admin_dashboard"))


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)

