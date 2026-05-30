import os
import sys

from app import create_app
from app.extensions import celery

app = create_app(os.getenv("FLASK_ENV", "development"))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        args = sys.argv[2:]
        with app.app_context():
            from app.cli import register_commands

            if command == "create-admin":
                email = args[args.index("--email") + 1] if "--email" in args else input("Email: ")
                name = args[args.index("--name") + 1] if "--name" in args else "Administrator"
                import getpass

                password = args[args.index("--password") + 1] if "--password" in args else getpass.getpass("Password: ")
                from app.extensions import db
                from app.models import User

                user = User(email=email.lower(), name=name, role="admin")
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                print(f"Created admin {email}")
            elif command == "rebuild-index":
                from flask.cli import ScriptInfo

                app.cli.commands["rebuild-index"].main(args=args, obj=ScriptInfo(create_app=lambda: app), standalone_mode=False)
            elif command in {"vector-health", "test-search", "benchmark-search", "backup", "restore", "run-worker", "seed-demo-data"}:
                from flask.cli import ScriptInfo

                app.cli.commands[command].main(args=args, obj=ScriptInfo(create_app=lambda: app), standalone_mode=False)
            else:
                print(f"Unknown command: {command}")
                sys.exit(2)
    else:
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
