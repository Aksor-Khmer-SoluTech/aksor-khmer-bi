# Install Aksor Khmer BI

Four steps take you from a fresh server to a signed-in portal: get Docker, install, set the address and start,
then check it. Nothing is compiled on the server. The install downloads a small kit (a script and three compose
files) and pulls the released images from Docker Hub.

| You need | |
|---|---|
| Docker | Docker Engine with the Compose v2 plugin (`docker compose`), or Docker Desktop on macOS / Windows |
| CPU | Intel/AMD (`linux/amd64`) or ARM (`linux/arm64`), Apple silicon included |
| Memory and disk | 4 GB of memory, 10 GB of free disk (the engine image carries LibreOffice and the Khmer fonts) |
| Ports | **8000** (API) and **8080** (portal) free, or others you choose in `.env` |
| Network | Access to Docker Hub and GitHub. A server without internet can install too: see [Without internet](#without-internet) |

Only the install is covered here. Running, updating, backing up and every setting are in
[Deployment](deployment.md).

---

## 1. Get Docker

Skip this step if both of these print a version:

```bash
docker --version
docker compose version
```

Install Docker from **Docker's own repository**. Avoid the distribution's `docker.io` / `podman-docker` packages
and the snap, which cause most odd networking problems.

### Ubuntu / Debian

For Debian, replace `linux/ubuntu` with `linux/debian` in both URLs.

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"      # then log out and back in, so docker works without sudo
```

### CentOS Stream / RHEL / Rocky / AlmaLinux / Fedora

For Fedora use `…/linux/fedora/docker-ce.repo`; for RHEL, `…/linux/rhel/docker-ce.repo`.

```bash
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"      # then log out and back in
```

SELinux needs nothing: every mounted folder is already labelled for it. firewalld must let containers out and
people in:

```bash
sudo firewall-cmd --permanent --zone=public --add-masquerade
sudo firewall-cmd --permanent --add-port=8080/tcp --add-port=8000/tcp
sudo firewall-cmd --reload && sudo systemctl restart docker
```

### macOS / Windows

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and give it at least 4 GB of memory
(Settings → Resources). On Windows, run the commands below in a WSL terminal.

### Check that Docker can download

Most first installs that fail, fail here. Both lines must print `ok`:

```bash
docker pull -q alpine && echo "docker hub: ok"
docker run --rm alpine wget -q -T 5 -O /dev/null http://example.com && echo "containers: ok"
```

If one fails, [Get Docker ready](deployment.md#a-get-docker-ready-ubuntu-debian-centos--rhel--rocky--alma-and-others)
has the fix for each case (IP forwarding, UFW, DNS, a proxy).

---

## 2. Install

### One line

```bash
curl -fsSL https://raw.githubusercontent.com/Aksor-Khmer-SoluTech/aksor-khmer-bi/main/install.sh | bash -s -- --no-start
```

This downloads the newest release's install kit, checks its SHA-256 checksum, unpacks it into `./aksor-khmer-bi`,
and runs `./deployment.sh init`. `init` creates the Docker network, the `data/` folders, and a `.env` file with
generated passwords. It prints the admin sign-in once:

```text
    portal login:  admin / <generated password>
```

Write the password down. It is also saved in `.env` as `PORTAL_PASSWORD`, and you choose your own at the first
sign-in.

Options, added after `--`:

| Option | Does |
|---|---|
| `1.0.0-beta.8` | installs that version instead of the newest (the list is on the [Releases page](https://github.com/Aksor-Khmer-SoluTech/aksor-khmer-bi/releases)) |
| `--dir /opt/aksor` | installs into another folder |
| `--no-start` | stops after `init` so you can set the address first (step 3). Leave it out to start straight away, which is fine for a try-out on your own computer |

### Without internet

On a machine that has internet, download the kit and its checksum from the
[Releases page](https://github.com/Aksor-Khmer-SoluTech/aksor-khmer-bi/releases), and save the images:

```bash
VERSION=1.0.0-beta.8
curl -fLO https://github.com/Aksor-Khmer-SoluTech/aksor-khmer-bi/releases/download/v$VERSION/aksor-khmer-bi-deploy-$VERSION.tar.gz
curl -fLO https://github.com/Aksor-Khmer-SoluTech/aksor-khmer-bi/releases/download/v$VERSION/aksor-khmer-bi-deploy-$VERSION.tar.gz.sha256
```

Copy both files to the server, then check and unpack them there:

```bash
sha256sum -c aksor-khmer-bi-deploy-$VERSION.tar.gz.sha256      # macOS: shasum -a 256 -c …
tar xzf aksor-khmer-bi-deploy-$VERSION.tar.gz
mv aksor-khmer-bi-deploy-$VERSION aksor-khmer-bi && cd aksor-khmer-bi
./deployment.sh init
```

The server still needs the images. Pull the ones the kit's `docker-compose.yml` names on a machine with internet,
`docker save` them into a file, copy it across and `docker load` it on the server.

---

## 3. Set the address and start

```bash
cd aksor-khmer-bi
```

People's browsers open the portal, and the portal's JavaScript calls the API from the browser. So `.env` must name
both addresses **as people's browsers reach them**. The default, `localhost`, only works in a browser on the server
itself.

For a server people reach at `192.0.2.10`, set in `.env`:

```env
CORS_ALLOWED_ORIGINS=http://192.0.2.10:8080
PORTAL_API_BASE_URL=http://192.0.2.10:8000
```

With a domain name and HTTPS in front, use those addresses instead (`https://reports.example.com`,
`https://api.reports.example.com`). See [A server with a domain name](deployment.md#variations) and
[TLS](deployment.md#tls--not-included-add-a-reverse-proxy).

If 8000 or 8080 is taken, change `API_PORT` / `PORTAL_PORT` too, and the two addresses with them. Every setting is
explained in `.env.example`.

Then start it:

```bash
./deployment.sh up
```

`up` first checks the machine (Docker, CPU, disk, ports) and the settings above, and stops with the fix if
something is wrong. Then it starts Redis and Postgres, pulls the app images, and starts the API, the scheduler, the
job worker and the portal. The database tables are created as the API starts. The first start takes a few minutes,
most of it the download.

---

## 4. Check it

```bash
./deployment.sh status                                # every service "running" or "healthy"
curl -fsS http://localhost:8000/api/v1/health && echo # the API answers
```

Open the portal (`http://<server>:8080`) and sign in as `admin` with the password from step 2. You are asked to
choose your own password straight away.

If something doesn't start, `./deployment.sh logs api` shows why. The
[Troubleshooting](deployment.md#troubleshooting) table lists the usual causes.

---

## Release information

| | |
|---|---|
| Installed version | `cat VERSION` in the install folder, or `./deployment.sh status` |
| What changed | [CHANGELOG](../CHANGELOG.md). Read it before every update |
| Downloads and checksums | [Releases page](https://github.com/Aksor-Khmer-SoluTech/aksor-khmer-bi/releases): each kit has a `.sha256` file next to it |
| Images | `aksorkhmerbi/aksor-khmer-bi-engine`, `-portal`, `-jdbc-worker` on Docker Hub. The versions are fixed in the kit's `docker-compose.yml` |
| Update | `./deployment.sh update`: backup, new kit, new images, restart. See [Running it every day](deployment.md#running-it-every-day) |

---

## Next steps

- **[Create a template](create-a-template.md)**: write a Word, Excel or HTML template and render your first
  report.
- **[Run it day to day](deployment.md#option-1--quick-deployment-deploymentsh)**: every `deployment.sh` command,
  including update, rollback, backup and restore.
- **[Put HTTPS in front](deployment.md#tls--not-included-add-a-reverse-proxy)**: a reverse proxy before you open it
  to other people.
- **[Sign-in and sessions](authentication.md)**: two-step verification, LDAP / Active Directory, API tokens.
- **[Databases and JDBC drivers](deployment.md#database-connections-and-jdbc-drivers)**: let reports read
  PostgreSQL, MySQL, Oracle, SQL Server or Db2.

Working on Aksor's own code instead? [CONTRIBUTING](../CONTRIBUTING.md) sets up a Python environment and runs the
tests without Docker.
