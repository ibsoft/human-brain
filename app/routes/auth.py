from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import OperationalError

from app.extensions import db, limiter
from app.models import User
from app.security.auth import lockout_until
from app.services.audit_service import AuditService

auth_bp = Blueprint("auth", __name__)


def setup_required():
    try:
        return User.query.count() == 0
    except OperationalError:
        db.session.rollback()
        if current_app.config.get("AUTO_CREATE_DEV_DB", False):
            db.create_all()
            return User.query.count() == 0
        return True


@auth_bp.route("/setup", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def setup():
    if not setup_required():
        return redirect(url_for("main.dashboard" if current_user.is_authenticated else "auth.login"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("name", "").strip() or "Administrator"
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not email or len(password) < 12:
            flash("Use a valid email and a password with at least 12 characters.", "danger")
            return render_template("auth/setup.html")
        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("auth/setup.html")
        user = User(email=email, name=name, role="admin")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        AuditService.log("auth.first_admin_created", "user", user.id)
        db.session.commit()
        login_user(user)
        return redirect(url_for("main.dashboard"))
    return render_template("auth/setup.html")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if setup_required():
        return redirect(url_for("auth.setup"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.locked_until and user.locked_until > datetime.utcnow():
            flash("Account temporarily locked.", "danger")
            return render_template("auth/login.html")
        if user and user.check_password(password):
            user.failed_login_count = 0
            user.locked_until = None
            db.session.commit()
            login_user(user)
            AuditService.log("auth.login", "user", user.id)
            db.session.commit()
            return redirect(url_for("main.dashboard"))
        if user:
            user.failed_login_count += 1
            user.locked_until = lockout_until(user.failed_login_count)
            db.session.commit()
        flash("Invalid credentials.", "danger")
    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    AuditService.log("auth.logout", "user", current_user.id)
    db.session.commit()
    logout_user()
    return redirect(url_for("auth.login"))
