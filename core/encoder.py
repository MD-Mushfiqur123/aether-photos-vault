"""
Aether Photos - Binary Video Encoder Engine
Converts arbitrary files (photos, archives, datasets) into a 1080p binary video stream.
Uses 8x8 macro-blocks with center-point sampling and frame headers for YouTube resilience.
"""

import os
import sys
import struct
import hashlib
import zipfile
import io
import subprocess
import numpy as np
from PIL import Image

try:
    import imageio_ffmpeg
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_EXE = "ffmpeg"

WIDTH = 1920
HEIGHT = 1080
BLOCK_SIZE = 8
MARGIN_BLOCKS = 2  # 2 blocks = 16px safety margin on all 4 sides against video player border cropping

COLS = (WIDTH // BLOCK_SIZE) - (2 * MARGIN_BLOCKS)  # 240 - 4 = 236
ROWS = (HEIGHT // BLOCK_SIZE) - (2 * MARGIN_BLOCKS)  # 135 - 4 = 131
BLOCKS_PER_FRAME = COLS * ROWS

# Each frame has a 16-byte header:
# [4B Magic: b'AFRM'] [4B Frame Index] [4B Total Frames] [4B Payload Bytes in this Frame]
FRAME_HEADER_SIZE = 16
FRAME_HEADER_BITS = FRAME_HEADER_SIZE * 8

PAYLOAD_BITS_PER_FRAME = BLOCKS_PER_FRAME - FRAME_HEADER_BITS
PAYLOAD_BYTES_PER_FRAME = PAYLOAD_BITS_PER_FRAME // 8



def pack_files_to_zip(file_paths: list[str]) -> bytes:
    """Compresses input files into an in-memory zip archive with max compression."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for f in file_paths:
            if os.path.isfile(f):
                zf.write(f, arcname=os.path.basename(f))
    return buf.getvalue()


def encode_data_to_video(data: bytes, output_video_path: str, fps: int = 30) -> dict:
    """
    Encodes raw bytes into a 1080p MP4 binary video using 8x8 macro-blocks.
    Returns metadata dict.
    """
    total_payload_bytes = len(data)
    payload_sha256 = hashlib.sha256(data).hexdigest()

    # Prepend Master Header:
    # [5B b"AETHR"] [1B Version] [4B Payload Len] [64B SHA256 Hex]
    master_header = struct.pack(">5sBI64s", b"AETHR", 1, total_payload_bytes, payload_sha256.encode('ascii'))
    full_stream = master_header + data

    # Calculate total frames needed
    total_frames = (len(full_stream) + PAYLOAD_BYTES_PER_FRAME - 1) // PAYLOAD_BYTES_PER_FRAME

    os.makedirs(os.path.dirname(os.path.abspath(output_video_path)), exist_ok=True)

    # Launch FFmpeg process to write video stream directly via pipe
    cmd = [
        FFMPEG_EXE,
        "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-pix_fmt", "gray",
        "-r", str(fps),
        "-i", "-",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "14",  # High quality to preserve sharp macro-block boundaries
        "-pix_fmt", "yuv420p",
        output_video_path
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    # Preallocate canvas and create view into the active grid area
    canvas = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    y_start = MARGIN_BLOCKS * BLOCK_SIZE
    x_start = MARGIN_BLOCKS * BLOCK_SIZE
    y_end = y_start + ROWS * BLOCK_SIZE
    x_end = x_start + COLS * BLOCK_SIZE
    # 4D view allows 0-copy vector broadcast directly into the canvas
    canvas_view = canvas[y_start:y_end, x_start:x_end].reshape((ROWS, BLOCK_SIZE, COLS, BLOCK_SIZE))

    offset = 0
    for frame_idx in range(total_frames):
        chunk = full_stream[offset : offset + PAYLOAD_BYTES_PER_FRAME]
        offset += len(chunk)

        # Build Frame Header: [AFRM] [frame_idx] [total_frames] [chunk_len]
        f_header = struct.pack(">4sIII", b"AFRM", frame_idx, total_frames, len(chunk))
        frame_bytes = f_header + chunk

        # Pad remaining bits with zeros if last frame
        frame_bits = np.unpackbits(np.frombuffer(frame_bytes, dtype=np.uint8))
        if len(frame_bits) < BLOCKS_PER_FRAME:
            pad = np.zeros(BLOCKS_PER_FRAME - len(frame_bits), dtype=np.uint8)
            frame_bits = np.concatenate([frame_bits, pad])
        elif len(frame_bits) > BLOCKS_PER_FRAME:
            frame_bits = frame_bits[:BLOCKS_PER_FRAME]

        # Reshape into block grid: 0 = 0 (black), 1 = 255 (white)
        grid = (frame_bits.reshape((ROWS, COLS)) * 255).astype(np.uint8)

        # High-speed vectorized broadcast filling all 8x8 pixels per block in ~1ms
        canvas_view[:, :, :, :] = grid[:, None, :, None]

        proc.stdin.write(canvas.tobytes())

    proc.stdin.close()
    proc.wait()


    return {
        "output_video": output_video_path,
        "total_frames": total_frames,
        "duration_sec": total_frames / fps,
        "original_bytes": total_payload_bytes,
        "sha256": payload_sha256,
        "fps": fps
    }


def encode_photo_batch(photo_paths: list[str], output_video_path: str) -> dict:
    """High-level API: Takes a list of image files, packs into zip, and encodes to MP4."""
    zip_bytes = pack_files_to_zip(photo_paths)
    meta = encode_data_to_video(zip_bytes, output_video_path)
    meta["photo_count"] = len(photo_paths)
    meta["photos"] = [os.path.basename(p) for p in photo_paths]
    return meta


if __name__ == "__main__":
    if len(sys.argv) > 1:
        files = sys.argv[1:]
        out = "vault_output.mp4"
        print(f"Encoding {len(files)} files into {out}...")
        res = encode_photo_batch(files, out)
        print("Success:", res)
    else:
        print("Aether Photos Encoder Engine Ready.")
