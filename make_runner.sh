#!/bin/bash

# -----------------------
# Define Colors and Helpers
# -----------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

print_step() {
    echo -e "${YELLOW}==> $1${NC}"
}

print_success() {
    echo -e "${GREEN}✔ $1${NC}"
}

print_error() {
    echo -e "${RED}✖ $1${NC}"
}

# -----------------------
# Show Help
# -----------------------
if [[ "$1" == "--help" || "$1" == "-h" ]]; then
    echo -e "${CYAN}Usage: $0 --url <REPO_URL> --token <REGISTRATION_TOKEN>${NC}"
    echo -e "${CYAN}This script sets up a GitHub Actions self-hosted runner for the specified repository.${NC}"
    exit 0
fi

# -----------------------
# Validate Dependencies
# -----------------------
REQUIRED_TOOLS=(curl tar sudo)

for tool in "${REQUIRED_TOOLS[@]}"; do
    if ! command -v "$tool" > /dev/null 2>&1; then
        print_error "Required tool '$tool' is not installed."
        exit 1
    fi
done

# -----------------------
# Parse Arguments
# -----------------------
URL=""
TOKEN=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --url)
            URL="$2"
            shift 2
            ;;
        --token)
            TOKEN="$2"
            shift 2
            ;;
        *)
            print_error "Unknown parameter passed: $1"
            exit 1
            ;;
    esac
done

if [[ -z "$URL" || -z "$TOKEN" ]]; then
    print_error "Both --url and --token are required."
    exit 1
fi

# -----------------------
# Get Arch Version
# -----------------------
if [ "$(arch)" == "x86_64" ]; then 
    ARCH="x64"
elif [ "$(arch)" == "aarch64" ]; then
    ARCH="arm64"
else
    print_error "Unkown ARCH type: $(arch)"
    exit 1
fi

# -----------------------
# Get Latest Runner
# -----------------------
print_step "Checking for Runner Updates..."

TAG_PAGE_LOCATION="https://github.com/actions/runner/tags"
TAG_PAGE=$(curl -s $TAG_PAGE_LOCATION)
if [[ $? -ne 0 ]]; then
    print_error "Failed to find tags."
    exit 1
fi
ALL_VERSIONS=$(echo "$TAG_PAGE" | grep -oP 'href="\/actions\/runner\/releases\/tag\/v\K[0-9]+\.[0-9]+\.[0-9]+')
NEWEST_VERSION=$(echo "$ALL_VERSIONS" | sort -V | tail -n 1)

DOWNLOADS_DIR="downloaded_runners"
mkdir -p "$DOWNLOADS_DIR"

for ENTRY in "$DOWNLOADS_DIR"/*; do
    if [[ "$ENTRY" =~ "$NEWEST_VERSION" ]]; then
        DOWNLOAD_FILE=$ENTRY
        break
    fi
done

FILENAME="actions-runner-linux-${ARCH}-${NEWEST_VERSION}.tar.gz"
if [ -z "${DOWNLOAD_FILE+x}" ]; then
    print_step "Found Updated Runner. Deleting old runner..."
    rm -rf "$DOWNLOADS_DIR"/*
    print_step "Downloading Updated Runner..."
    NEWEST_DOWNLOAD_LOCATION="https://github.com/actions/runner/releases/download/v${NEWEST_VERSION}/${FILENAME}"
    curl -o "$DOWNLOADS_DIR/$FILENAME" -L "$NEWEST_DOWNLOAD_LOCATION"
    if [[ $? -ne 0 ]]; then
        print_error "Failed to download runner."
        exit 1
    fi
    print_success "Latest Runner Downloaded"
else
    print_success "Runner up to date"
fi

# -----------------------
# Create Runner
# -----------------------
REPO_NAME="${URL##*/}"
REPO_NAME="${REPO_NAME,,}"
INDEX=0
RUNNERS_DIR="runners"

runner_exists() {
    local runner_name=$1
    if ls "$RUNNERS_DIR"/"$runner_name" 1> /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

while runner_exists "${REPO_NAME}_$(hostname)_${INDEX}"; do
    INDEX=$((INDEX + 1))
done

RUNNER_NAME="${REPO_NAME}_$(hostname)_${INDEX}"
RUNNER_DIR=$RUNNERS_DIR/$RUNNER_NAME

print_step "Creating Runner at $RUNNER_DIR"
mkdir -p "$RUNNER_DIR"
tar xzf "$DOWNLOADS_DIR/$FILENAME" -C "$RUNNER_DIR"
if [[ $? -ne 0 ]]; then
    print_error "Failed to build runner."
    exit 1
fi

cat <<EOF > "$RUNNER_DIR/.config.input"

$RUNNER_NAME
EOF

echo -e "${CYAN}"
"$RUNNER_DIR/config.sh" --url "$URL" --token "$TOKEN" < "$RUNNER_DIR/.config.input"
if [[ $? -ne 0 ]]; then
    print_error "Runner configuration failed."
    exit 1
fi

print_success "Runner Created"

# -----------------------
# Setup Systemd Service
# -----------------------
print_step "Creating Service for Runner..."

SERVICE_NAME="${REPO_NAME}_${INDEX}"
SERVICE_FILE_PATH="/etc/systemd/system/$SERVICE_NAME.service"

sudo tee "$SERVICE_FILE_PATH" > /dev/null <<EOF
[Unit]
Description=GitHub Actions Self-Hosted Runner: $SERVICE_NAME
After=network.target

[Service]
ExecStart=$(pwd)/$RUNNER_DIR/run.sh
WorkingDirectory=$(pwd)/$RUNNER_DIR
Restart=always
RestartSec=5
User=$USER
Environment=RUNNER_ALLOW_RUNASROOT=1

[Install]
WantedBy=multi-user.target
EOF

print_step "Reloading systemd..."
sudo systemctl daemon-reload

read -rp "Do you want to enable and start the runner service now? [y/N] " CONFIRM
if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
    sudo systemctl enable "$SERVICE_NAME" &> /dev/null
    sudo systemctl start "$SERVICE_NAME" &> /dev/null
    print_success "Service $SERVICE_NAME started and enabled"
else
    print_step "Service not started"
fi

print_success "Runner Built and Activated"
