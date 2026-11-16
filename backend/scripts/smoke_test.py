"""Run against a separately running API and Celery worker; uses synthetic sample data."""
import argparse
import time
from pathlib import Path
import httpx

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    image = Path(__file__).resolve().parents[2] / "assets/sample-product.png"
    with httpx.Client(base_url=args.api, timeout=30) as client:
        with image.open("rb") as source:
            response = client.post("/api/v1/generations", files={"file": (image.name, source, "image/png")},
                                   data={"platform": "instagram", "format": "reel", "brand_name": "Studio Sample"})
        response.raise_for_status()
        job_id = response.json()["id"]
        print(f"Created job: {job_id}", flush=True)
        last_stage = None
        for _ in range(180):
            response = client.get(f"/api/v1/generations/{job_id}")
            response.raise_for_status()
            job = response.json()
            if job["stage"] != last_stage:
                print(f"{job['status']}: {job['stage']}", flush=True)
                last_stage = job["stage"]
            if job["status"] == "failed":
                raise RuntimeError(job["error_message"])
            if job["status"] == "completed":
                media = client.get(f"/api/v1/generations/{job_id}/download")
                media.raise_for_status()
                assert media.headers["content-type"] == "video/mp4" and len(media.content) > 1000
                package = client.get(f"/api/v1/generations/{job_id}/content")
                package.raise_for_status()
                print(f"Verified download ({len(media.content)} bytes), caption, and persisted job; mode={job['generation_mode']}")
                break
            time.sleep(1)
        else:
            raise TimeoutError("Generation did not finish within 180 seconds")


if __name__ == "__main__":
    main()
