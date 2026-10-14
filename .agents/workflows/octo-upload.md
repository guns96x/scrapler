---
description: Automated video upload to YouTube Studio via Octo Browser antidetect profile
globs: scrapler/uploader/**/*.py
---

# Octo Browser Video Upload Workflow

When instructed to upload a video:
1. Verify Octo Browser is running:
   ```bash
   python -m scrapler.uploader.cli doctor
   ```
2. Upload video with the requested title, description, and visibility:
   ```bash
   python -m scrapler.uploader.cli upload --video "<PATH_TO_VIDEO>" --title "<TITLE>" --desc "<DESCRIPTION>" --visibility "<unlisted|public>"
   ```
3. Parse the JSON result from `stdout` to get `video_url` and `video_id`.
