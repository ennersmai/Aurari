"""Trivial passing test to verify test suite runs."""

def test_suite_runs():
    """Basic test to confirm pytest works."""
    assert True


def test_fake_db_fixture(fake_db):
    """Test that the fake_db fixture works."""
    assert fake_db is not None
    assert hasattr(fake_db, 'query')
    assert hasattr(fake_db, 'create')
    assert hasattr(fake_db, 'select')
    assert hasattr(fake_db, 'merge')
    assert hasattr(fake_db, 'delete')