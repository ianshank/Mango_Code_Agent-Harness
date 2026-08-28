"""Tests for the FastAPI orchestration server.

``harness/shared/tests`` has always been a package; this directory was not,
so its module basenames lived in a flat global namespace. A second
``test_main.py`` anywhere under ``testpaths`` would have collided at import
with an error that names neither file.
"""
