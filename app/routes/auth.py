from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import OperationalError

from app.extensions import db, limiter
from app.models import User
from app.security.auth import lockout_until
from app.security.totp import verify_totp
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
        mfa_code = request.form.get("mfa_code", "")
        user = User.query.filter_by(email=email).first()
        if user and user.locked_until and user.locked_until > datetime.utcnow():
            flash("Account temporarily locked.", "danger")
            return render_template("auth/login.html")
        if user and user.check_password(password):
            if user.mfa_enabled and not verify_totp(user.mfa_secret, mfa_code):
                flash("Enter a valid MFA code.", "danger")
                return render_template("auth/login.html", email=email, mfa_required=True)
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


@auth_bp.post("/profile/password")
@login_required
@limiter.limit("5 per minute")
def change_password():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    if not current_user.check_password(current_password):
        flash("Current password is incorrect.", "danger")
        return redirect(request.referrer or url_for("main.dashboard"))
    if len(new_password) < 12:
        flash("New password must be at least 12 characters.", "danger")
        return redirect(request.referrer or url_for("main.dashboard"))
    if new_password != confirm_password:
        flash("New passwords do not match.", "danger")
        return redirect(request.referrer or url_for("main.dashboard"))
    current_user.set_password(new_password)
    AuditService.log("auth.password_changed", "user", current_user.id, target_type="user", target_id=current_user.id)
    db.session.commit()
    flash("Password updated.", "success")
    return redirect(request.referrer or url_for("main.dashboard"))


@auth_bp.post("/profile/theme")
@login_required
def update_theme():
    theme = request.form.get("default_theme", "dark").strip().lower()
    if theme not in {"dark", "light"}:
        flash("Choose a valid theme.", "danger")
        return redirect(request.referrer or url_for("main.dashboard"))
    current_user.default_theme = theme
    AuditService.log("auth.default_theme_updated", "user", current_user.id, target_type="user", target_id=current_user.id, metadata={"theme": theme})
    db.session.commit()
    flash("Default theme updated.", "success")
    return redirect(request.referrer or url_for("main.dashboard"))


@auth_bp.post("/profile/mfa/enable")
@login_required
@limiter.limit("5 per minute")
def enable_mfa():
    current_password = request.form.get("current_password", "")
    secret = request.form.get("mfa_secret", "").strip().replace(" ", "").upper()
    code = request.form.get("mfa_code", "")
    if not current_user.check_password(current_password):
        flash("Current password is incorrect.", "danger")
        return redirect(request.referrer or url_for("main.dashboard"))
    if not secret or not verify_totp(secret, code):
        flash("MFA code did not verify. Check the secret in your authenticator app.", "danger")
        return redirect(request.referrer or url_for("main.dashboard"))
    current_user.mfa_enabled = True
    current_user.mfa_secret = secret
    current_user.mfa_enabled_at = datetime.utcnow()
    AuditService.log("auth.mfa_enabled", "user", current_user.id, target_type="user", target_id=current_user.id)
    db.session.commit()
    flash("MFA enabled.", "success")
    return redirect(request.referrer or url_for("main.dashboard"))


@auth_bp.post("/profile/mfa/disable")
@login_required
@limiter.limit("5 per minute")
def disable_mfa():
    current_password = request.form.get("current_password", "")
    code = request.form.get("mfa_code", "")
    if not current_user.check_password(current_password):
        flash("Current password is incorrect.", "danger")
        return redirect(request.referrer or url_for("main.dashboard"))
    if current_user.mfa_enabled and not verify_totp(current_user.mfa_secret, code):
        flash("Enter a valid MFA code to disable MFA.", "danger")
        return redirect(request.referrer or url_for("main.dashboard"))
    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    current_user.mfa_enabled_at = None
    AuditService.log("auth.mfa_disabled", "user", current_user.id, target_type="user", target_id=current_user.id)
    db.session.commit()
    flash("MFA disabled.", "success")
    return redirect(request.referrer or url_for("main.dashboard"))
