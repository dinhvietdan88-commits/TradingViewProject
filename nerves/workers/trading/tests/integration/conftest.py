"""
Integration test configuration.
Registers custom pytest markers used by integration-level tests.
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "staging: marks tests that hit a live staging server (deselect with '-m \"not staging\"')",
    )
