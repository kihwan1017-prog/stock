from pathlib import Path

import psycopg
from dotenv import dotenv_values


ENV_PATH = Path(r"E:\StockTrading\secrets\stock-platform.env")


def main() -> None:
    if not ENV_PATH.exists():
        raise FileNotFoundError(f"환경설정 파일이 없습니다: {ENV_PATH}")

    config = dotenv_values(ENV_PATH)

    required_keys = [
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
    ]

    missing_keys = [
        key for key in required_keys
        if not config.get(key)
    ]

    if missing_keys:
        raise ValueError(
            f"환경설정 값이 비어 있습니다: {', '.join(missing_keys)}"
        )

    connection_info = (
        f"host={config['DB_HOST']} "
        f"port={config['DB_PORT']} "
        f"dbname={config['DB_NAME']} "
        f"user={config['DB_USER']} "
        f"password={config['DB_PASSWORD']}"
    )

    with psycopg.connect(connection_info) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_user,
                    current_database(),
                    current_setting('TimeZone'),
                    version()
                """
            )

            row = cursor.fetchone()

    print("PostgreSQL 연결 성공")
    print(f"사용자: {row[0]}")
    print(f"데이터베이스: {row[1]}")
    print(f"시간대: {row[2]}")
    print(f"버전: {row[3]}")


if __name__ == "__main__":
    main()
