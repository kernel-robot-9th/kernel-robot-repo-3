"""Loopback-only mock preview factory. Production Ubuntu retains its DB lock."""
from .api import create_app as api_app
from .distributed import DistributedEngine


def create_app():
    # A fresh in-memory run per preview start; never opens a production DB.
    return api_app(engine=DistributedEngine())
