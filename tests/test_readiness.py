from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db.database import check_database
from app.main import app


def test_readyz_database_available() -> None:
    with (
        patch("app.main.check_database", return_value=True),
        TestClient(app) as client,
    ):
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_database_unavailable() -> None:
    with (
        patch("app.main.check_database", return_value=False),
        TestClient(app) as client,
    ):
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_database_connection_failure() -> None:
    with patch("app.db.database.engine.connect") as connect:
        connect.side_effect = OperationalError(
            "SELECT 1",
            {},
            Exception("Connection failed"),
        )

        assert check_database() is False


def test_database_connection_success() -> None:
    with patch("app.db.database.engine.connect") as connect:
        connection = MagicMock()
        connect.return_value.__enter__.return_value = connection

        assert check_database() is True
        connection.execute.assert_called_once()
