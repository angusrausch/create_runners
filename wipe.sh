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

print_question() {
    echo -e "${BLUE}$1${NC}"
}

print_process() {
    echo -e "${CYAN} $1${NC}"
}

print_question "This will remove all runners present on this systm and clear the runners dir\nThis will not remove the runner from GitHub\nAre you sure you wish to proceed? (yN)"
read CONFIRMATION
if [ "$CONFIRMATION" == "y" ]; then
    print_step "Finding GitHub Actions runner services..."

    # Get list of matching service names
    services=$(systemctl list-units --type=service --no-legend | grep 'actions.runner' | awk '{print $1}')

    if [[ -z "$services" ]]; then
        print_success "No matching services found."
    else
        print_step "Removing from systemd..."

        for service in $services; do
            print_process "Removing $service..."
            sudo systemctl stop "$service" || true
            sudo systemctl disable "$service" || true
            sudo rm -f "/etc/systemd/system/$service"
        done

        print_step "Reloading systemd..."
        sudo systemctl daemon-reload
    fi

    print_step "Purging ./runners dir"

    rm -rf ./runners/* > /dev/null 2>&1

    print_success "Done."
    exit 0
else
    print_error "Cancelling task"
    exit 0
fi