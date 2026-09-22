"""Portable Qt Quick Test runner; PySide6 is a test dependency only."""
from pathlib import Path
import sys
from PySide6.QtQuickTest import QUICK_TEST_MAIN

root=Path(__file__).resolve().parent
sys.exit(QUICK_TEST_MAIN('github',['github','-import',str(root/'qml/imports'),'-input',str(root/'qml')]))
