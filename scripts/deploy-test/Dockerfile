# A bare Ubuntu 26.04 box with Docker Engine + Compose from Docker's official apt repo, for trying
# ./deployment.sh by hand.
#   docker compose -f scripts/deploy-test/docker-compose.yml up -d --build
#   docker compose -f scripts/deploy-test/docker-compose.yml exec ubuntu bash
# See docker-compose.yml for what the mounts and --privileged are for.
FROM ubuntu:26.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git gnupg iptables iproute2 procps python3 sudo \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
    && . /etc/os-release \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
         > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends \
         docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
CMD ["bash"]
