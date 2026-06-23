from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

import pygame


class AudioPlayer:
    def __init__(self):
        pygame.mixer.init()
        self._paused = False
        self._stopped = False
        self._should_pause = False   # pausa pedida durante síntese
        self._volume = 1.0

    def set_volume(self, volume: int) -> None:
        self._volume = max(0.0, min(1.0, volume / 100))
        pygame.mixer.music.set_volume(self._volume)

    def play_file(self, path: Path, stop_checker: Optional[Callable[[], bool]] = None) -> None:
        self._stopped = False
        self._paused = False
        pygame.mixer.music.load(str(path))
        pygame.mixer.music.set_volume(self._volume)
        pygame.mixer.music.play()
        # se pause foi pedido durante a síntese, começa já pausado
        if self._should_pause:
            pygame.mixer.music.pause()
            self._paused = True
        while True:
            if self._stopped or (stop_checker and stop_checker()):
                pygame.mixer.music.stop()
                break
            if self._paused:
                # mantém o loop vivo enquanto pausado (get_busy() pode retornar False)
                time.sleep(0.05)
                continue
            if not pygame.mixer.music.get_busy():
                break
            time.sleep(0.05)

    def pause(self) -> None:
        self._should_pause = True
        if not self._paused:
            pygame.mixer.music.pause()
            self._paused = True

    def resume(self) -> None:
        self._should_pause = False
        if self._paused:
            pygame.mixer.music.unpause()
            self._paused = False

    def stop(self) -> None:
        self._stopped = True
        self._paused = False
        self._should_pause = False
        pygame.mixer.music.stop()
        try:
            pygame.mixer.music.unload()
        except pygame.error:
            pass

    def close(self) -> None:
        self.stop()
        pygame.mixer.quit()
