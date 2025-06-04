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
MAX_RUNNERS = int(os.getenv("MAX_RUNNERS", 4))
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
        self.built_runners = []
        self.queued_jobs = []
        self.running_jobs = []
        self.check_token()
        self.repo_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"
        try:
            os.mkdir(DOWNLOADS_DIR)
        except FileExistsError:
            print("Download Directory Exists")
        try:
            os.mkdir(RUNNERS_DIR)
        except FileExistsError:
            print("Runner Directory Exists")
        
        self.get_current_runners()
        for runner in self.runners:
            runner.safe_to_close()
        
        self.monitor_queued_runs()

    def get_current_runners(self):
        for dir in os.listdir(RUNNERS_DIR):
            if Runner.check_valid(dir):
                runner = Runner(name=dir)
                runner.stop()
                self.built_runners.append(runner)
                
        print(f"Found {len(self.built_runners)} valid runners")

    def get_runs_by_status(self, status):
        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/runs"
        params = {"status": status, "per_page": 20}

        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json().get("workflow_runs", [])
        else:
            print(f"[ERROR] Failed to fetch {status} runs: {response.status_code} - {response.text}")
            return []

    def monitor_queued_runs(self):
        print(f"Monitoring queued GitHub Actions runs for {REPO_OWNER}/{REPO_NAME} every {POLL_INTERVAL}s...\n")
        seen_run_ids = set()

        while len(self.built_runners) < MAX_RUNNERS:
            self.build_runners()

        try:
            while True:
                try:
                    self.queued_jobs = self.get_runs_by_status("queued")
                    self.active_jobs = self.get_runs_by_status("in_progress")
                    if self.queued_jobs:
                        print(f"[{time.strftime('%H:%M:%S')}] Queued runs: {len(self.queued_jobs)}")
                        for run in self.queued_jobs:
                            print(f"  - ID: {run['id']} | Branch: {run['head_branch']} | Event: {run['event']} | Created: {run['created_at']}")
                            seen_run_ids.add(run["id"])
                    else:
                        print(f"[{time.strftime('%H:%M:%S')}] No queued runs.")
                    
                    if self.active_jobs:
                        print(f"[{time.strftime('%H:%M:%S')}] Active runs: {len(self.active_jobs)}")
                        for run in self.active_jobs:
                            print(f"  - ID: {run['id']} | Branch: {run['head_branch']} | Event: {run['event']} | Created: {run['created_at']}")
                            seen_run_ids.add(run["id"])
                    else:
                        print(f"[{time.strftime('%H:%M:%S')}] No active runs.")

                    print(f"[{time.strftime('%H:%M:%S')}] {len(self.runners)} Active.")
                    print(f"[{time.strftime('%H:%M:%S')}] {len(self.built_runners)} On Standby.")

                except Exception as e:
                    print(f"[ERROR] {e}")
                
                runners_to_build = min(len(self.queued_jobs), MAX_RUNNERS)
                if runners_to_build:
                    self.up_runners(runners_to_build)

                if len(self.queued_jobs) == 0 and len(self.active_jobs) < len(self.runners):
                    self.down_runners()

                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\nPlease wait while runners are stopped and removed")
            for runner in self.runners:
                self.check_token()
                runner.stop(self.token["token"])
        except Exception as e:
            print(f"Unhandled exception occured:\n{e}\nPlease wait while runners are stopped")
            for runner in self.runners:
                self.check_token()
                runner.stop(self.token["token"])
                

    @classmethod
    def get_runner_registration_token(self):
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/runners/registration-token"
        response = requests.post(url, headers=headers)

        if response.status_code == 201:
            data = response.json()
            return {
                "token": data["token"],
                "expires_at": data["expires_at"]
            }
        else:
            raise Exception(f"Failed to get runner token: {response.status_code} - {response.text}")

    def up_runners(self, number=1):
        if self.built_runners:
            while number > 0 and self.built_runners:
                runner = self.built_runners[0]
                self.built_runners.pop(0)
                self.runners.append(runner)
                runner.start()
                number -= 1
        self.build_runners(number, True)

    def down_runners(self):
        for index in range(len(self.runners)):
            # Need to get rid of index error
            try:
                runner = self.runners[index]
                if runner.safe_to_close():
                    runner.stop()
                    self.runners.pop(index)
                    self.built_runners.append(runner)
            except IndexError:
                pass

    def build_runners(self, number=1, start=False):
        archive_path = self.check_updated_runner()
        for i in range(number):
            self.check_token()
            runner = Runner(archive_path=archive_path, token=self.token["token"], repo_url=self.repo_url)
            self.built_runners.append(runner)
            if start:
                runner.start()

    def check_token(self):
        if hasattr(self, "token") and self.token:
            try:
                expires_at = datetime.strptime(self.token["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                expires_at = datetime.strptime(self.token["expires_at"], "%Y-%m-%dT%H:%M:%S.%f%z").replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if now + timedelta(minutes=5) <= expires_at:
                return            
        self.token = self.get_runner_registration_token()
        if not self.token:
            print("Failed retrieving token. Stopping!")
            exit()

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

class Runner:
    def __init__(self, name=None, archive_path=None, token=None, repo_url=None):
        if name:
            self.runner_name = name
            self.runner_dir = os.path.join(RUNNERS_DIR, name)
            self.service_name = f"actions.runner.{REPO_OWNER}-{REPO_NAME}.{name}.service"
        else:
            if not all([archive_path, token, repo_url]):
                raise ValueError("archive_path, token, and repo_url are required when name is not provided")

            self.runner_name = f"runner_{uuid.uuid4().hex}"
            self.service_name = f"actions.runner.{REPO_OWNER}-{REPO_NAME}.{self.runner_name}.service"

            self.runner_dir = os.path.join(RUNNERS_DIR, self.runner_name)
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(path=self.runner_dir)

            print("Configuring runner")
            self.configure(token, repo_url)


    def safe_to_close(self):
        try:
            status = str(subprocess.check_output(["journalctl", "-u", self.service_name, "-n", "1"]))
            print(status)
            if "Running job:" not in status: 
                return True
        except subprocess.CalledProcessError:
            print(f"Failed to get status from {self.runner_name}")
        return False

    @classmethod
    def check_valid(cls, runner):
        runner_dir = os.path.join(RUNNERS_DIR, runner)

        original_dir = os.getcwd()
        os.chdir(runner_dir)
        print(f"Testing runner {runner_dir}")
        try:
            subprocess.run(
                ["sudo", "./svc.sh", "start"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10
            )
            subprocess.run(
                ["sudo", "./svc.sh", "stop"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            print(f"Runner failed check, removing!")
            os.chdir(original_dir)
            Runner.manual_delete_runner(runner_dir)
            return False
        else:
            os.chdir(original_dir)
            return True

    
    @classmethod
    def manual_delete_runner(cls, runner_dir):
        original_dir = os.getcwd()
        os.chdir(runner_dir)

        print("Uninstalling runner")
        try:
            subprocess.run(
                ["sudo", "svc.sh", "uninstall"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            print(f"Failed uninstalling runner")
        try:
            subprocess.run(
                ["./config.sh", "remove", "--token", Runner_Watcher.get_runner_registration_token()["token"]],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            print(f"Failed removing runner")
        finally:
            os.chdir(original_dir)            

        print("Deleting runner dir")
        try:
            shutil.rmtree(runner_dir)
        except shutil.ExecError as e:
            print(f"Failed to remove {runner_dir} directory")            
            

    def configure(self, token, repo_url):
        config_script = os.path.join(self.runner_dir, "config.sh")

        subprocess.run(
            [config_script, "--url", repo_url, "--token", token, "--name", self.runner_name, "--unattended"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=30
        )
        original_dir = os.getcwd()
        os.chdir(self.runner_dir)
        subprocess.run(
            ["sudo", "./svc.sh", "install"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        os.chdir(original_dir)


    def start(self):
        original_dir = os.getcwd()
        os.chdir(self.runner_dir)
        subprocess.run(
            ["sudo", "./svc.sh", "start"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        os.chdir(original_dir)

    def stop(self, token=None):
        original_dir = os.getcwd()
        os.chdir(self.runner_dir)

        subprocess.run(
            ["sudo", "./svc.sh", "stop"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        # subprocess.run(
        #     ["sudo", "./svc.sh", "uninstall"],
        #     capture_output=True,
        #     text=True,
        #     check=True,
        #     timeout=10
        # )
        # subprocess.run(
        #     ["./config.sh", "remove", "--token", token],
        #     capture_output=True,
        #     text=True,
        #     check=True,
        #     timeout=10
        # )
        
        os.chdir(original_dir)
        # try:
        #     shutil.rmtree(self.runner_dir)
        # except Exception as e:
        #     print(f"Failed to remove {self.runner_dir} directory")

if __name__ == "__main__":
    Runner_Watcher()