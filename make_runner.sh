#!/bin/bash
# Initialize variables
URL=""
TOKEN=""

# Parse command-line arguments
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
            echo "Unknown parameter passed: $1"
            exit 1
            ;;
    esac
done

# Check if required arguments are provided
if [[ -z "$URL" || -z "$TOKEN" ]]; then
    echo "Both --url and --token are required."
    exit 1
fi

echo "Checking For Runner Updates"

TAG_PAGE_LOCATION="https://github.com/actions/runner/tags"
TAG_PAGE=$(curl -s $TAG_PAGE_LOCATION)
ALL_VERSIONS=$(echo "$TAG_PAGE" | grep -oP 'href="\/actions\/runner\/releases\/tag\/v\K[0-9]+\.[0-9]+\.[0-9]+')
NEWEST_VERSION=$(echo "$ALL_VERSIONS" | sort -V | tail -n 1)

DOWNLOADS_DIR="downloaded_runners"
mkdir -p $DOWNLOADS_DIR

for ENTRY in $DOWNLOADS_DIR/*; do
    if [[ "$ENTRY" =~ "$NEWEST_VERSION" ]]; then
        DOWNLOAD_FILE=$ENTRY
        break
    fi
done

if [ -z "${DOWNLOAD_FILE+x}" ]; then
    echo -e "Found Updated Runner\nDeleting Old Runner"
    rm -rf $DOWNLOADS_DIR/*
    echo -e "Downloaded Updated Runner"
    NEWEST_DOWNLOAD_LOCATION="https://github.com/actions/runner/releases/download/v${NEWEST_VERSION}/actions-runner-linux-x64-${NEWEST_VERSION}.tar.gz"
    DOWNLOAD_FILE="actions-runner-linux-x64-${NEWEST_VERSION}.tar.gz"
    curl -s -o "$DOWNLOADS_DIR/$DOWNLOAD_FILE" -L "$NEWEST_DOWNLOAD_LOCATION"
else
    echo "Already have most up to date runner"
fi

echo -e "Creating Name"

REPO_NAME="${URL##*/}"
REPO_NAME="${REPO_NAME,,}"

HOSTNAME=$(hostname)

RUNNERS_DIR="runners"

INDEX=0

runner_exists() {
    local runner_name=$1
    if ls "$RUNNERS_DIR"/"$runner_name" 1> /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

while runner_exists "${REPO_NAME}_${HOSTNAME}_${INDEX}"; do
    INDEX=$((INDEX + 1))
done

RUNNER_NAME="${REPO_NAME}_${HOSTNAME}_${INDEX}"

RUNNER_DIR=$RUNNERS_DIR/$RUNNER_NAME

echo "Creating New Runner"

mkdir -p $RUNNER_DIR
tar xzf $DOWNLOADS_DIR/actions-runner-linux-x64-${NEWEST_VERSION}.tar.gz -C $RUNNER_DIR

cat <<EOF > $RUNNER_DIR/.config.input

$RUNNER_NAME
EOF
$RUNNER_DIR/config.sh --url $URL --token $TOKEN < $RUNNER_DIR/.config.input

SERVICE_NAME="${REPO_NAME}_${INDEX}"

SERVICE_FILE="
[Unit]\n
Description=GitHub Actions Self-Hosted Runner: $SERVICE_NAME\n
After=network.target\n
\n
[Service]\n
ExecStart=$(pwd)/$RUNNER_DIR/run.sh\n
WorkingDirectory=$(pwd)/$RUNNER_DIR\n
Restart=always\n
RestartSec=5\n
User=$USER\n
Environment="RUNNER_ALLOW_RUNASROOT=1"\n
\n
[Install]\n
WantedBy=multi-user.target\n
"

echo -e "$SERVICE_FILE" | sudo tee /etc/systemd/system/$SERVICE_NAME.service > /dev/null

echo "Must start system as sudo"
sudo systemctl enable $SERVICE_NAME
sudo systemctl start $SERVICE_NAME