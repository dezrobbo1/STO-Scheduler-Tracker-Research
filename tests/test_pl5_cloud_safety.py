import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

def load_script():
    spec = importlib.util.spec_from_file_location('cloud_safety', ROOT / 'scripts/pl5-cloud-evidence.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class CloudSafetyTests(unittest.TestCase):
    def test_capacitor_never_logs_secret_plugin_arguments(self):
        config = json.loads((ROOT / 'field/capacitor.config.json').read_text())
        self.assertEqual(config.get('loggingBehavior'), 'none')

    def test_runner_redacts_native_bridge_credentials_and_passphrases(self):
        tool = load_script()
        raw = 'callback methodData: {"passphrase":"local-key"}\nconsole {"token":"device-key"}\nAuthorization: Bearer device-key\nphase passed\n'
        safe = tool.sanitize(raw, ['device-key', 'master-key'])
        self.assertNotIn('device-key', safe)
        self.assertNotIn('local-key', safe)
        self.assertIn('phase passed', safe)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'logcat.txt'
            path.write_text(raw)
            with self.assertRaises(ValueError):
                tool.scan(Path(temp), ['device-key'])
            path.write_text(safe)
            tool.scan(Path(temp), ['device-key'])

    def test_ios_screen_must_show_post_store_connection_form(self):
        tool = load_script()
        self.assertFalse(tool.ios_screen_ready(['STO field', 'Opening local store…']))
        self.assertFalse(tool.ios_screen_ready([]))
        ready = ['STO field', 'Connect this device', 'Server HTTPS URL', 'Project ID', 'Device token', 'Connect']
        self.assertTrue(tool.ios_screen_ready(ready))
        self.assertFalse(tool.ios_screen_ready(ready + ['Native encrypted storage unavailable']))

class AndroidEvidenceTests(unittest.TestCase):
    def fixture(self):
        import copy
        setup = dict(project_id='project', actor_a='actor-a', actor_b='actor-b', baseline_hash='base', baseline_version_id='version')
        execution = dict(operation_id='execution', actor_user_id='actor-a', activity_uid='activity', payload={'operation_id':'execution','activity_uid':'activity'}, local_final_state='queued')
        note = dict(id='note', actor_user_id='actor-a', activity_uid='activity', text='CI emulator offline note', local_final_state='queued')
        queued = dict(project_id='project', actor_user_id='actor-a', cursor=0, version_id='version', canonical_hash='base', execution=[execution], communication=[note], media=[])
        reopened = copy.deepcopy(queued)
        reconciled = copy.deepcopy(queued)
        reconciled.update(cursor=2, canonical_hash='final',version_id='new')
        e = dict(operation_id='execution',project_id='project',actor_user_id='actor-a',status='applied',canonical_hash='final',result_version_id='new',server_sequence=1)
        n = dict(id='note',project_id='project',actor_user_id='actor-a',kind='trial_message',text=note['text'],activity_uid='activity',server_sequence=2)
        reconciled['execution'][0].update(local_final_state='applied',error_code=None,receipt=e)
        reconciled['communication'][0].update(local_final_state='accepted',error_code=None,receipt=n)
        account_b = dict(project_id='project',actor_user_id='actor-b',cursor=2,canonical_hash='final',execution=[],communication=[],media=[])
        feed = dict(events=[e,n],next_cursor=2,has_more=False)
        return setup,queued,reopened,reconciled,account_b,feed

    def test_uuid_and_frozen_payload_survive_reopen_and_bind_server_feed(self):
        import copy
        tool=load_script()
        args=self.fixture()
        tool.verify_android(*args)
        for mutate in [lambda a:a[2]['execution'][0].update(operation_id='replacement'),lambda a:a[2]['execution'][0]['payload'].update(activity_uid='changed'),lambda a:a[5]['events'][0].update(operation_id='unrelated'),lambda a:a[4]['communication'].append(a[1]['communication'][0]),lambda a:a[3]['execution'][0].update(local_final_state='sending')]:
            changed=copy.deepcopy(args);mutate(changed)
            with self.assertRaises(ValueError):tool.verify_android(*changed)

class ArtifactRetirementTests(unittest.TestCase):
    def test_only_previous_cloud_android_artifacts_from_trial_branch_are_retired(self):
        spec=importlib.util.spec_from_file_location('retire',ROOT/'scripts/cleanup-pl5-cloud-artifacts.py')
        tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
        row={'id':11543100748,'name':'pl5-cloud-emulator','workflow_run':{'head_branch':tool.BRANCH,'head_sha':'prior'}}
        self.assertTrue(tool.eligible(row,'current'))
        self.assertFalse(tool.eligible({**row,'id':999999},'current'))
        self.assertFalse(tool.eligible(row,'prior'))
        self.assertFalse(tool.eligible({**row,'name':'pl5-device-return'},'current'))
        self.assertFalse(tool.eligible({**row,'workflow_run':{'head_branch':'main','head_sha':'prior'}},'current'))

class OfflineLinkHandshakeTests(unittest.TestCase):
    def test_server_restart_waits_for_native_offline_assertion(self):
        shell=(ROOT/'scripts/run-pl5-cloud-emulator.sh').read_text()
        java=(ROOT/'field/android/app/src/androidTest/java/au/com/sto/fieldtrial/CloudEmulatorFlowTest.java').read_text()
        self.assertIn('start_server_after_offline_hint',shell)
        self.assertIn('OFFLINE_HINT_CONFIRMED',shell)
        method=java.split('public void offlineDeepLinkRecovers()',1)[1]
        self.assertLess(method.index('assertNotEquals('),method.index('OFFLINE_HINT_CONFIRMED'))
        self.assertNotIn('sleep 8',shell)

class IosEncryptionConfigurationTests(unittest.TestCase):
    def test_ios_encrypted_store_has_stable_app_keychain_namespace(self):
        config=json.loads((ROOT/'field/capacitor.config.json').read_text())
        self.assertTrue(config['plugins']['CapacitorSQLite']['iosIsEncryption'])
        self.assertEqual(config['plugins']['CapacitorSQLite'].get('iosKeychainPrefix'),'au.com.sto.fieldtrial')
