import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    API_ID: int = int(os.environ["API_ID"])
    API_HASH: str = os.environ["API_HASH"]
    SESSION_STRING: str = os.environ["SESSION_STRING"]
    BOT_TOKEN: str = os.environ["BOT_TOKEN"]
    ADMIN_USER_ID: int = int(os.environ["ADMIN_USER_ID"])
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///forwarder.db")
    DB_PATH: str = os.environ.get("DB_PATH", "forwarder.db")


config = Config()
