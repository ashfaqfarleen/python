from flask_server import db, app

with app.app_context():
    db.create_all()
    print("Tables created!")
