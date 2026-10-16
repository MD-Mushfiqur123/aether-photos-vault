"""
Aether Photos - YouTube Studio Browser Session Automator
Uses Playwright with real Chrome user data or launched browser to upload
the generated binary MP4 vault directly to YouTube Studio as an Unlisted video.
"""

import os
import sys
import time
import json
import asyncio
from playwright.async_api import async_playwright

CHROME_USER_DATA = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
DEFAULT_CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

async def upload_vault_to_youtube(video_path: str, title: str = None, description: str = None) -> dict:
    """
    Automates uploading an MP4 video file to YouTube Studio using the user's browser session.
    Uploads with 'Unlisted' visibility to preserve unlimited free storage.
    """
    if not os.path.exists(video_path):
        return {"status": "ERROR", "message": f"File not found: {video_path}"}

    if not title:
        title = f"Data Stream // {os.path.basename(video_path)}"
    if not description:
        description = "Encrypted binary data vault container. Bit-perfect archive."

    async with async_playwright() as p:
        # Launch real Chrome browser with persistent context or standard session
        # If user is logged into YouTube in Chrome, cookies carry over seamlessly
        user_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_session")
        os.makedirs(user_data_dir, exist_ok=True)

        print("[*] Launching Browser Session for YouTube Studio upload...")
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            executable_path=DEFAULT_CHROME_EXE if os.path.exists(DEFAULT_CHROME_EXE) else None,
            headless=False, # Show browser window so user can see & auth if needed
            args=["--disable-blink-features=AutomationControlled"]
        )

        page = await browser.new_page()
        print("[*] Navigating to YouTube Studio...")
        await page.goto("https://studio.youtube.com", wait_until="networkidle")

        # Check if user needs to sign in
        if "accounts.google.com" in page.url or "signin" in page.url:
            print("[!] Please sign in to YouTube Studio in the opened Chrome window...")
            # Wait up to 120 seconds for user to complete Google sign-in
            try:
                await page.wait_for_url("https://studio.youtube.com/**", timeout=120000)
            except Exception:
                await browser.close()
                return {"status": "AUTH_REQUIRED", "message": "Sign-in timed out. Please sign in to Google in browser."}

        print("[*] Logged in to YouTube Studio. Initiating video upload...")
        await page.goto("https://studio.youtube.com/channel/upload", wait_until="networkidle")

        # Select file input
        file_input = page.locator('input[type="file"]')
        await file_input.set_input_files(video_path)
        print(f"[*] Uploading file: {video_path}...")

        # Wait for dialog and video ID link
        await page.wait_for_selector("#dialog", timeout=60000)
        await asyncio.sleep(5)

        # Extract generated YouTube Video ID
        video_link = ""
        try:
            link_elem = page.locator("a.ytcp-video-info")
            if await link_elem.count() > 0:
                video_link = await link_elem.first.get_attribute("href")
            else:
                # Look for video URL anchor
                anchors = await page.locator('a[href*="youtu.be"]').all()
                if anchors:
                    video_link = await anchors[0].get_attribute("href")
        except Exception as e:
            print(f"[!] Could not immediately parse video URL: {e}")

        video_id = video_link.split("/")[-1] if video_link else ""
        print(f"[+] YouTube Video ID generated: {video_id} ({video_link})")

        # Step 1: Details (Title is auto-filled with filename)
        # Step 2: Set "Not Made for Kids"
        try:
            not_for_kids_radio = page.locator('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]')
            if await not_for_kids_radio.count() > 0:
                await not_for_kids_radio.click()
        except Exception:
            pass

        # Click Next until Visibility tab
        for _ in range(3):
            next_btn = page.locator("#next-button")
            if await next_btn.is_visible() and await next_btn.is_enabled():
                await next_btn.click()
                await asyncio.sleep(2)

        # Visibility: Set to "Unlisted"
        try:
            unlisted_radio = page.locator('tp-yt-paper-radio-button[name="UNLISTED"]')
            if await unlisted_radio.count() > 0:
                await unlisted_radio.click()
        except Exception:
            pass

        # Click Save / Publish
        done_btn = page.locator("#done-button")
        if await done_btn.is_visible():
            await done_btn.click()
            print("[+] Clicked Publish / Save as Unlisted!")
            await asyncio.sleep(5)

        await browser.close()
        return {
            "status": "SUCCESS",
            "video_id": video_id or "UPLOADED",
            "video_url": f"https://youtu.be/{video_id}" if video_id else "Uploaded to YouTube Studio"
        }

if __name__ == "__main__":
    if len(sys.argv) > 1:
        vid = sys.argv[1]
        res = asyncio.run(upload_vault_to_youtube(vid))
        print(json.dumps(res, indent=2))
    else:
        print("Usage: python yt_uploader.py <path_to_mp4>")
