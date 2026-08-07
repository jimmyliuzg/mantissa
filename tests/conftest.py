"""Shared test configuration and fixtures for all test layers."""
import os

# Absolute path to the tests/fixtures/ directory, accessible from any layer.
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
