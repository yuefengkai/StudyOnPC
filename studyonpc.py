# -*- coding: utf-8 -*-
"""StudyOnPC entry point.

Normal (no black console):
  pythonw studyonpc.py --role=watchdog
  double-click start.bat / start.vbs

Debug console:
  start-console.bat
  python studyonpc.py --console --role=main --force
"""
from __future__ import annotations

from studyonpc.app import main

if __name__ == "__main__":
    main()
