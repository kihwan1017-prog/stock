from sqlalchemy import text
import httpx

from stock_platform.database.engine import create_database_engine


def check_database():
    try:
        engine = create_database_engine()

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        return {
            "status": "UP"
        }

    except Exception as ex:
        return {
            "status": "DOWN",
            "message": str(ex)
        }


def check_ollama():
    try:
        response = httpx.get(
            "http://127.0.0.1:11434/api/tags",
            timeout=3.0,
        )

        response.raise_for_status()

        models = response.json()["models"]

        return {
            "status": "UP",
            "model_count": len(models),
        }

    except Exception as ex:
        return {
            "status": "DOWN",
            "message": str(ex)
        }