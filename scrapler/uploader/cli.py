import sys
import os
import json
import uuid
import argparse
import logging
from typing import Optional

from .octo_client import OctoClient, OctoClientError
from .job_store import JobStore
from .youtube import YouTubeUploader, YouTubeUploadError

DEFAULT_PROFILE_UUID = "6a4fadba6da048cea9f54f532dfcb1e0"

# Configure logging to stderr so stdout remains clean JSON
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger("octo_uploader.cli")


def cmd_doctor(args):
    client = OctoClient()
    healthy = client.is_healthy()
    active_profiles = []
    if healthy:
        try:
            active_profiles = client.get_active_profiles()
        except Exception as e:
            logger.warning(f"Failed to fetch active profiles: {e}")

    result = {
        "status": "ok" if healthy else "error",
        "octo_api_online": healthy,
        "octo_api_url": client.base_url,
        "default_profile_uuid": DEFAULT_PROFILE_UUID,
        "active_profiles_count": len(active_profiles),
        "active_profiles": active_profiles
    }
    print(json.dumps(result, indent=2))
    sys.exit(0 if healthy else 1)


def cmd_status(args):
    store = JobStore()
    job = store.get_job(args.job_id)
    if not job:
        print(json.dumps({"error": f"Job not found: {args.job_id}"}))
        sys.exit(1)
    print(json.dumps(job, indent=2))
    sys.exit(0)


def cmd_upload(args):
    video_path = os.path.abspath(args.video)
    if not os.path.exists(video_path) or not os.path.isfile(video_path):
        res = {"status": "error", "message": f"File does not exist or is a directory: {video_path}"}
        print(json.dumps(res))
        sys.exit(1)

    profile_uuid = args.profile_uuid or DEFAULT_PROFILE_UUID
    job_id = args.job_id or f"job-{uuid.uuid4().hex[:8]}"
    store = JobStore()
    lock_timeout = args.timeout + 600

    if not store.acquire_lock(profile_uuid, job_id, timeout_seconds=lock_timeout):
        res = {
            "status": "locked",
            "message": f"Profile {profile_uuid} is currently locked by another active operation."
        }
        print(json.dumps(res))
        sys.exit(1)

    # All work following successful lock acquisition is inside try/finally
    started_by_us = False
    client = OctoClient()
    try:
        if not client.is_healthy():
            res = {
                "status": "error",
                "message": "Octo Browser local API is not running on http://127.0.0.1:58888. Please start Octo Browser."
            }
            print(json.dumps(res))
            sys.exit(1)

        store.create_job(
            job_id=job_id,
            profile_uuid=profile_uuid,
            file_path=video_path,
            title=args.title,
            description=args.desc or "",
            visibility=args.visibility
        )

        start_info = client.start_profile(
            uuid=profile_uuid,
            headless=args.headless,
            debug_port=True
        )
        started_by_us = not start_info.get("already_running", False)
        ws_endpoint = start_info.get("ws_endpoint")

        if not ws_endpoint:
            raise OctoClientError(f"No ws_endpoint returned by Octo for profile {profile_uuid}")

        uploader = YouTubeUploader(ws_endpoint=ws_endpoint, job_store=store)
        upload_result = uploader.upload(
            video_path=video_path,
            title=args.title,
            description=args.desc or "",
            visibility=args.visibility,
            job_id=job_id,
            upload_timeout=args.timeout
        )

        final_res = {
            "status": upload_result.get("status", "PUBLISHED"),
            "job_id": job_id,
            "video_id": upload_result.get("video_id"),
            "video_url": upload_result.get("video_url"),
            "visibility": upload_result.get("visibility"),
            "title": args.title,
            "profile_uuid": profile_uuid
        }
        print(json.dumps(final_res, indent=2))

    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        store.update_job(job_id=job_id, status="FAILED", error_message=str(e))
        err_res = {
            "status": "failed",
            "job_id": job_id,
            "error": str(e),
            "profile_uuid": profile_uuid
        }
        print(json.dumps(err_res, indent=2))
        sys.exit(1)

    finally:
        # Cleanup: stop profile if started by this script and --keep-open is not set
        if started_by_us and not args.keep_open:
            logger.info("Stopping Octo profile started by uploader...")
            try:
                client.stop_profile(profile_uuid)
            except Exception as e:
                logger.warning(f"Error while stopping Octo profile: {e}")
        store.release_lock(profile_uuid, job_id)


def main():
    parser = argparse.ArgumentParser(description="Octo Browser YouTube Uploader CLI for AI Agents")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Doctor
    doc_parser = subparsers.add_parser("doctor", help="Check Octo Browser API status")
    doc_parser.set_defaults(func=cmd_doctor)

    # Status
    stat_parser = subparsers.add_parser("status", help="Get status of an upload job")
    stat_parser.add_argument("--job-id", required=True, help="Job ID")
    stat_parser.set_defaults(func=cmd_status)

    # Upload
    up_parser = subparsers.add_parser("upload", help="Upload a video to YouTube Studio via Octo Browser")
    up_parser.add_argument("--video", required=True, help="Path to video file (.mp4, .mov, etc.)")
    up_parser.add_argument("--title", required=True, help="Video title")
    up_parser.add_argument("--desc", default="", help="Video description")
    up_parser.add_argument("--visibility", choices=["unlisted", "public", "private"], default="unlisted", help="Visibility (default: unlisted)")
    up_parser.add_argument("--profile-uuid", default=DEFAULT_PROFILE_UUID, help="Octo profile UUID")
    up_parser.add_argument("--job-id", default=None, help="Custom job ID")
    up_parser.add_argument("--headless", action="store_true", default=False, help="Run browser headless")
    up_parser.add_argument("--keep-open", action="store_true", default=False, help="Keep Octo profile running after upload")
    up_parser.add_argument("--timeout", type=int, default=1800, help="Upload timeout in seconds (default: 1800)")
    up_parser.set_defaults(func=cmd_upload)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
