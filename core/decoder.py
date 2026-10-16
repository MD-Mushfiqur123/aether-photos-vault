"""
Aether Photos - Binary Video Decoder Engine
Reads 1080p binary video stream, samples 8x8 macro-block centers,
recovers the bitstream, verifies SHA-256 checksum, and restores original files 100% bit-for-bit.
"""

import os
import sys
import struct
import hashlib
import zipfile
import io
import subprocess
import numpy as np

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

FRAME_HEADER_SIZE = 16
FRAME_HEADER_BITS = FRAME_HEADER_SIZE * 8



class AetherDecoderError(Exception):
    """Base exception for Aether video decoding failures."""
    pass

class CorruptedHeaderError(AetherDecoderError):
    """Raised when master header magic is invalid or corrupted."""
    pass

class IncompleteStreamError(AetherDecoderError):
    """Raised when required video frames are missing or stream is truncated."""
    pass

class ChecksumMismatchError(AetherDecoderError):
    """Raised when SHA-256 payload integrity check fails."""
    pass


def decode_video_to_data(video_path: str) -> bytes:
    """
    Decodes the binary MP4 video into raw payload bytes.
    Verifies frame sequence and SHA-256 integrity with robust error diagnostics.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Aether video vault file not found: '{video_path}'")

    if os.path.getsize(video_path) == 0:
        raise IncompleteStreamError(f"Video file is empty (0 bytes): '{video_path}'")

    # Launch FFmpeg to decode video frames to raw grayscale byte stream
    cmd = [
        FFMPEG_EXE,
        "-i", video_path,
        "-f", "rawvideo",
        "-pix_fmt", "gray",
        "-vsync", "0",
        "-"
    ]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        raise AetherDecoderError(f"FFmpeg binary not found at '{FFMPEG_EXE}'. Ensure FFmpeg or imageio-ffmpeg is installed.")

    frame_bytes_len = WIDTH * HEIGHT
    y_start = MARGIN_BLOCKS * BLOCK_SIZE
    x_start = MARGIN_BLOCKS * BLOCK_SIZE

    # Pre-calculate slice bounds (sampling center pixel of each 8x8 block)
    y_center_start = y_start + (BLOCK_SIZE // 2)
    x_center_start = x_start + (BLOCK_SIZE // 2)
    y_center_end = y_center_start + ROWS * BLOCK_SIZE
    x_center_end = x_center_start + COLS * BLOCK_SIZE

    recovered_chunks = {}
    expected_total_frames = None
    processed_raw_frames = 0
    corrupted_frame_counter = 0

    try:
        while True:
            raw_frame = proc.stdout.read(frame_bytes_len)
            if not raw_frame:
                break
            if len(raw_frame) < frame_bytes_len:
                # Truncated trailing frame data from decoder
                break

            processed_raw_frames += 1
            frame_arr = np.frombuffer(raw_frame, dtype=np.uint8).reshape((HEIGHT, WIDTH))

            # Ultra-fast strided slice: samples all macro-block centers directly with zero overhead
            sampled_grid = frame_arr[y_center_start:y_center_end:BLOCK_SIZE, x_center_start:x_center_end:BLOCK_SIZE]
            
            # Binary threshold: > 128 is 1, <= 128 is 0
            bits = (sampled_grid > 128).astype(np.uint8).ravel()

            # Pack bits into bytes
            frame_data = np.packbits(bits).tobytes()


            # Check Frame Header: [4B Magic: b'AFRM'] [4B Frame Index] [4B Total Frames] [4B Chunk Len]
            if len(frame_data) < FRAME_HEADER_SIZE:
                corrupted_frame_counter += 1
                continue

            magic, f_idx, tot_frames, chunk_len = struct.unpack(">4sIII", frame_data[:FRAME_HEADER_SIZE])
            if magic != b"AFRM":
                corrupted_frame_counter += 1
                continue

            # Basic sanity check on frame metadata
            if tot_frames == 0 or tot_frames > 1_000_000 or f_idx >= tot_frames:
                corrupted_frame_counter += 1
                continue

            expected_total_frames = tot_frames
            chunk = frame_data[FRAME_HEADER_SIZE : FRAME_HEADER_SIZE + chunk_len]
            recovered_chunks[f_idx] = chunk
    finally:
        if proc.stdout:
            proc.stdout.close()
        proc.wait()

    if not recovered_chunks:
        detail = f"Processed {processed_raw_frames} raw video frames, but 0 valid Aether frames (b'AFRM') were detected."
        if corrupted_frame_counter > 0:
            detail += f" ({corrupted_frame_counter} candidate frames had corrupt or mismatched headers)."
        raise CorruptedHeaderError(f"No valid Aether binary stream found in '{video_path}'. {detail}")

    # Assemble full stream in frame order and check for missing frames
    if expected_total_frames is None:
        raise IncompleteStreamError("Stream header metadata missing total frame count.")

    missing_frames = [idx for idx in range(expected_total_frames) if idx not in recovered_chunks]
    if missing_frames:
        preview_missing = missing_frames[:5]
        raise IncompleteStreamError(
            f"Incomplete video stream! Missing {len(missing_frames)} of {expected_total_frames} frames "
            f"(Frames: {preview_missing}{'...' if len(missing_frames) > 5 else ''}). "
            f"The video may have been truncated or corrupted during upload/download."
        )

    full_stream = io.BytesIO()
    for idx in range(expected_total_frames):
        full_stream.write(recovered_chunks[idx])

    assembled_bytes = full_stream.getvalue()

    # Parse Master Header: [5B b"AETHR"] [1B Version] [4B Total Payload Len] [64B SHA256 Hex]
    master_header_size = 5 + 1 + 4 + 64
    if len(assembled_bytes) < master_header_size:
        raise IncompleteStreamError(
            f"Assembled stream is truncated ({len(assembled_bytes)} bytes). "
            f"Required at least {master_header_size} bytes for Aether master header."
        )

    magic, version, payload_len, expected_sha_bytes = struct.unpack(">5sBI64s", assembled_bytes[:master_header_size])
    if magic != b"AETHR":
        raise CorruptedHeaderError(
            f"Invalid Aether master header magic. Expected b'AETHR', received {repr(magic)}. "
            f"The video container does not contain a recognized Aether payload."
        )

    try:
        expected_sha256 = expected_sha_bytes.decode('ascii')
    except UnicodeDecodeError:
        raise CorruptedHeaderError("Aether master header contains corrupt SHA-256 checksum string.")

    if len(assembled_bytes) < master_header_size + payload_len:
        raise IncompleteStreamError(
            f"Payload truncated: expected {payload_len} bytes from master header, but only found "
            f"{len(assembled_bytes) - master_header_size} payload bytes in stream."
        )

    payload = assembled_bytes[master_header_size : master_header_size + payload_len]

    # Verify SHA-256 Checksum
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256.lower() != expected_sha256.lower():
        raise ChecksumMismatchError(
            f"Aether Vault SHA-256 checksum mismatch!\n"
            f"Expected: {expected_sha256}\n"
            f"Actual:   {actual_sha256}\n"
            f"Bit-for-bit integrity validation failed. Payload may be damaged."
        )

    return payload


def extract_photos_from_video(video_path: str, output_dir: str) -> dict:
    """
    High-level API: Decodes video, extracts all original photos, and saves to output directory.
    Returns extraction summary.
    """
    os.makedirs(output_dir, exist_ok=True)
    zip_bytes = decode_video_to_data(video_path)

    extracted_files = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
        for info in zf.infolist():
            zf.extract(info, path=output_dir)
            extracted_files.append({
                "filename": info.filename,
                "size_bytes": info.file_size
            })

    return {
        "status": "SUCCESS",
        "checksum_verified": True,
        "output_directory": output_dir,
        "extracted_count": len(extracted_files),
        "files": extracted_files
    }


if __name__ == "__main__":
    if len(sys.argv) > 2:
        vid = sys.argv[1]
        out_d = sys.argv[2]
        print(f"Decoding {vid} to {out_d}...")
        res = extract_photos_from_video(vid, out_d)
        print("Success:", res)
    else:
        print("Aether Photos Decoder Engine Ready.")
