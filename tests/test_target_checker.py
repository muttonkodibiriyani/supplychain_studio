"""Regression tests for the portable workbook acceptance tool."""
from datetime import date

import openpyxl
import pytest

from scripts.check_target_workbook import COLUMNS, check


def workbook(tmp_path):
    book = openpyxl.Workbook()
    book.remove(book.active)
    for name, columns in COLUMNS.items():
        book.create_sheet(name).append(columns)
    book['Header'].append(['0001', '000045', '0002', '0003', '0004', 'S',
                           date(2026, 9, 25), 20, 1, None, None, None, None])
    book['Tax_Breakdown'].append(['0001', '0005', 20])
    book['Details'].append(['0001', '000006', '00000007', 10, 2, '0005'])
    path = tmp_path / 'synthetic.xlsx'
    return book, path


def test_valid_target_preserves_text_identifiers(tmp_path):
    book, path = workbook(tmp_path)
    book.save(path)
    assert check(path)[0] == []


@pytest.mark.parametrize('sheet,cell,value,message', [
    ('Header', 'B2', '=1+1', 'formula-injection'),
    ('Details', 'B2', 6, 'stored as a number'),
    ('Details', 'A2', '9999', 'no matching Header'),
    ('Tax_Breakdown', 'C2', 21, 'Tax Basis does not reconcile'),
    ('Details', 'D2', 'NaN', 'non-numeric'),
    ('Details', 'D2', 11, 'does not equal sum of Details'),
])
def test_invalid_target_is_rejected(tmp_path, sheet, cell, value, message):
    book, path = workbook(tmp_path)
    book[sheet][cell] = value
    book.save(path)
    assert any(message in failure for failure in check(path)[0])


def test_high_precision_discounted_unit_cost_reconciles_at_line_precision(tmp_path):
    book, path = workbook(tmp_path)
    book['Header']['H2'] = 1000
    book['Tax_Breakdown']['C2'] = 1000
    book['Details']['D2'] = 3.3333333333
    book['Details']['E2'] = 300
    book.save(path)
    assert check(path)[0] == []


def test_cli_returns_nonzero_for_nonconformant_workbook(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    script = Path(__file__).resolve().parents[1] / 'scripts/check_target_workbook.py'
    book, path = workbook(tmp_path)
    book.save(path)
    valid = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True)
    assert valid.returncode == 0, valid.stdout
    book['Details']['D2'] = 11
    book.save(path)
    invalid = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True)
    assert 'NON-CONFORMANT' in invalid.stdout
    assert invalid.returncode == 1, invalid.stdout
