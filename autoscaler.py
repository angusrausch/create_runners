import os
import shutil
import time
from dotenv import load_dotenv
import requests
import re
import platform
from urllib.request import urlretrieve
import subprocess
import tarfile
from datetime import datetime, timedelta, timezone
import stat
import uuid

load_dotenv()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 30))
MIN_RUNNERS = int(os.getenv("Min_RUNNERS", 0))
MAX_RUNNERS = int(os.getenv("MAX_RUNNERS", 2))
RUNNERS_DIR = os.getenv("RUNNERS_DIR", "runners")
DOWNLOADS_DIR = os.getenv("DOWNLOADS_DIR", "download")

if not GITHUB_TOKEN or not REPO_OWNER or not REPO_NAME:
    raise ValueError("Missing env vars: GITHUB_TOKEN, REPO_OWNER, REPO_NAME")

headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

class Runner_Watcher:
    def __init__(self):
        self.runners = []
        self.queued_jobs = []
        self.running_jobs = []
        self.token = None
        self.repo_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"

        try:
            os.mkdir(DOWNLOADS_DIR)
        except FileExistsError:
            pass
        try:
            os.mkdir(RUNNERS_DIR)
        except FileExistsError:
            pass
        
        self.check_updated_runner()
        self.build_runner()
        self.monitor_queued_runs()

    def get_runs_by_status(self, status):
        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/runs"
        params = {"status": status, "per_page": 10}
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            self.queued_jobs = response.json().get("workflow_runs", [])
        else:
            print(f"[ERROR] Failed to fetch {status} runs: {response.status_code} - {response.text}")
            self.queued_jobs = []

    def monitor_queued_runs(self):
        print(f"Monitoring queued GitHub Actions runs for {REPO_OWNER}/{REPO_NAME} every {POLL_INTERVAL}s...\n")
        seen_run_ids = set()

        try:
            while True:
                try:
                    self.get_runs_by_status("queued")

                    if self.queued_jobs:
                        print(f"[{time.strftime('%H:%M:%S')}] Queued runs: {len(self.queued_jobs)}")
                        for run in self.queued_jobs:
                            print(f"  - ID: {run['id']} | Branch: {run['head_branch']} | Event: {run['event']} | Created: {run['created_at']}")
                            seen_run_ids.add(run["id"])
                    else:
                        print(f"[{time.strftime('%H:%M:%S')}] No new queued runs.")

                except Exception as e:
                    print(f"[ERROR] {e}")

                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\nPlease wait while runners are stopped and removed")
            time.sleep(5)
            for runner in self.runners:
                self.stop_runner(runner)
        except Exception as e:
            print("Unhandled exception occured:\n{e}\nPlease wait while runners are stopped")
            for runner in self.runners:
                self.stop_runner(runner)
                


    def get_runner_registration_token(self):
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/runners/registration-token"
        response = requests.post(url, headers=headers)

        if response.status_code == 201:
            data = response.json()
            self.token = {
                "token": data["token"],
                "expires_at": data["expires_at"]
            }
        else:
            raise Exception(f"Failed to get runner token: {response.status_code} - {response.text}")


    def build_runner(self, number=1):
        archive_path = self.check_updated_runner()

        for i in range(number):
            runner_name = f"runner_{uuid.uuid4().hex}"
            runner_dir = os.path.join(RUNNERS_DIR, runner_name)
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(path=runner_dir)
            
            self.runners.append(runner_dir)
            self.check_token()
            print("Configuring runner")
            self.configure_runner(runner_name, runner_dir)
            print("Starting runner")
            self.start_runner(runner_dir)
            print(f"Started runner {runner_dir}")

    def configure_runner(self, runner_name, runner_dir):
        config_script = os.path.join(runner_dir, "config.sh")
        os.chmod(config_script, os.stat(config_script).st_mode | stat.S_IEXEC)

        subprocess.run(
            [config_script, "--url", self.repo_url, "--token", self.token["token"], "--name", runner_name, "--unattended"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=30
        )

    def start_runner(self, runner_dir):
        original_dir = os.getcwd()
        os.chdir(runner_dir)

        result = subprocess.run(
            ["sudo", "./svc.sh", "install"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        result = subprocess.run(
            ["sudo", "./svc.sh", "start"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        os.chdir(original_dir)

    def stop_runner(self, runner_dir):
        original_dir = os.getcwd()
        os.chdir(runner_dir)

        subprocess.run(
            ["sudo", "./svc.sh", "stop"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        subprocess.run(
            ["sudo", "./svc.sh", "uninstall"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        subprocess.run(
            ["./config.sh", "remove", "--token", self.token["token"]],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        
        os.chdir(original_dir)
        try:
            shutil.rmtree(runner_dir)
        except Exception as e:
            print(f"Failed to remove {runner_dir} directory")


    def check_token(self):
        if self.token:
            expires_at = datetime.strptime(self.token["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if now + timedelta(minutes=5) <= expires_at:
                return
        self.get_runner_registration_token()

    def check_updated_runner(self):
        print("Checking current runner version")
        version = Runner_Watcher.find_latest_version()
        arch = Runner_Watcher.find_machine_arch()

        filename = f"actions-runner-linux-{arch}-{version}.tar.gz"
        file_path = os.path.join(DOWNLOADS_DIR, filename)
        if os.path.isfile(file_path):
            print("Runner up to date")
        else:
            print("Runner update required")
            Runner_Watcher.update_runner(version, filename, file_path)
            print("Downloaded updated runner")
        return file_path

    @classmethod
    def update_runner(cls, version, filename, file_path):
        download_url= f"https://github.com/actions/runner/releases/download/v{version}/{filename}"
        urlretrieve(download_url, file_path)

    @classmethod
    def find_latest_version(cls):
        tag_page_url = "https://github.com/actions/runner/tags"

        try:
            response = requests.get(tag_page_url)
            response.raise_for_status()
            tag_page = response.text
        except requests.RequestException as e:
            print(f"Failed to fetch tags: {e}")
            exit(1)

        versions = re.findall(r'href="/actions/runner/releases/tag/v(\d+\.\d+\.\d+)"', tag_page)

        if not versions:
            print("No versions found.")
            exit(1)
        
        latest_version = sorted(versions)[-1]
        return latest_version

    @classmethod
    def find_machine_arch(cls):
        arch = platform.machine()

        if arch == "x86_64":
            return "x64"
        elif arch in ["arm64", "aarch64"]:
            return "arm64"
        else:
            print(f"Unknown ARCH type: {arch}")
            exit(1)


if __name__ == "__main__":
    Runner_Watcher()