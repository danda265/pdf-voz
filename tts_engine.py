from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable, List

import edge_tts

from utils import split_text, temp_audio_name

DEFAULT_VOICE = 'pt-BR-FranciscaNeural'
VOICES = [
    'pt-BR-FranciscaNeural',
    'pt-BR-AntonioNeural',
    'pt-BR-BrendaNeural',
    'pt-BR-DonatoNeural',
    'pt-BR-ElzaNeural',
]


class TTSEngine:
    def __init__(self, temp_dir: str | Path):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def format_rate(value: int) -> str:
        value = max(-50, min(50, int(value)))
        sign = '+' if value >= 0 else ''
        return f'{sign}{value}%'

    @staticmethod
    def format_volume(value: int) -> str:
        value = max(0, min(100, int(value)))
        edge_value = value - 100
        sign = '+' if edge_value >= 0 else ''
        return f'{sign}{edge_value}%'

    def split(self, text: str) -> List[str]:
        return split_text(text)

    def synthesize_chunk(self, text: str, index: int, voice: str, rate: int, volume: int,
                          prefix: str = '') -> Path:
        name = f'{prefix or "leitura_bloco_"}{index:05d}.mp3'
        output = self.temp_dir / name
        asyncio.run(self._save_chunk(text, output, voice, rate, volume))
        return output

    async def _save_chunk(self, text: str, output: Path, voice: str, rate: int, volume: int) -> None:
        communicate = edge_tts.Communicate(
            text,
            voice=voice,
            rate=self.format_rate(rate),
            volume=self.format_volume(volume),
        )
        await communicate.save(str(output))

    def export_mp3(self, chunks: Iterable[str], output_path: str | Path, voice: str, rate: int, volume: int) -> None:
        asyncio.run(self._export_mp3(chunks, Path(output_path), voice, rate, volume))

    async def _export_mp3(self, chunks: Iterable[str], output_path: Path, voice: str, rate: int, volume: int) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open('wb') as file:
            for chunk in chunks:
                communicate = edge_tts.Communicate(
                    chunk,
                    voice=voice,
                    rate=self.format_rate(rate),
                    volume=self.format_volume(volume),
                )
                async for message in communicate.stream():
                    if message['type'] == 'audio':
                        file.write(message['data'])
