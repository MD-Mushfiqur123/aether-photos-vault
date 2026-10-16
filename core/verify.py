"""
Aether Photos - Automated End-to-End Verification Test
Creates sample photos/data, encodes to 1080p binary video, decodes back,
and compares SHA-256 hashes bit-for-bit to prove zero data corruption.
"""

import os
import sys
import hashlib

sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image, ImageDraw
from encoder import encode_photo_batch
from decoder import extract_photos_from_video

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_INPUT = os.path.join(BASE_DIR, "test_input")
TEST_OUTPUT_VIDEO = os.path.join(BASE_DIR, "test_vault_video.mp4")
TEST_RECOVERED = os.path.join(BASE_DIR, "test_recovered")


def generate_sample_photos(num_photos=5):
    """Generates synthetic high-res photos for testing."""
    os.makedirs(TEST_INPUT, exist_ok=True)
    generated = []

    colors = [
        (255, 99, 71),   # Tomato
        (30, 144, 255),  # DodgerBlue
        (50, 205, 50),   # LimeGreen
        (255, 215, 0),   # Gold
        (138, 43, 226)   # BlueViolet
    ]

    for i in range(num_photos):
        p_path = os.path.join(TEST_INPUT, f"sample_photo_{i+1:02d}.png")
        img = Image.new("RGB", (640, 480), color=colors[i % len(colors)])
        draw = ImageDraw.Draw(img)
        draw.text((40, 40), f"Aether Vault Test Photo #{i+1}", fill=(255, 255, 255))
        draw.rectangle([100, 100, 540, 380], outline=(255, 255, 255), width=4)
        img.save(p_path)
        generated.append(p_path)

    return generated


def get_file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_full_verification():
    print("==================================================")
    print("🚀 STARTING AETHER PHOTOS END-TO-END VERIFICATION")
    print("==================================================")

    # 1. Generate test photos
    photos = generate_sample_photos(5)
    print(f"[1/4] Generated {len(photos)} test photos:")
    orig_hashes = {}
    for p in photos:
        h = get_file_sha256(p)
        orig_hashes[os.path.basename(p)] = h
        print(f"      - {os.path.basename(p)} (SHA256: {h[:16]}...)")

    # 2. Encode to binary MP4
    print("\n[2/4] Encoding photos into 1080p binary video...")
    encode_meta = encode_photo_batch(photos, TEST_OUTPUT_VIDEO)
    print(f"      - Video: {os.path.basename(TEST_OUTPUT_VIDEO)}")
    print(f"      - Frames: {encode_meta['total_frames']}")
    print(f"      - Duration: {encode_meta['duration_sec']:.2f} seconds")
    print(f"      - Video File Size: {os.path.getsize(TEST_OUTPUT_VIDEO)} bytes")

    # 3. Decode from binary MP4
    print("\n[3/4] Decoding video stream and extracting original files...")
    decode_meta = extract_photos_from_video(TEST_OUTPUT_VIDEO, TEST_RECOVERED)
    print(f"      - Extracted count: {decode_meta['extracted_count']}")
    print(f"      - Checksum verified: {decode_meta['checksum_verified']}")

    # 4. Bit-for-bit comparison
    print("\n[4/4] Verifying Bit-for-Bit SHA-256 Hash Matching:")
    all_matched = True
    for fname, orig_h in orig_hashes.items():
        rec_path = os.path.join(TEST_RECOVERED, fname)
        if not os.path.exists(rec_path):
            print(f"      ❌ MISSING FILE: {fname}")
            all_matched = False
            continue
        rec_h = get_file_sha256(rec_path)
        if orig_h == rec_h:
            print(f"      ✅ 100% BIT-PERFECT MATCH: {fname}")
        else:
            print(f"      ❌ HASH MISMATCH: {fname}")
            all_matched = False

    print("\n==================================================")
    if all_matched:
        print("🎉 VERIFICATION SUCCESS: ZERO DATA LOSS (100% BIT-IDENTICAL)")
    else:
        print("❌ VERIFICATION FAILED")
    print("==================================================")


if __name__ == "__main__":
    run_full_verification()
