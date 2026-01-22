from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt

# Create instances but don't initialize with app yet
db = SQLAlchemy()
bcrypt = Bcrypt()