import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_dashboard_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "PriceDrop" in response.text


def test_selector_test_endpoint(client):
    # Testing an empty/invalid URL
    response = client.post(
        "/api/test-selector",
        json={"url": "https://invalid-non-existent-domain-12345.com", "css_selector": ".price"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["price"] is None


def test_create_and_get_product(client):
    payload = {
        "name": "Wireless Noise Cancelling Headphones",
        "url": "https://example.com/item/123",
        "css_selector": ".price-tag",
        "target_price": 149.99,
    }
    # 1. Create product
    create_res = client.post("/products", json=payload)
    assert create_res.status_code == 201
    data = create_res.json()
    assert data["name"] == payload["name"]
    assert data["target_price"] == 149.99
    product_id = data["id"]

    # 2. Get list of products
    list_res = client.get("/products")
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1

    # 3. Get single product
    get_res = client.get(f"/products/{product_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == product_id

    # 4. Update product target price
    update_res = client.put(f"/products/{product_id}", json={"target_price": 129.99})
    assert update_res.status_code == 200
    assert update_res.json()["target_price"] == 129.99

    # 5. Get product history (initially empty)
    history_res = client.get(f"/products/{product_id}/history")
    assert history_res.status_code == 200
    assert history_res.json() == []

    # 5. Delete product
    del_res = client.delete(f"/products/{product_id}")
    assert del_res.status_code == 204

    # 6. Verify deleted
    get_again = client.get(f"/products/{product_id}")
    assert get_again.status_code == 404
