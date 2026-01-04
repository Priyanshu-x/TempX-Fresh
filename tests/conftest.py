import pytest
from app import app, db, User
from flask_login import current_user

@pytest.fixture
def test_client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False # Disable CSRF for easier API testing
    
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            yield client
            db.session.remove()
            db.drop_all()

@pytest.fixture
def auth_client(test_client):
    with app.app_context():
        user = User(username='admin')
        user.set_password('admin123')
        db.session.add(user)
        db.session.commit()
    return test_client

def login(client, username, password):
    return client.post('/admin/login', data=dict(
        username=username,
        password=password
    ), follow_redirects=True)

def logout(client):
    return client.get('/admin/logout', follow_redirects=True)
