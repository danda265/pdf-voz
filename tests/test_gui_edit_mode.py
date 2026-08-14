from __future__ import annotations

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from gui import MainWindow


def test_edit_mode_renders_first_page(qtbot, sample_pdf):
    window = MainWindow()
    qtbot.addWidget(window)
    window.current_file = str(sample_pdf)
    window.edit_mode_button.setEnabled(True)
    window.edit_mode_button.setChecked(True)
    assert window.edit_session is not None
    assert window.stack.currentIndex() == 1
    assert len(window.edit_scroll.canvas.spans) > 0
    window.close()
