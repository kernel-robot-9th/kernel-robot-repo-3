"""Loopback UI preview: mock replay or disconnected field setup; no production DB."""
from .api import create_app as api_app
from .distributed import DistributedEngine
from .reference import ReferenceEngine
import os


def create_app():
    # A fresh in-memory run per preview start; never opens a production DB.
    if os.getenv('SHOP_PREVIEW_PROFILE') == 'field':
        return api_app(engine=DistributedEngine(mode='hardware', test_only=True))
    return api_app(engine=ReferenceEngine() if os.getenv('SHOP_MOTION_BACKEND') == 'reference_v4' else DistributedEngine())
