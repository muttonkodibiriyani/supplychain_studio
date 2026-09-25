"""Prevent private-data formats and credentials from entering source releases."""
from pathlib import Path

import pytest

from scripts import package_source


@pytest.mark.parametrize('relative,expected', [
    ('tests/fixtures/real_invoice.pdf', False),
    ('docs/customer_master.xlsx', False),
    ('tests/private_catalog.csv', False),
    ('tests/private_aliases.json', False),
    ('tests/fixtures/sample_invoice.csv', True),
    ('tests/fixtures/sample_catalog.json', True),
    ('src/App.tsx', True),
])
def test_only_source_and_named_synthetic_data_formats_are_selected(tmp_path, monkeypatch, relative, expected):
    monkeypatch.setattr(package_source, 'ROOT', tmp_path)
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('synthetic content')
    assert package_source.allowed(path) is expected


def test_external_symlink_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / 'source'
    root.mkdir()
    monkeypatch.setattr(package_source, 'ROOT', root)
    private = tmp_path / 'private.txt'
    private.write_text('private')
    link = root / 'example.py'
    link.symlink_to(private)
    assert not package_source.allowed(link)
    with pytest.raises(SystemExit, match='symlink'):
        package_source.validate_source([link])


def test_secret_value_never_appears_in_validation_error(tmp_path, monkeypatch):
    monkeypatch.setattr(package_source, 'ROOT', tmp_path)
    source = tmp_path / 'example.py'
    secret = 'ghp_' + 'x' * 40
    source.write_text('credential = ' + repr(secret))
    with pytest.raises(SystemExit) as error:
        package_source.validate_source([source])
    assert secret not in str(error.value)
    assert 'example.py' in str(error.value)
