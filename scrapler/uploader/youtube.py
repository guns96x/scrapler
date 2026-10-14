import os
import re
import time
import logging
from typing import Optional, Dict, Any, Callable
from playwright.sync_api import sync_playwright, Browser, Page, TimeoutError as PwTimeoutError
from .job_store import JobStore

logger = logging.getLogger("octo_uploader.youtube")


class YouTubeUploadError(Exception):
    pass


class YouTubeUploader:
    """Automates video upload on YouTube Studio via CDP."""

    def __init__(self, ws_endpoint: str, job_store: Optional[JobStore] = None):
        self.ws_endpoint = ws_endpoint
        self.job_store = job_store

    def upload(
        self,
        video_path: str,
        title: str,
        description: str = "",
        visibility: str = "unlisted",  # unlisted, public, private
        job_id: Optional[str] = None,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        upload_timeout: int = 1800,
    ) -> Dict[str, Any]:
        """
        Executes complete video upload flow.
        """
        if not os.path.exists(video_path):
            raise YouTubeUploadError(f"Video file not found: {video_path}")

        video_path = os.path.abspath(video_path)
        visibility = visibility.upper()
        if visibility not in ["UNLISTED", "PUBLIC", "PRIVATE"]:
            visibility = "UNLISTED"

        logger.info(f"Connecting Playwright over CDP: {self.ws_endpoint}")
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(self.ws_endpoint)
            page = None
            try:
                # Always create a dedicated new page so we never overwrite or close user's tabs
                context = browser.contexts[0] if browser.contexts else browser
                page = context.new_page()
                logger.info("Opened dedicated upload tab for YouTube Studio")

                return self._run_upload_flow(
                    page=page,
                    video_path=video_path,
                    title=title,
                    description=description,
                    visibility=visibility,
                    job_id=job_id,
                    progress_callback=progress_callback,
                    upload_timeout=upload_timeout
                )
            finally:
                if page and not page.is_closed():
                    try:
                        page.close()
                    except Exception:
                        pass
                browser.close()

    def _update_job(self, job_id: Optional[str], **kwargs):
        if self.job_store and job_id:
            self.job_store.update_job(job_id=job_id, **kwargs)

    def _run_upload_flow(
        self,
        page: Page,
        video_path: str,
        title: str,
        description: str,
        visibility: str,
        job_id: Optional[str],
        progress_callback: Optional[Callable[[str, int], None]],
        upload_timeout: int
    ) -> Dict[str, Any]:
        def log_step(msg: str, pct: int = 0):
            logger.info(f"[{pct}%] {msg}")
            if progress_callback:
                progress_callback(msg, pct)

        log_step("Navigating to YouTube Studio...", 5)
        self._update_job(job_id, status="OPENING_STUDIO")
        page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=60000)

        # Check authentication
        time.sleep(3)
        current_url = page.url
        if "accounts.google.com" in current_url or "signin" in current_url.lower():
            err = "Authentication required: Octo profile is not logged into YouTube."
            self._update_job(job_id, status="FAILED", error_message=err)
            raise YouTubeUploadError(err)

        log_step("Locating Create / Upload button...", 10)
        upload_input = page.locator('input[type="file"]')
        if upload_input.count() == 0:
            create_btn = page.locator('#create-icon, button[aria-label*="Create" i], ytcp-button#create-icon')
            if create_btn.count() > 0:
                create_btn.first.click()
                time.sleep(1)
                upload_item = page.locator('tp-yt-paper-item:has-text("Upload"), ytcp-text-menu #text-item-0')
                if upload_item.count() > 0:
                    upload_item.first.click()
            else:
                dash_btn = page.locator('#upload-button, button:has-text("Upload videos")')
                if dash_btn.count() > 0:
                    dash_btn.first.click()

        # Wait for file input to appear
        log_step("Attaching video file...", 15)
        upload_input = page.locator('input[type="file"]')
        upload_input.wait_for(state="attached", timeout=30000)
        upload_input.set_input_files(video_path)

        log_step("File attached, waiting for upload dialog...", 20)
        self._update_job(job_id, status="UPLOADING")

        # Wait for dialog and extract video_id
        time.sleep(3)
        video_id = None
        video_url = None

        # Try to extract video link from dialog early
        for _ in range(15):
            url_elem = page.locator('a.ytcp-video-info, .video-url-fadeable a, span:has-text("youtu.be")')
            if url_elem.count() > 0:
                text = url_elem.first.inner_text().strip()
                href = url_elem.first.get_attribute("href") or ""
                candidate = href if "youtu.be" in href else text
                match = re.search(r"youtu\.be/([a-zA-Z0-9_-]+)", candidate)
                if match:
                    video_id = match.group(1)
                    video_url = f"https://youtu.be/{video_id}"
                    logger.info(f"Detected video ID early: {video_id} ({video_url})")
                    self._update_job(job_id, video_id=video_id, video_url=video_url)
                    break
            time.sleep(1)

        log_step("Configuring title and description...", 30)
        self._update_job(job_id, status="CONFIGURING_DETAILS")

        # Title: must succeed, do not swallow errors
        title_box = page.locator('#title-textarea #textbox, [aria-label*="title" i]#textbox')
        try:
            title_box.wait_for(state="visible", timeout=30000)
            title_box.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            title_box.fill(title)
        except Exception as e:
            err = f"Failed to set required video title: {e}"
            self._update_job(job_id, status="FAILED", error_message=err)
            raise YouTubeUploadError(err)

        # Description
        if description:
            desc_box = page.locator('#description-textarea #textbox, [aria-label*="description" i]#textbox')
            if desc_box.count() > 0:
                try:
                    desc_box.first.click()
                    desc_box.first.fill(description)
                except Exception as e:
                    logger.warning(f"Could not fill description: {e}")

        # Audience: 'Not made for kids'
        log_step("Setting audience: Not made for kids...", 40)
        not_for_kids = page.locator('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]')
        if not_for_kids.count() > 0:
            not_for_kids.first.click()
        else:
            fallback_kids = page.locator('tp-yt-paper-radio-button:has-text("No, it\'s not made for kids"), tp-yt-paper-radio-button:has-text("Ні, це відео не для дітей")')
            if fallback_kids.count() > 0:
                fallback_kids.first.click()

        # Step 1 -> 2: Next button
        log_step("Advancing through wizard...", 50)
        next_btn = page.locator('#next-button, button:has-text("Next"), button:has-text("Далі")')
        next_btn.wait_for(state="visible", timeout=15000)
        next_btn.click()
        time.sleep(2)

        # Step 2 -> 3: Next button (Video elements)
        next_btn.click()
        time.sleep(2)

        # Step 3 -> 4: Next button (Checks)
        next_btn.click()
        time.sleep(2)

        # Visibility step
        log_step(f"Setting visibility to {visibility}...", 65)
        visibility_applied = False
        vis_radio = page.locator(f'tp-yt-paper-radio-button[name="{visibility}"]')
        if vis_radio.count() > 0 and vis_radio.first.is_visible():
            vis_radio.first.click()
            visibility_applied = True
        else:
            vis_text = page.locator(f'tp-yt-paper-radio-button:has-text("{visibility.capitalize()}")')
            if vis_text.count() > 0 and vis_text.first.is_visible():
                vis_text.first.click()
                visibility_applied = True

        if not visibility_applied:
            err = f"Abort: Failed to locate and select requested visibility '{visibility}'. Halting to prevent unintended publication state."
            self._update_job(job_id, status="FAILED", error_message=err)
            raise YouTubeUploadError(err)

        time.sleep(1)

        # Re-check video_id if not yet found
        if not video_id:
            url_elem = page.locator('a.ytcp-video-info, .video-url-fadeable a, span:has-text("youtu.be")')
            if url_elem.count() > 0:
                candidate = url_elem.first.get_attribute("href") or url_elem.first.inner_text().strip()
                match = re.search(r"youtu\.be/([a-zA-Z0-9_-]+)", candidate)
                if match:
                    video_id = match.group(1)
                    video_url = f"https://youtu.be/{video_id}"
                    self._update_job(job_id, video_id=video_id, video_url=video_url)

        # Click Publish / Done
        log_step("Publishing / Saving...", 80)
        self._update_job(job_id, status="PUBLISHING")
        done_btn = page.locator('#done-button, button:has-text("Save"), button:has-text("Publish"), button:has-text("Опублікувати"), button:has-text("Зберегти")')
        done_btn.wait_for(state="visible", timeout=15000)
        done_btn.click()

        # Wait for confirmation dialog or close button
        log_step("Waiting for upload confirmation...", 90)
        start_wait = time.time()
        published_confirmed = False

        while time.time() - start_wait < upload_timeout:
            close_btn = page.locator('#close-button, ytcp-button#close-button, button:has-text("Close"), button:has-text("Закрити")')
            if close_btn.count() > 0 and close_btn.first.is_visible():
                modal_link = page.locator('.ytcp-video-share-dialog a, a.ytcp-video-info')
                if modal_link.count() > 0:
                    href = modal_link.first.get_attribute("href") or ""
                    match = re.search(r"youtu\.be/([a-zA-Z0-9_-]+)", href)
                    if match:
                        video_id = match.group(1)
                        video_url = f"https://youtu.be/{video_id}"

                close_btn.first.click()
                published_confirmed = True
                break

            progress_elem = page.locator('.progress-label, span:has-text("%")')
            if progress_elem.count() > 0:
                text = progress_elem.first.inner_text().strip()
                logger.debug(f"Upload progress: {text}")

            time.sleep(2)

        if not published_confirmed:
            logger.warning("Upload completion modal did not appear before timeout, marking as UNKNOWN_OUTCOME")
            status = "UNKNOWN_OUTCOME"
        else:
            status = "PUBLISHED"

        log_step(f"Upload complete! Status: {status}. URL: {video_url or 'N/A'}", 100)
        self._update_job(job_id, status=status, video_id=video_id, video_url=video_url)

        return {
            "status": status,
            "job_id": job_id,
            "video_id": video_id,
            "video_url": video_url,
            "visibility": visibility,
            "title": title
        }
