# -*- coding: utf-8 -*-
"""StudyOnPC entry point. Usage:
  pythonw studyonpc.py --role=watchdog
  pythonw studyonpc.py --role=main
  python studyonpc.py --once --force
"""
from __future__ import annotations

from studyonpc.app import main

if __name__ == "__main__":
    main()
