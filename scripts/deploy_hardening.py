#!/usr/bin/env python3
"""
deploy_hardening.py — Automation script for OS-level Hardening on Server A (Gateway).
Configures UFW, Fail2ban, Chrony NTP, and Docker daemon log rotation.
"""

import os
import subprocess
import sys

# SSH configuration parameters for Server A
SERVER_A_IP = "100.92.13.100"
SERVER_A_USER = "botuser"
SERVER_A_KEY = os.path.expanduser("~/.ssh/pk/sshkey-serverc.pem")


def run_ssh_command(ip, user, key_path, cmd):
    """Run ssh command and return output."""
    ssh_cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "StrictHostKeyChecking=no",
        "-i",
        key_path,
        f"{user}@{ip}",
        cmd,
    ]
    print(f"\n[SSH EXEC] {user}@{ip}: {cmd[:80]}...")
    res = subprocess.run(
        ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    return res.returncode, res.stdout, res.stderr


def harden_server_a():
    """Harden Server A (Debian 12 Gateway)."""
    print("=======================================================")
    print("           HARDENING SERVER A (GATEWAY)                ")
    print("=======================================================")

    commands = [
        # 1. Update package list
        "sudo apt-get update",
        # 2. NTP Time Sync (Chrony)
        "sudo apt-get install -y chrony",
        """sudo tee /etc/chrony/chrony.conf << 'EOF'
server 0.pool.ntp.org iburst
server 1.pool.ntp.org iburst
server time.google.com iburst prefer
server time.cloudflare.com iburst
makestep 1.0 3
driftfile /var/lib/chrony/chrony.drift
logdir /var/log/chrony
log tracking measurements statistics
maxdistance 0.1
EOF""",
        "sudo systemctl enable --now chrony || sudo systemctl enable --now chronyd",
        "sudo systemctl restart chrony || sudo systemctl restart chronyd",
        # 3. Fail2ban setup
        "sudo apt-get install -y fail2ban",
        """sudo tee /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 3

[sshd]
enabled = true
port    = ssh
filter  = sshd
logpath = /var/log/auth.log
EOF""",
        "sudo systemctl enable --now fail2ban",
        "sudo systemctl restart fail2ban",
        # 4. Docker CE install & configuration
        """if ! command -v docker &> /dev/null; then
            sudo apt-get install -y ca-certificates curl gnupg
            sudo install -m 0755 -d /etc/apt/keyrings
            curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
            sudo chmod a+r /etc/apt/keyrings/docker.gpg
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
            sudo apt-get update
            sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
        fi""",
        """sudo mkdir -p /etc/docker && sudo tee /etc/docker/daemon.json << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "storage-driver": "overlay2"
}
EOF""",
        "sudo systemctl enable docker",
        "sudo systemctl restart docker",
        # 5. UFW Firewall setup (Strict rules)
        "sudo apt-get install -y ufw",
        "sudo ufw default deny incoming",
        "sudo ufw default allow outgoing",
        "sudo ufw allow 22/tcp",
        "sudo ufw allow in on tailscale0",
        "echo 'y' | sudo ufw enable",
        "sudo systemctl enable --now ufw",
        "sudo systemctl restart ufw",
    ]

    for cmd in commands:
        code, out, err = run_ssh_command(SERVER_A_IP, SERVER_A_USER, SERVER_A_KEY, cmd)
        if code != 0:
            print(
                f"[ERROR] Command failed with code {code}.\nStderr: {err}\nStdout: {out}"
            )
            return False
        else:
            print(f"[SUCCESS] Command output:\n{out.strip()}")

    print("\n[OK] Server A hardening completed successfully!")
    return True


def main():
    success = harden_server_a()
    if success:
        print("\n=======================================================")
        print("SUCCESS: SERVER A HARDENED SUCCESSFULLY!")
        print("=======================================================")
        sys.exit(0)
    else:
        print("\nFAILURE: Hardening failed on Server A.")
        sys.exit(1)


if __name__ == "__main__":
    main()
