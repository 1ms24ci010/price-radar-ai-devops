def create_product(client, **overrides):
    payload = {
        "name": "Test headphones",
        "marketplace": "Amazon",
        "product_url": "https://example.com/item",
        "current_price": 3000,
        "target_price": 2500,
        "drop_amount": 300,
        "alert_mode": "either",
    }
    payload.update(overrides)
    return client.post("/api/products", json=payload)


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "healthy"


def test_home_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200


def test_create_product_and_list_state(client):
    response = create_product(client)
    assert response.status_code == 200
    product_id = response.get_json()["id"]
    state = client.get("/api/state").get_json()
    assert any(item["id"] == product_id for item in state["products"])


def test_price_drop_triggers_alert_and_history(client):
    product = create_product(client).get_json()
    response = client.post("/api/price-update", json={
        "product_id": product["id"], "current_price": 2600, "source": "Automated test observation"
    })
    assert response.status_code == 200
    assert response.get_json()["alert_triggered"] is True
    history = client.get(f"/api/products/{product['id']}/history").get_json()["history"]
    assert len(history) == 2


def test_invalid_price_is_rejected(client):
    product = create_product(client).get_json()
    response = client.post("/api/price-update", json={
        "product_id": product["id"], "current_price": -10
    })
    assert response.status_code == 400
