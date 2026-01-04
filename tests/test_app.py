def test_home_page(test_client):
    response = test_client.get('/')
    assert response.status_code == 200
    assert b"Public File Board" in response.data

def test_admin_login(auth_client):
    response = login(auth_client, 'admin', 'admin123')
    assert b"Logged in successfully" in response.data
    assert b"Admin Panel" in response.data

def test_admin_login_fail(test_client):
    response = login(test_client, 'admin', 'wrongpass')
    assert b"Invalid username or password" in response.data

def test_upload_file(test_client):
    data = {
        'files[]': (b'my file contents', 'test_file.txt')
    }
    response = test_client.post('/upload', data=data, content_type='multipart/form-data', follow_redirects=True)
    assert b"1 file(s) uploaded successfully" in response.data
    assert b"test_file.txt" in response.data

def test_admin_access_denied(test_client):
    response = test_client.get('/admin', follow_redirects=True)
    assert b"Please log in to access this page" in response.data or b"Admin Login" in response.data
