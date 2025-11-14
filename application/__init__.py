import os
from flask import Flask, request
from flask_cors import CORS
from dotenv import load_dotenv

from application.database import db
from flask_login import LoginManager
from application.models import User  # <- phải đúng đường dẫn

load_dotenv()

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), '..', 'templates'),
    static_folder=os.path.join(os.path.dirname(__file__), '..', 'static'),
)

# Config
CORS(app)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'test')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///database.sqlite3')
app.config['GEMINI_MODEL'] = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')

# Init DB
db.init_app(app)

# ----- Flask Login -----
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
# -------------------------

# Blueprint chatbot
from application.bookbot import bookbot_bp
app.register_blueprint(bookbot_bp)

# Import routes cũ
from application import routes  # noqa: F401

# Create database
with app.app_context():
    db.create_all()
