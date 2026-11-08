"""Optional real Tk wiring smoke tests, run with xvfb-run on Linux. No speech/network."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
try:
    from studyonpc.quiz_ui import QuizSetRunner
except ModuleNotFoundError as exc:
    if exc.name != "tkinter":
        raise
    QuizSetRunner = None
from studyonpc.rules import RulesConfig

class FakeVoice:
    def __init__(self,config,questions):self.questions=questions;self.closed=False;self.shown=[];self.requests=0;self.stopped=0;self.enters=0
    def show(self,index):self.shown.append(index)
    def poll(self):return '语音准备中… 可继续答题'
    def request_play(self):self.requests+=1
    def hover_enter(self):self.enters+=1
    def hover_leave(self):pass
    def stop(self):self.stopped+=1
    def close(self):self.closed=True

@unittest.skipUnless(QuizSetRunner is not None and (os.environ.get('DISPLAY') or os.name=='nt'),
                     'Tk smoke requires tkinter and display')
class TkVoiceTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.questions=[{'id':i,'type':'single','subject':'数学','q':f'{i}+10=?','a':str(i+10),'choices':[str(i+10),'20','30','40']} for i in range(3)]
        self.patcher=patch('studyonpc.quiz_ui.QuizVoice',FakeVoice);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.runner=QuizSetRunner(self.root,self.questions,{},RulesConfig(answer_delay_seconds=0),'test',lambda *args:None,lambda:None,tts_config={'enabled':True,'api_key':'fake','speaker':'voice'})
        self.addCleanup(self.runner._close_voice)

    def test_group_prepared_autoshow_manual_hover_and_destroy(self):
        self.runner.start();self.root.update()
        voice=self.runner._voice
        self.assertEqual(len(voice.questions),3);self.assertEqual(voice.shown,[0])
        self.assertFalse(self.runner._q_host.bind('<Motion>'))
        self.assertTrue(self.runner._q_host.bind('<Enter>'))
        self.runner._q_host.event_generate('<Enter>');self.root.update()
        self.assertGreaterEqual(voice.enters,1)
        self.runner._on_speak();self.assertEqual(voice.requests,1)
        self.runner.idx=1;self.runner._show_current();self.root.update()
        self.assertEqual(voice.shown,[0,1])
        self.runner._win.destroy();self.root.update();self.assertTrue(voice.closed)

    def test_answer_stops_and_result_closes_voice(self):
        self.runner.start();self.root.update();voice=self.runner._voice
        with patch('studyonpc.quiz_ui.log_answer'):
            self.runner._handle_answer(self.runner._active_q,'wrong',self.runner._win)
        self.assertEqual(voice.stopped,1)
        self.runner._finish_set();self.assertTrue(voice.closed)

    def test_unconfigured_tts_does_not_block_or_popup(self):
        self.runner.tts_config={};self.runner.start();self.root.update()
        self.assertIsNone(self.runner._voice)
        self.runner._on_speak()
        self.assertIn('未配置',self.runner._voice_label.cget('text'))
