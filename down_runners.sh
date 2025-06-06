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
    echo -e "${CYAN}This script removes GitHub Actions self-hosted runners for the specified repository.${NC}"
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


user_id=`id -u`
if [ $user_id -ne 0 ]; then
    print_error "Must run as sudo"
    exit 1
fi

# -----------------------
# Parse Arguments
# -----------------------
URL=""
TOKEN=""
RUNNER_AMOUNT=""

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
        --runners)
            RUNNER_AMOUNT="$2"
            shift 2
            ;;
        *)
            print_error "Unknown parameter passed: $1"
            exit 1
            ;;
    esac
done

if [[ -z "$URL" || -z "$TOKEN" || -z "$RUNNER_AMOUNT" ]]; then
    print_error "--url, --token and --runners are required."
    exit 1
fi

# -----------------------
# Remove Runners
# -----------------------
REPO_NAME="${URL##*/}"
REPO_NAME="${REPO_NAME,,}"
RUNNERS_DIR="$(pwd)/runners"


mapfile -t ALL_RUNNERS < <(find "$RUNNERS_DIR" -maxdepth 1 -type d -printf "%f\n" | grep "$REPO_NAME")
length=${#ALL_RUNNERS[@]}

for (( i=$length-1; i>=RUNNER_AMOUNT; i-- )); do
    echo "i"
    runner=${ALL_RUNNERS[i]}
    print_step "Removing $runner..."

    pushd "$RUNNERS_DIR/$runner" > /dev/null
    ./svc.sh stop > /dev/null 2>&1
    ./svc.sh uninstall > /dev/null 2>&1
    sudo -u $SUDO_USER ./config.sh remove --token $TOKEN > /dev/null
    popd > /dev/null

    rm -rf "$RUNNERS_DIR/$runner"
    print_success "Removed $runner"
done

print_success "Reduced $REPO_NAME runners to $RUNNER_AMOUNT"