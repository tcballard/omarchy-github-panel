"""Real Git merge fixtures with fake GitHub transport and isolated local remotes."""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import conflict_workspace as cw
from github_client import GhError


class Client:
    account = 'alice'
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.published = None
    def api(self, endpoint):
        if endpoint == 'user': return {'login': self.account, 'id': 123}
        if '/pulls/' in endpoint:
            s = self.snapshot
            return {'state': 'open', 'merged': False,
                    'head': {'sha': s['headSha'], 'ref': s['headRef'], 'repo': {'full_name': s['headRepo']}},
                    'base': {'sha': s['baseSha'], 'ref': s['baseRef'], 'repo': {'full_name': s['baseRepo']}}}
        if '/git/ref/heads/' in endpoint: return {'object': {'sha': self.published}}
        raise AssertionError(endpoint)


class ConflictTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'XDG_STATE_HOME': self.temp.name}); self.env.start(); self.addCleanup(self.env.stop)
        self.source = Path(self.temp.name) / 'fixture.git'
        self.git = cw.Git(self.source)
        self.git.run('init', '--bare', '--template=', str(self.source))
        self.git.env.update(GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.test',
                            GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.test')
        self.folder = cw.location('alice', 'a/b', 7)
        self.item = cw.conflict_target('a/b', 7)

    def commit(self, files, parents=()):
        entries = []
        for filename, value in sorted(files.items()):
            mode, data = value if isinstance(value, tuple) else ('100644', value)
            sha = self.git.run('hash-object', '-w', '--stdin', input=data)[0].decode().strip()
            entries.append(f'{mode} blob {sha}\t{filename}\0')
        tree = self.git.run('mktree', '-z', input=''.join(entries).encode())[0].decode().strip()
        args = ['commit-tree', tree]
        for parent in parents: args.extend(['-p', parent])
        return self.git.run(*args, input=b'fixture commit')[0].decode().strip()

    def fixture(self, ancestor=None, source=None, base=None):
        ancestor = ancestor if ancestor is not None else {'file.txt': b'one\ncommon\nend\n'}
        source = source if source is not None else {'file.txt': b'one\nsource\nend\n', 'source-only': b'keep me\n'}
        base = base if base is not None else {'file.txt': b'one\ntarget\nend\n', 'base-only': b'keep me too\n'}
        common = self.commit(ancestor); head = self.commit(source, [common]); target = self.commit(base, [common])
        self.snapshot = dict(headSha=head, baseSha=target, headRepo='fork/b', baseRepo='a/b', headRef='topic', baseRef='main')
        self.client = Client(self.snapshot)
        self.git.run('update-ref', 'refs/heads/topic', head)
        def fetch(git, snapshot, number):
            shutil.copytree(self.source, git.folder)
        with cw.locked(self.folder), patch.object(cw, 'fetch', fetch):
            return cw.prepare(self.client, 'a/b', 7, self.folder, self.snapshot)

    def saved(self): return cw.read_session(self.folder)

    def save(self, session=None, mode='edit', body='one\ncombined\nend\n', filename='file.txt', file_mode='100644'):
        session = session or self.saved()
        return cw.perform(self.client, dict(confirmed=True, action='conflicts-save', item=self.item,
            expected={**cw.expectation(session), 'path': filename}, values={'mode': mode, 'body': body, 'fileMode': file_mode}))

    def test_real_merge_preserves_both_nonconflicting_changes_and_edited_file(self):
        session = self.fixture()
        self.assertEqual(set(session['files']), {'file.txt'})
        self.assertEqual(session['unsupported'], [])
        view = cw.detail(self.client, cw.conflict_target('a/b', 7, 'file.txt'))
        self.assertIn('<<<<<<<', view['actions'][0]['fields'][1]['value'])
        self.save()
        git = cw.Git(self.folder / 'objects.git'); tree = cw.resolution_tree(git, self.saved())
        for name, expected in [('source-only', b'keep me\n'), ('base-only', b'keep me too\n'), ('file.txt', b'one\ncombined\nend\n')]:
            self.assertEqual(git.run('show', tree + ':' + name)[0], expected)

    def test_unresolved_and_markers_block_publication(self):
        session = self.fixture(); git = cw.Git(self.folder / 'objects.git')
        with self.assertRaises(GhError): cw.resolution_tree(git, session)
        with self.assertRaisesRegex(GhError, 'markers'): self.save(body='<<<<<<< source\nconflict\n=======\nother\n>>>>>>> target\n')
        self.assertEqual(self.saved()['resolutions'], {})

    def test_repository_marker_size_cannot_bypass_unresolved_check(self):
        attributes = b'* conflict-marker-size=3\n'
        self.fixture(ancestor={'.gitattributes': attributes, 'file.txt': b'base\n'},
                     source={'.gitattributes': attributes, 'file.txt': b'source\n'},
                     base={'.gitattributes': attributes, 'file.txt': b'target\n'})
        git = cw.Git(self.folder / 'objects.git')
        body = cw.merged_text(git, self.saved(), 'file.txt')
        self.assertIn('<<<<<<<', body)
        with self.assertRaisesRegex(GhError, 'markers'): self.save(body=body)

    def test_modify_delete_and_add_add_and_empty_resolution(self):
        session = self.fixture(ancestor={'file.txt': b'base'}, source={}, base={'file.txt': b'edited'})
        self.assertEqual(session['unsupported'], [])
        self.save(mode='source')
        git = cw.Git(self.folder / 'objects.git'); tree = cw.resolution_tree(git, self.saved())
        self.assertEqual(git.run('ls-tree', tree)[0], b'')
        session = self.fixture(ancestor={}, source={'file.txt': b'source'}, base={'file.txt': b'target'})
        self.assertEqual(session['unsupported'], [])
        self.save(body='')
        git = cw.Git(self.folder / 'objects.git'); tree = cw.resolution_tree(git, self.saved())
        self.assertEqual(git.run('show', tree + ':file.txt')[0], b'')

    def test_binary_side_choice_preserves_bytes_and_executable_mode(self):
        session = self.fixture(ancestor={'file.txt': ('100755', b'\0base')}, source={'file.txt': ('100755', b'\0source')}, base={'file.txt': ('100755', b'\0target')})
        self.assertEqual(session['unsupported'], [])
        detail = cw.detail(self.client, cw.conflict_target('a/b', 7, 'file.txt'))
        self.assertEqual(detail['actions'][0]['fields'][0]['options'], ['source', 'target'])
        self.save(mode='target')
        git = cw.Git(self.folder / 'objects.git'); tree = cw.resolution_tree(git, self.saved())
        self.assertEqual(git.run('show', tree + ':file.txt')[0], b'\0target')
        self.assertTrue(git.run('ls-tree', tree)[0].startswith(b'100755'))

    def test_structural_rename_and_symlink_conflicts_block_all_publication(self):
        for source, base in [({'source.txt': b'base'}, {'target.txt': b'base'}),
                             ({'file.txt': ('120000', b'one')}, {'file.txt': b'two'})]:
            with self.subTest(source=source):
                session = self.fixture(ancestor={'file.txt': b'base'}, source=source, base=base)
                self.assertTrue(session['unsupported'])
                with self.assertRaises(GhError): cw.resolution_tree(cw.Git(self.folder / 'objects.git'), session)

    def test_stale_head_base_ref_or_local_revision_blocks_save(self):
        session = self.fixture()
        for key in ('headSha', 'baseSha', 'headRef', 'headRepo'):
            original = self.client.snapshot[key]
            self.client.snapshot[key] = 'f' * 40 if key.endswith('Sha') else 'other/name'
            with self.subTest(key=key), self.assertRaisesRegex(GhError, 'branch changed'):
                self.save(session)
            self.client.snapshot[key] = original
        self.save(session)
        with self.assertRaisesRegex(GhError, 'resolution changed'): self.save(session)

    def test_unconfirmed_action_and_account_isolation(self):
        self.fixture()
        with self.assertRaises(GhError): cw.perform(self.client, {'action': 'conflicts-discard', 'item': self.item})
        with self.assertRaises(GhError): cw.perform(self.client, {'action': 'conflicts-publish', 'item': self.item, 'confirmed': True})
        with self.assertRaises(GhError): cw.read_session(cw.location('bob', 'a/b', 7))
        self.assertEqual(self.folder.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.folder / 'session.json').stat().st_mode & 0o777, 0o600)

    def test_discard_removes_objects_and_saved_edits(self):
        session = self.fixture(); self.save()
        cw.perform(self.client, dict(confirmed=True, action='conflicts-discard', item=self.item, expected=cw.expectation(self.saved())))
        self.assertFalse((self.folder / 'session.json').exists())
        self.assertFalse((self.folder / 'objects.git').exists())

    def publish_locally(self, race=False):
        session = self.saved(); original_run = cw.Git.run; pushed = []
        def run(git, *args, **kwargs):
            if args[0] == 'push':
                pushed.append(args)
                if race:
                    advanced = self.commit({'file.txt': b'concurrent'}, [session['headSha']])
                    self.git.run('update-ref', 'refs/heads/topic', advanced)
                command = list(args); command[-2] = str(self.source)
                value = original_run(git, '-c', 'protocol.file.allow=always', *command, **kwargs)
                self.client.published = args[-1].split(':')[0]
                return value
            return original_run(git, *args, **kwargs)
        with patch.object(cw.Git, 'run', run):
            result = cw.perform(self.client, dict(confirmed=True, action='conflicts-publish', item=self.item,
                expected=cw.expectation(session), values={'message': 'Resolve conflicts'}))
        return result, pushed

    def test_real_publish_makes_two_parent_commit_and_keeps_pr_open(self):
        session = self.fixture(); self.save()
        result, pushed = self.publish_locally()
        self.assertEqual(result['target']['kind'], 'pull-request')
        commit = self.git.run('rev-parse', 'refs/heads/topic')[0].decode().strip()
        parents = self.git.run('show', '-s', '--format=%P', commit)[0].decode().strip().split()
        self.assertEqual(parents, [session['headSha'], session['baseSha']])
        self.assertIn('--force-with-lease=refs/heads/topic:' + session['headSha'], pushed[0])
        self.assertFalse((self.folder / 'session.json').exists())

    def test_real_push_lease_rejects_concurrent_source_update_and_retains_draft(self):
        self.fixture(); self.save()
        with self.assertRaises(GhError): self.publish_locally(race=True)
        self.assertTrue((self.folder / 'session.json').exists())
        self.assertEqual(self.git.run('show', 'refs/heads/topic:file.txt')[0], b'concurrent')

    def test_disk_limit_terminates_work(self):
        self.fixture()
        with patch.object(cw, 'DISK_LIMIT', 1), self.assertRaisesRegex(GhError, '256 MiB'):
            cw.Git(self.folder / 'objects.git').run('status')

    def test_guard_and_git_environment_disable_external_repository_configuration(self):
        with patch.dict(os.environ, {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.hooksPath', 'GIT_CONFIG_VALUE_0': '/bad'}):
            git = cw.Git(self.source)
        self.assertNotIn('GIT_CONFIG_COUNT', git.env)
        self.assertEqual(git.env['GIT_CONFIG_GLOBAL'], os.devnull)
        with cw.locked(self.folder), self.assertRaisesRegex(GhError, 'Another conflict'):
            with cw.locked(self.folder): pass
