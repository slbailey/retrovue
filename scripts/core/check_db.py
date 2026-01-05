from __future__ import annotations

import re

from sqlalchemy import create_engine, text

from retrovue.infra.settings import settings


def redact(url: str) -> str:
    return re.sub(r"://([^:]+):([^@]+)@", lambda m: f"://{m.group(1)}:***@", url)


def main() -> None:
    urls: dict[str, str | None] = {
        "DATABASE_URL": settings.database_url,
        "TEST_DATABASE_URL": settings.test_database_url,
    }
    for k, v in urls.items():
        if v:
            print(f"{k} = {redact(v)}")

    for name, url in [(k, v) for k, v in urls.items() if v]:
        print(f"\nTesting connect to {name}...")
        try:
            e = create_engine(url, future=True)
            with e.connect() as conn:
                ver = conn.execute(text("select version()"))
                print("Connected ok:", next(ver)[0].split(" on ")[0])
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()










