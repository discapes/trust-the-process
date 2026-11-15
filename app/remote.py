"""Run the build and test scripts in ../checks on the Verda instance (repo at /root/mp) and fetch their results."""
import shlex
import subprocess
from pathlib import Path

HOST = "root@95.216.229.243"  # the build host prepared by checks/setup_instance.sh
SSH = ["ssh", "-i", str(Path.home() / ".ssh/verda_junction"), "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
       "-o", "LogLevel=ERROR", "-o", "ServerAliveInterval=60"]
RESULTS = Path.home() / "junction-data/earned-trust/results"
CHECKS = Path(__file__).parent.parent / "checks"


def run(cmd, timeout=3600):
    """Run a shell command on the instance; returns (exit code, combined output)."""
    r = subprocess.run([*SSH, HOST, cmd], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def put(local_or_text, remote_path, text=False):
    data = local_or_text if text else Path(local_or_text).read_text()
    subprocess.run([*SSH, HOST, f"mkdir -p {shlex.quote(str(Path(remote_path).parent))} && cat > {shlex.quote(remote_path)}"],
                   input=data, text=True, check=True)


def sync_scripts():
    for f in CHECKS.glob("*.sh"):
        put(f, f"/root/{f.name}")
    run("chmod +x /root/*.sh")


def fetch(name):
    """Copy /root/results/<name>/ here; returns the local directory."""
    dest = RESULTS / name
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["rsync", "-az", "--delete", "-e", " ".join(SSH), f"{HOST}:/root/results/{name}/", f"{dest}/"], check=True)
    return dest


def has(name):
    return (RESULTS / name / "test.log").exists() or run(f"test -f /root/results/{name}/test.log")[0] == 0


def push(ref):
    """Make a local ref of the clone (e.g. a benchmark variant) available in the instance's repo under the same name."""
    import partition
    subprocess.run(["git", "-C", partition.REPO, "push", "-q", "-f", f"ssh://{HOST}/root/mp", f"{ref}:refs/heads/{ref}"],
                   env={"GIT_SSH_COMMAND": " ".join(SSH), "PATH": "/usr/bin:/bin"}, check=True, capture_output=True)
