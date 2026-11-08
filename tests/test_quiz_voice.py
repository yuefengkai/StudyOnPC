"""No GUI, network, audio playback or paid synthesis in these tests."""
import base64
from concurrent.futures import Future, ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studyonpc import tts
from studyonpc.quiz_voice import GroupPreloader, QuizVoice, ManagedPlayer, question_text

CONFIG = dict(enabled=True, api_key='test-only-not-a-real-key', speaker='voice',
              resource_id='resource', sample_rate=24000)
AUDIO = b'ID3' + b'fake-audio' * 100


class Response:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self):
        return ('data: '+json.dumps({'code': 0, 'data': base64.b64encode(AUDIO).decode()})+'\n').encode()


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.cache = patch.object(tts, 'cache_dir', return_value=self.directory)
        self.cache.start(); self.addCleanup(self.cache.stop)

    def test_second_and_concurrent_requests_use_one_network_call(self):
        with patch.object(tts.request, 'urlopen', return_value=Response()) as net:
            with ThreadPoolExecutor(4) as pool:
                paths = list(pool.map(lambda _: tts.synthesize('prompt', CONFIG), range(8)))
            self.assertEqual(net.call_count, 1)
            self.assertEqual(len(set(paths)), 1)
            self.assertEqual(paths[0].read_bytes(), AUDIO)
        with patch.object(tts.request, 'urlopen', side_effect=AssertionError('offline')):
            self.assertEqual(tts.synthesize('prompt', CONFIG), paths[0])

    def test_cache_identity_parameters_not_secrets(self):
        key = tts._cache_key('prompt', CONFIG)
        self.assertEqual(key, tts._cache_key('prompt', dict(CONFIG, api_key='rotated')))
        self.assertNotIn(CONFIG['api_key'], key)
        for name, value in dict(speaker='other', resource_id='other', sample_rate=16000,
                                encoding='wav', api_url='https://other.example/',
                                provider='other', speech_rate=10, loudness_rate=10).items():
            self.assertNotEqual(key, tts._cache_key('prompt', dict(CONFIG, **{name: value})),name)
        self.assertNotEqual(key, tts._cache_key('new prompt', CONFIG))

    def test_atomic_publication_then_failure_cleanup_and_retry(self):
        real_replace = tts.os.replace
        def replace(src, dst):
            self.assertEqual(Path(src).read_bytes(), AUDIO)
            self.assertFalse(Path(dst).exists())
            real_replace(src, dst)
        with patch.object(tts.request, 'urlopen', return_value=Response()):
            with patch.object(tts.os, 'replace', side_effect=replace):
                path = tts.synthesize('one', CONFIG)
            self.assertEqual(path.read_bytes(), AUDIO)
            with patch.object(tts.os, 'replace', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError): tts.synthesize('two', CONFIG)
            self.assertFalse((self.directory / tts._cache_key('two', CONFIG)).exists())
            self.assertEqual(list(self.directory.glob('*.tmp')), [])
            self.assertEqual(tts.synthesize('two', CONFIG).read_bytes(), AUDIO)

    def test_network_failure_does_not_publish_partial_cache(self):
        with patch.object(tts.request, 'urlopen', side_effect=OSError('offline')):
            self.assertIsNone(tts.synthesize('fail', CONFIG))
        self.assertEqual(list(self.directory.iterdir()), [])
        with patch.object(tts.request, 'urlopen', return_value=Response()):
            self.assertIsNotNone(tts.synthesize('fail', CONFIG))

    def test_server_error_rejects_partial_audio(self):
        raw=Response().read()+b'data: {"code": 45000000}\n'
        self.assertIsNone(tts._parse_sse_audio(raw))


class FakeLoader:
    def __init__(self): self.futures={}; self.prepared=[]; self.closed=False;self.requests=[]
    def prepare(self,texts):
        self.prepared=list(texts)
        for t in texts:self.request(t)
    def request(self,text,priority=False):
        self.requests.append((text,priority))
        return self.futures.setdefault(text,Future())
    def discard(self,text):pass
    def close(self):self.closed=True


class FakePlayer:
    def __init__(self):self.played=[];self.playing=False;self.stops=0
    def play(self,path):self.played.append(path);self.playing=True;return True
    def busy(self):return self.playing
    def stop(self):self.playing=False;self.stops+=1


class ControllerTests(unittest.TestCase):
    def make(self, questions=None):
        self.loader=FakeLoader();self.player=FakePlayer();self.now=0
        return QuizVoice(CONFIG,questions or [{'q':'one'},{'q':'two'}],
             preloader=self.loader,player=self.player,clock=lambda:self.now)

    def test_preload_never_plays_and_reads_only_prompt(self):
        q={'q':'question','a':'secret answer','explanation':'secret explanation','choices':['secret']}
        v=self.make([q]);self.assertEqual(self.loader.prepared,['question'])
        self.assertEqual(question_text(q),'question');self.assertEqual(self.player.played,[])
        self.loader.futures['question'].set_result(Path('one.mp3'))
        v.poll();self.assertEqual(self.player.played,[])
        v.show(0);v.poll();self.assertEqual(self.player.played,[Path('one.mp3')])

    def test_auto_hover_pending_and_playing_do_not_overlap(self):
        v=self.make();v.show(0)
        self.assertFalse(v.hover_enter());self.assertFalse(v.hover_enter())
        self.loader.futures['one'].set_result(Path('one.mp3'));v.poll()
        v.hover_leave();self.now=2;self.assertFalse(v.hover_enter());v.poll()
        self.assertEqual(self.player.played,[Path('one.mp3')])

    def test_leave_reenter_cooldown_and_same_region_events(self):
        v=self.make();v.show(0);self.loader.futures['one'].set_result(Path('one.mp3'));v.poll()
        self.player.playing=False
        self.assertTrue(v.hover_enter());v.poll();self.player.playing=False
        self.assertFalse(v.hover_enter())
        v.hover_leave();self.now=.5;self.assertFalse(v.hover_enter())
        v.hover_leave();self.now=2;self.assertTrue(v.hover_enter());v.poll()
        self.assertEqual(len(self.player.played),3)

    def test_switch_discards_old_async_result(self):
        v=self.make();v.show(0);token=v.token;v.show(1)
        self.assertGreater(v.token,token)
        self.loader.futures['one'].set_result(Path('old.mp3'));v.poll()
        self.assertEqual(self.player.played,[])
        self.loader.futures['two'].set_result(Path('current.mp3'));v.poll()
        self.assertEqual(self.player.played,[Path('current.mp3')])

    def test_answer_stop_and_close_do_not_play_late_result(self):
        for close in (False,True):
            v=self.make();v.show(0)
            v.close() if close else v.stop()
            self.loader.futures['one'].set_result(Path('late.mp3'));v.poll()
            self.assertEqual(self.player.played,[]);self.assertFalse(v.request_play())
            if close:self.assertTrue(self.loader.closed)

    def test_preload_error_is_nonblocking(self):
        v=self.make();v.show(0);self.loader.futures['one'].set_exception(OSError('offline'))
        self.assertIn('可继续答题',v.poll());self.assertEqual(self.player.played,[])

    def test_selected_group_sizes_only(self):
        for n in (3,5):
            v=self.make([{'q':str(i)} for i in range(n)])
            self.assertEqual(len(self.loader.prepared),n);v.close()


class WorkerTests(unittest.TestCase):
    def test_shared_future_and_cancel_unsent(self):
        entered=threading.Event();release=threading.Event();done=threading.Event();calls=[]
        def synth(text,cfg):
            calls.append(text);entered.set();release.wait(2);done.set();return Path('a.mp3')
        loader=GroupPreloader(CONFIG,synthesize=synth)
        first=loader.request('one');self.assertTrue(entered.wait(2))
        self.assertIs(loader.request('one',priority=True),first)
        second=loader.request('two');third=loader.request('three')
        loader.close();release.set();self.assertTrue(done.wait(2))
        self.assertTrue(second.cancelled());self.assertTrue(third.cancelled())
        self.assertEqual(first.result(2),Path('a.mp3'));self.assertEqual(calls,['one'])
        self.assertTrue(loader.request('four').cancelled())

    def test_current_priority_and_one_worker(self):
        entered=threading.Event();release=threading.Event();calls=[]
        def synth(text,cfg):
            calls.append(text)
            if text=='one':entered.set();release.wait(2)
            return Path(text+'.mp3')
        loader=GroupPreloader(CONFIG,synthesize=synth);self.addCleanup(loader.close)
        f1=loader.request('one');self.assertTrue(entered.wait(2))
        f2=loader.request('two');f3=loader.request('three');loader.request('three',priority=True)
        release.set();f1.result(2);f3.result(2);f2.result(2)
        self.assertEqual(calls,['one','three','two'])

    def test_discard_old_queued_prompt_and_show_does_not_block(self):
        entered=threading.Event();release=threading.Event();calls=[]
        def synth(text,cfg):
            calls.append(text)
            if text=='one':entered.set();release.wait(2)
            return Path(text+'.mp3')
        loader=GroupPreloader(CONFIG,synthesize=synth)
        self.addCleanup(loader.close);self.addCleanup(release.set)
        loader.request('one');self.assertTrue(entered.wait(2))
        old=loader.request('obsolete');new=loader.request('two')
        loader.discard('obsolete');self.assertTrue(old.cancelled())
        player=FakePlayer()
        voice=QuizVoice(CONFIG,[{'q':'one'},{'q':'two'}],preloader=loader,player=player)
        voice.show(0);self.assertEqual(voice.status,'语音准备中… 可继续答题')
        voice.show(1);self.assertEqual(player.played,[])
        release.set();new.result(2);voice.poll()
        self.assertEqual(calls,['one','two'])
        self.assertEqual(player.played,[Path('two.mp3')]);voice.close()

    def test_failure_can_retry(self):
        calls=[]
        def synth(text,cfg):
            calls.append(text);return None if len(calls)==1 else Path('ok.mp3')
        loader=GroupPreloader(CONFIG,synthesize=synth);self.addCleanup(loader.close)
        self.assertIsNone(loader.request('one').result(2))
        self.assertEqual(loader.request('one').result(2),Path('ok.mp3'))


class PlayerTests(unittest.TestCase):
    def test_windows_nonblocking_and_stop(self):
        player=ManagedPlayer();commands=[]
        def mci(cmd):commands.append(cmd);return 0,'playing'
        with patch('studyonpc.quiz_voice.os.name','nt'),patch.object(player,'_mci',side_effect=mci):
            # Mock Path.resolve to avoid platform-specific Path creation under os.name patch.
            with patch('studyonpc.quiz_voice.Path') as path:
                path.return_value.resolve.return_value='audio.mp3'
                self.assertTrue(player.play('audio.mp3'))
            self.assertTrue(player.busy());player.stop()
        self.assertFalse(any(' wait' in c for c in commands))
        self.assertTrue(any(c.startswith('close ') for c in commands))

if __name__=='__main__':unittest.main()
