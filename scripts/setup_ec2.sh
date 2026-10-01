#!/usr/bin/env bash
# One-time EC2 host preparation (Amazon Linux 2023). Run as ec2-user with sudo.
set -euo pipefail
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
command -v aws >/dev/null || sudo dnf install -y awscli
echo "Re-login so the docker group applies. Then attach an IAM instance profile (see docs/aws-deployment.md)."
