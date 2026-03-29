from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import models for metadata registration
from app import models  # noqa: E402,F401
