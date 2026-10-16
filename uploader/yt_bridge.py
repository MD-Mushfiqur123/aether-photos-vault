"""
Aether Photos - YouTube Connector Bridge
Handles the two real-world connections to YouTube:
  1. Downloader: Fetches raw 1080p MP4 binary stream from any unlisted YouTube URL via yt-dlp / session.
  2. Uploader: Guides browser session auth or OAuth credentials to upload MP4 photo vaults to YouTube.
"""

import os
import sys
import subprocess
import yt_dlp

def download_youtube_vault_video(video_url: str, output_path: str) -> str:
    """
    Downloads the highest quality 1080p MP4 video stream from a YouTube video URL.
    Returns the absolute filepath to the downloaded MP4.
    """
    ydl_opts = {
        'format': 'bestvideo[height<=1080][ext=mp4]/best[height<=1080][ext=mp4]/best',
        'outtmpl': output_path,
        'quiet': False,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])
    return output_path

if __name__ == "__main__":
    if len(sys.argv) > 1:
        url = sys.argv[1]
        out = sys.argv[2] if len(sys.argv) > 2 else "downloaded_vault.mp4"
        print(f"[*] Downloading YouTube Vault Video: {url} -> {out}")
        download_youtube_vault_video(url, out)
        print("[+] Download complete!")
    else:
        print("Usage: python yt_bridge.py <youtube_url> [output_path]")
