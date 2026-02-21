def concat_wav(wav_paths: list[str], output_path: str) -> None:
    """
    複数のWAVファイルをffmpegで結合してoutput_pathに保存する。
    wav_paths: 結合するWAVファイルのリスト
    output_path: 出力先ファイルパス
    """
    if not wav_paths:
        raise ValueError("wav_paths is empty")
    list_path = output_path + ".txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for wav in wav_paths:
            f.write(f"file '{os.path.abspath(wav)}'\n")
    try:
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output_path
        ], check=True)
    finally:
        os.remove(list_path)
import subprocess
import os
from typing import List

