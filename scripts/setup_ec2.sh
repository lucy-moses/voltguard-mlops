#!/usr/bin/env bash
# One-time EC2 host preparation (Ubuntu). Run as the EC2 login user with sudo.
set -euo pipefail
sudo apt-get update
sudo apt-get install -y docker.io awscli
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
echo "Re-login so the docker group applies. Attach the VoltGuardEC2S3Role instance profile (see docs/aws-deployment.md)."
