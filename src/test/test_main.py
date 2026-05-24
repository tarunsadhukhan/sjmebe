# src/tests/test_main.py

from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)

def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to our FastAPI application!"}

def test_read_item():
    response = client.get("/items/42")
    assert response.status_code == 200
    assert response.json()["item_id"] == 42
