"""Prevent private-data formats and credentials from entering source releases."""
from pathlib import Path
import os
import shutil
import subprocess

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


# --- documentation allowlist -------------------------------------------------

SHIPPED_DOCS = ['MAC_SETUP.md', 'WINDOWS_SETUP.md', 'OPERATOR_TRAINING.md',
                'DELIVERY.md', 'OPEN_SOURCE.md', 'EXTRACTION.md']
MEASUREMENT_DOCS = ['IMPLEMENTATION_ACCEPTANCE.md', 'REAL_CORPUS_EVALUATION.md',
                    'VOLUME_RESULTS.md', 'RELEASE_VALIDATION.md', 'VERIFICATION.md']


def _minimal_root(tmp_path):
    """A tree with every file main() requires, plus every docs/ name the repo has."""
    root = tmp_path / 'source'
    for name in package_source.FILES:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text('# synthetic\n')
    for name in ['public/favicon.svg', 'public/THIRD_PARTY_NOTICES.txt', 'backend/app.py',
                 'backend/extraction.py', 'src/App.tsx', 'public/templates/invoice.csv',
                 'public/templates/rms-item-master.csv']:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text('synthetic\n')
    for name in SHIPPED_DOCS + MEASUREMENT_DOCS + ['UNLISTED_NEW_DOC.md']:
        (root / 'docs').mkdir(exist_ok=True)
        (root / 'docs' / name).write_text(f'# {name}\n')
    return root


def _point_packager_at(monkeypatch, root):
    monkeypatch.setattr(package_source, 'ROOT', root)
    monkeypatch.setattr(package_source, 'OUTPUT', root / 'public/invoice-studio-source.zip')
    monkeypatch.setattr(package_source, 'PACKAGE_JSON', root / 'public/source-package.json')


def test_docs_are_an_explicit_allowlist_not_a_directory_walk(tmp_path, monkeypatch):
    root = _minimal_root(tmp_path)
    _point_packager_at(monkeypatch, root)
    selected = {p.relative_to(root).as_posix() for p in package_source.selected_files()}
    assert {f'docs/{n}' for n in SHIPPED_DOCS} <= selected
    assert not {f'docs/{n}' for n in MEASUREMENT_DOCS} & selected
    assert 'docs/UNLISTED_NEW_DOC.md' not in selected
    assert 'docs' not in package_source.DIRECTORIES


# --- identifier / capability class -------------------------------------------

# Samples are assembled at runtime so this file itself carries none of the forms:
# tests/ is shipped in the package and the guard reads it too.
G = 'goo' + 'gle.com'
IDENTIFIER_SAMPLES = [
    'https://docs.' + G + '/spreadsheets/d/abc/edit',
    'https://drive.' + G + '/file/d/abc/view',
    'https://example.com/report?usp=' + 'sharing',
    'https://example.com/x?id=1&ou' + 'id=123456789',
    'https://example.com/x?user' + 'Id=42',
    'wrote results to /ho' + 'me/alice/project/out.json',
    'wrote results to /Us' + 'ers/alice/project/out.json',
    'saved to C:' + '\\Users' + '\\alice' + '\\Documents' + '\\out.json',
]


@pytest.mark.parametrize('sample', IDENTIFIER_SAMPLES)
def test_identifier_and_capability_forms_are_rejected_without_printing_them(tmp_path, monkeypatch, sample):
    monkeypatch.setattr(package_source, 'ROOT', tmp_path)
    source = tmp_path / 'notes.md'
    source.write_text('see ' + sample + '\n')
    with pytest.raises(SystemExit) as error:
        package_source.validate_source([source])
    assert 'notes.md' in str(error.value)
    assert sample not in str(error.value)


PLACEHOLDER_SAMPLES = [
    'move it under your account, for example C:' + '\\Users' + '\\your-name' + '\\InvoiceStudio',
    'for example /Us' + 'ers/your-name/InvoiceStudio or /ho' + 'me/<user>/InvoiceStudio',
    'the container path /app/data/invoices.db',
    'https://github.com/example/invoice-studio',
]


@pytest.mark.parametrize('sample', PLACEHOLDER_SAMPLES)
def test_documented_placeholders_and_container_paths_pass(tmp_path, monkeypatch, sample):
    monkeypatch.setattr(package_source, 'ROOT', tmp_path)
    source = tmp_path / 'notes.md'
    source.write_text(sample + '\n')
    package_source.validate_source([source])


# --- the check that reads the DECODED package, not the tree -------------------

def _decoded_entries(package_json):
    import base64
    import hashlib
    import io
    import json
    from zipfile import ZipFile
    payload = json.loads(package_json.read_text())
    data = base64.b64decode(payload['base64'])
    assert hashlib.sha256(data).hexdigest() == payload['sha256']
    with ZipFile(io.BytesIO(data)) as archive:
        return {info.filename: archive.read(info.filename) for info in archive.infolist()}


def test_decoded_package_excludes_measurement_docs_and_every_private_pattern(tmp_path, monkeypatch):
    root = _minimal_root(tmp_path)
    _point_packager_at(monkeypatch, root)
    package_source.main()
    entries = _decoded_entries(root / 'public/source-package.json')
    names = set(entries)
    assert {f'invoice-studio/docs/{n}' for n in SHIPPED_DOCS} <= names
    assert not {f'invoice-studio/docs/{n}' for n in MEASUREMENT_DOCS} & names
    assert 'invoice-studio/docs/UNLISTED_NEW_DOC.md' not in names
    selected = {'invoice-studio/' + p.relative_to(root).as_posix() for p in package_source.selected_files()}
    assert names <= selected
    for name, content in entries.items():
        text = content.decode('utf-8', errors='replace')
        for pattern in package_source.PRIVATE_CONTENT_PATTERNS:
            assert not pattern.search(text), f'{pattern.pattern!r} matched inside {name}'


# --- the whole-tree guard: a hit outside the archive allowlist still fails ---------

def test_pattern_hit_outside_the_archive_allowlist_fails_the_build_closed(tmp_path, monkeypatch):
    """A measurement doc is excluded from the zip but published by git; it is checked too."""
    root = _minimal_root(tmp_path)
    planted = 'source: https://docs.' + G + '/spreadsheets/d/abc/edit?usp=' + 'sharing&ou' + 'id=1'
    (root / 'docs/VOLUME_RESULTS.md').write_text(planted + '\n')
    assert root / 'docs/VOLUME_RESULTS.md' not in package_source.selected_files()
    _point_packager_at(monkeypatch, root)
    with pytest.raises(SystemExit) as error:
        package_source.main()
    assert 'docs/VOLUME_RESULTS.md' in str(error.value)
    assert planted not in str(error.value)
    assert not (root / 'public/invoice-studio-source.zip').exists(), 'the archive must not be written on a hit'


def test_whole_tree_guard_uses_git_listing_and_skips_ignored_and_binary_files(tmp_path, monkeypatch):
    import shutil
    import subprocess
    if shutil.which('git') is None:
        pytest.skip('git is not installed here (the runtime image has none); the walk fallback is tested below')
    root = _minimal_root(tmp_path)
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    (root / '.gitignore').write_text('ignored/\n')
    (root / 'ignored').mkdir()
    (root / 'ignored/notes.md').write_text('https://drive.' + G + '/file/d/abc/view\n')
    (root / 'public/picture.png').write_bytes(b'\x89PNG\x00' + ('https://drive.' + G + '/file/d/abc/view').encode())
    (root / 'untracked_but_committable.md').write_text('clean\n')
    scanned = {p.relative_to(root).as_posix() for p in package_source.repository_text_files(root)}
    assert 'untracked_but_committable.md' in scanned
    assert 'ignored/notes.md' not in scanned
    assert 'public/picture.png' not in scanned
    package_source.validate_repository(root)  # ignored and binary hits do not fail
    (root / 'untracked_but_committable.md').write_text('https://drive.' + G + '/file/d/abc/view\n')
    with pytest.raises(SystemExit, match='untracked_but_committable.md'):
        package_source.validate_repository(root)


def test_whole_tree_guard_walks_the_tree_outside_a_git_checkout(tmp_path):
    """An unzipped package or a test root has no .git; every regular text file is scanned."""
    root = _minimal_root(tmp_path)
    hit = 'https://drive.' + G + '/file/d/abc/view'
    (root / 'data').mkdir(); (root / 'data/private.md').write_text(hit + '\n')
    (root / 'public/picture.png').write_bytes(b'\x89PNG\x00' + hit.encode())
    scanned = {p.relative_to(root).as_posix() for p in package_source.repository_text_files(root)}
    assert 'docs/VOLUME_RESULTS.md' in scanned and 'README.md' in scanned
    assert 'data/private.md' not in scanned and 'public/picture.png' not in scanned
    package_source.validate_repository(root)
    (root / 'docs/VOLUME_RESULTS.md').write_text(hit + '\n')
    with pytest.raises(SystemExit) as error:
        package_source.validate_repository(root)
    assert 'docs/VOLUME_RESULTS.md' in str(error.value) and hit not in str(error.value)


def test_check_only_entry_fails_closed_and_names_the_file(tmp_path, capsys):
    root = _minimal_root(tmp_path)
    assert package_source.check_only(root) == 0
    assert 'no listed pattern found' in capsys.readouterr().out
    hit = 'https://drive.' + G + '/file/d/abc/view'
    (root / 'docs/VOLUME_RESULTS.md').write_text(hit + '\n')
    with pytest.raises(SystemExit) as error:
        package_source.check_only(root)
    assert 'docs/VOLUME_RESULTS.md' in str(error.value) and hit not in str(error.value)


def test_ci_workflow_and_pre_push_hook_run_the_check_only_entry():
    root = package_source.ROOT
    # Committed under workflows.pending/ until the repository owner moves it (the
    # automation token cannot create workflows); either path must pass.
    candidates = [root / '.github/workflows/privacy-guard.yml',
                  root / '.github/workflows.pending/privacy-guard.yml']
    present = [path for path in candidates if path.is_file()]
    assert present, 'privacy-guard.yml missing from both .github/workflows/ and .github/workflows.pending/'
    workflow = present[0].read_text()
    hook = root / '.githooks/pre-push'
    assert 'scripts/package_source.py --check-only' in workflow
    assert 'pull_request' in workflow and 'push' in workflow
    assert 'scripts/package_source.py --pre-push' in hook.read_text()
    assert hook.stat().st_mode & 0o111, 'pre-push must be executable'
    if shutil.which('git') is not None and (root / '.git').exists():
        # git skips a hook that is not executable, silently; the index mode is what a clone gets.
        listing = subprocess.run(['git', '-C', str(root), 'ls-files', '-s', '.githooks/pre-push'],
                                 capture_output=True, text=True, check=True).stdout
        assert listing.startswith('100755 '), listing


def test_both_launchers_install_the_pre_push_hook_in_clones_only():
    """Tripwire only: the acceptance evidence is a fresh-clone push refusal (docs/RELEASE_VALIDATION.md)."""
    root = package_source.ROOT
    for name in ['start.sh', 'Start-InvoiceStudio.ps1']:
        text = (root / name).read_text()
        assert 'core.hooksPath .githooks' in text, name
        assert '.git' in text and 'core.hooksPath' in text.split('docker')[0], f'{name}: hook install must precede the Docker checks'
    assert '-d .git' in (root / 'start.sh').read_text()
    assert "Join-Path $PSScriptRoot '.git'" in (root / 'Start-InvoiceStudio.ps1').read_text()


def test_whole_tree_guard_on_this_repository_is_clean():
    package_source.validate_repository(package_source.ROOT)


START_SCRIPTS = ['start.sh', 'Start-InvoiceStudio.command', 'Start-InvoiceStudio.ps1']


def test_start_scripts_ship_with_the_package_and_keep_their_mode(tmp_path, monkeypatch):
    """README and the setup guides tell the operator to run these from the unzipped folder."""
    root = _minimal_root(tmp_path)
    for name in ['start.sh', 'Start-InvoiceStudio.command']:
        (root / name).chmod(0o755)
    _point_packager_at(monkeypatch, root)
    package_source.main()
    from zipfile import ZipFile
    with ZipFile(root / 'public/invoice-studio-source.zip') as archive:
        modes = {info.filename: (info.external_attr >> 16) & 0o777 for info in archive.infolist()}
    for name in START_SCRIPTS:
        assert f'invoice-studio/{name}' in modes
    assert modes['invoice-studio/start.sh'] & 0o111
    assert modes['invoice-studio/Start-InvoiceStudio.command'] & 0o111


def test_decoded_package_built_from_this_repository_is_clean(tmp_path, monkeypatch):
    """Build the real package into a temp location, decode it, and grep the result.

    A tree grep cannot see inside base64; this is the form of the privacy check that
    cannot be fooled by the encoding step.
    """
    monkeypatch.setattr(package_source, 'OUTPUT', tmp_path / 'invoice-studio-source.zip')
    monkeypatch.setattr(package_source, 'PACKAGE_JSON', tmp_path / 'source-package.json')
    package_source.main()
    entries = _decoded_entries(tmp_path / 'source-package.json')
    docs = sorted(n for n in entries if n.startswith('invoice-studio/docs/'))
    assert docs == sorted(f'invoice-studio/docs/{n}' for n in SHIPPED_DOCS)
    for name, content in entries.items():
        text = content.decode('utf-8', errors='replace')
        for pattern in package_source.PRIVATE_CONTENT_PATTERNS:
            assert not pattern.search(text), f'{pattern.pattern!r} matched inside {name}'


# --- Push-range guard: the hook must refuse what the push carries, not what the tree shows.

def _git_env():
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid',
               GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.invalid',
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    env.pop('GIT_DIR', None)
    return env


def _git(cwd, *args, check=True, stdin=None):
    return subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True,
                          check=check, env=_git_env(), input=stdin)


def _clone_with_bare_origin(tmp_path):
    """A clone of a bare origin, carrying this repository's checker and hook plus one clean commit."""
    if shutil.which('git') is None:
        pytest.skip('git is not installed here (the runtime image has none)')
    origin = tmp_path / 'origin.git'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(origin)], check=True, env=_git_env())
    clone = tmp_path / 'clone'
    _git(tmp_path, 'clone', '-q', str(origin), str(clone))
    (clone / 'scripts').mkdir()
    (clone / '.githooks').mkdir()
    real = package_source.ROOT
    (clone / 'scripts/package_source.py').write_bytes((real / 'scripts/package_source.py').read_bytes())
    (clone / '.githooks/pre-push').write_bytes((real / '.githooks/pre-push').read_bytes())
    (clone / '.githooks/pre-push').chmod(0o755)
    (clone / 'README.md').write_text('clean\n')
    _git(clone, 'add', '-A')
    _git(clone, 'commit', '-q', '-m', 'clean baseline')
    _git(clone, 'push', '-q', '-u', 'origin', 'main')
    return origin, clone


def _marker():
    # A home-directory path, assembled so this file carries none of the forms itself.
    return 'log: ' + '/home/' + 'example-user/' + 'invoices/batch.csv\n'


def _plant_and_commit(clone, name='notes.txt'):
    (clone / name).write_text(_marker())
    _git(clone, 'add', name)
    _git(clone, 'commit', '-q', '-m', 'add ' + name)


def test_arm_a_hook_refuses_a_marker_in_the_pushed_tip(tmp_path):
    origin, clone = _clone_with_bare_origin(tmp_path)
    _git(clone, 'config', 'core.hooksPath', '.githooks')
    _plant_and_commit(clone)
    result = _git(clone, 'push', 'origin', 'main', check=False)
    assert result.returncode != 0, result.stdout + result.stderr
    assert 'notes.txt' in result.stderr
    assert 'example-user' not in result.stderr, 'the error must name the file, never the value'
    remote_tip = _git(origin, 'rev-parse', 'main').stdout.strip()
    assert remote_tip == _git(clone, 'rev-parse', 'HEAD~1').stdout.strip(), 'origin must still be at the clean baseline'


def test_arm_a2_hook_refuses_a_marker_buried_under_a_clean_commit(tmp_path):
    """Tree clean, tree checker clean, push still refused: the range carries the marker."""
    origin, clone = _clone_with_bare_origin(tmp_path)
    _git(clone, 'config', 'core.hooksPath', '.githooks')
    _plant_and_commit(clone)
    _git(clone, 'rm', '-q', 'notes.txt')
    _git(clone, 'commit', '-q', '-m', 'remove notes again')
    assert not (clone / 'notes.txt').exists()
    package_source.validate_repository(clone)  # the working-tree guard sees nothing: that is the hole
    result = _git(clone, 'push', 'origin', 'main', check=False)
    assert result.returncode != 0, 'a marker deleted from the tip is still inside the pushed range'
    assert 'notes.txt' in result.stderr and 'example-user' not in result.stderr
    assert _git(origin, 'rev-parse', 'main').stdout.strip() == _git(clone, 'rev-parse', 'HEAD~2').stdout.strip()


def test_arm_b_fresh_clone_with_nothing_run_is_not_guarded(tmp_path):
    """Documented limit: git installs no hook on clone, so nothing refuses until core.hooksPath is set."""
    origin, clone = _clone_with_bare_origin(tmp_path)
    assert _git(clone, 'config', '--get', 'core.hooksPath', check=False).stdout.strip() == ''
    _plant_and_commit(clone)
    result = _git(clone, 'push', 'origin', 'main', check=False)
    assert result.returncode == 0, result.stderr
    assert _git(origin, 'rev-parse', 'main').stdout.strip() == _git(clone, 'rev-parse', 'HEAD').stdout.strip()


def test_arm_c_hook_is_executable_in_the_index():
    """git silently skips a hook without the exec bit; the index mode is what every clone receives."""
    root = package_source.ROOT
    if shutil.which('git') is None or not (root / '.git').exists():
        pytest.skip('needs git and a checkout of this repository')
    listing = _git(root, 'ls-files', '-s', '.githooks/pre-push').stdout
    assert listing.startswith('100755 '), listing


def test_push_range_scan_covers_a_file_added_then_deleted_and_a_new_branch(tmp_path):
    origin, clone = _clone_with_bare_origin(tmp_path)
    baseline = _git(clone, 'rev-parse', 'HEAD').stdout.strip()
    _plant_and_commit(clone)
    _git(clone, 'rm', '-q', 'notes.txt')
    _git(clone, 'commit', '-q', '-m', 'remove notes again')
    tip = _git(clone, 'rev-parse', 'HEAD').stdout.strip()
    commits = package_source.commits_in_push(clone, tip, baseline)
    assert len(commits) == 2
    blobs = package_source.blobs_introduced(clone, commits)
    assert [path for _sha, path, _commit in blobs] == ['notes.txt']
    assert package_source.scan_blobs(clone, blobs) and 'notes.txt' in package_source.scan_blobs(clone, blobs)[0]
    # New branch (remote sha all zeros): only what origin lacks is scanned, and a delete line is skipped.
    zeros = '0' * 40
    assert package_source.commits_in_push(clone, tip, zeros) == commits
    with pytest.raises(SystemExit) as error:
        package_source.validate_push(clone, [f'refs/heads/feature {tip} refs/heads/feature {zeros}'])
    assert 'notes.txt' in str(error.value) and 'example-user' not in str(error.value)
    assert package_source.validate_push(clone, [f'(delete) {zeros} refs/heads/feature {tip}']) == (0, 0)
    assert package_source.validate_push(clone, [f'refs/heads/main {baseline} refs/heads/main {baseline}']) == (0, 0)


def test_push_range_scan_refuses_on_any_git_error(tmp_path):
    origin, clone = _clone_with_bare_origin(tmp_path)
    tip = _git(clone, 'rev-parse', 'HEAD').stdout.strip()
    with pytest.raises(SystemExit) as error:
        package_source.validate_push(clone, [f'refs/heads/main {tip} refs/heads/main {"f" * 40}'])
    assert 'refused' in str(error.value)
