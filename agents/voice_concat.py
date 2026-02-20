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

def concat_mp3(mp3_paths: List[str], output_path: str) -> None:
    """
    複数のMP3ファイルをffmpegで結合してoutput_pathに保存する。
    mp3_paths: 結合するMP3ファイルのリスト
    output_path: 出力先ファイルパス
    """
    if not mp3_paths:
        raise ValueError("mp3_paths is empty")
    # ffmpeg concat demuxer用の一時リストファイルを作成
    list_path = output_path + ".txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for mp3 in mp3_paths:
            f.write(f"file '{os.path.abspath(mp3)}'\n")
    try:
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output_path
        ], check=True)
    finally:
        os.remove(list_path)
