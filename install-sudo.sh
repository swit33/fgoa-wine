#!/bin/bash
# fgoa-wine — the root-only part of the install.
#
# Everything else this project does runs as your own user: install.sh, the launcher, the scripts in
# scripts/. These are the only three things that need root, and they are in their own file so it is
# obvious what they are before you hand over a password:
#
#   1. net.ipv4.ip_unprivileged_port_start = 777
#      The platform's ALL.Net server listens on 777, and ports below 1024 are privileged on Linux.
#      Persisted in /etc/sysctl.d/99-fgoa-ports.conf (777, not 0: only that one port is needed).
#
#   2. 192.168.100.1/24 and 192.168.100.11/24 on lo
#      The platform's own network plan (App/FGO_LocalNetwork.ps1) puts the title server at
#      192.168.100.1 on the cabinet subnet. On Windows the platform creates that network itself; in
#      a Wine prefix nothing does. Without it the platform probe at boot follows whatever route the
#      host has for that address - on the machine this was built for, a VPN - and the game can come
#      up as a sub cabinet and stop at ERROR 8404. `ip addr add` does not survive a reboot.
#
#   3. /etc/systemd/system/fgoa-cabinet-net.service
#      Adds those two addresses again at every boot (#2 with memory).
#
# Usage:
#   sudo ./install-sudo.sh                        # 1 + 2 + 3, idempotent
#   sudo ./install-sudo.sh --no-ports             # skip the sysctl
#   sudo ./install-sudo.sh --no-cabinet-net       # skip the addresses and the unit
#   sudo ./install-sudo.sh --remove               # take the persistent parts back out
#
# install.sh never calls this for you: run it once, yourself, and it prints exactly what it changed.
set -u

DO_PORTS=1; DO_CABINET_NET=1; DO_REMOVE=0
UNIT=/etc/systemd/system/fgoa-cabinet-net.service
SYSCTL_FILE=/etc/sysctl.d/99-fgoa-ports.conf
ADDR1=192.168.100.1/24; ADDR2=192.168.100.11/24

while [ $# -gt 0 ]; do
    case "$1" in
        --no-ports)        DO_PORTS=0; shift ;;
        --no-cabinet-net)  DO_CABINET_NET=0; shift ;;
        --remove)          DO_REMOVE=1; shift ;;
        -h|--help)         awk 'NR>1 && /^set -u/{exit} NR>1{print}' "$0" | sed 's/^# \{0,1\}//' ; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

say()  { printf '%s\n' "$*"; }
step() { printf '\n=== %s\n' "$*"; }
warn() { printf '! %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run this with sudo: it is the script that changes system files (see the header for the list)"

if [ "$DO_REMOVE" = 1 ]; then
    step "removing what this script installed"
    for a in "$ADDR1" "$ADDR2"; do
        if ip -4 addr show lo | grep -q "${a%%/*}/"; then
            ip addr del "$a" dev lo && say "address $a removed from lo"
        fi
    done
    if [ -f "$UNIT" ]; then
        systemctl disable --now fgoa-cabinet-net.service >/dev/null 2>&1 || true
        rm -f "$UNIT" && systemctl daemon-reload
        say "$UNIT removed"
    fi
    if [ -f "$SYSCTL_FILE" ]; then
        rm -f "$SYSCTL_FILE" && sysctl -w net.ipv4.ip_unprivileged_port_start=1024 >/dev/null
        say "$SYSCTL_FILE removed, privileged port floor back to 1024"
    fi
    say "the Wine prefix, the game folder and the saves are untouched (that is uninstall.sh)"
    exit 0
fi

if [ "$DO_PORTS" = 1 ]; then
    step "port 777 for the ALL.Net server"
    local_floor=$(sysctl -n net.ipv4.ip_unprivileged_port_start 2>/dev/null || echo 1024)
    if [ "$local_floor" -le 777 ]; then
        say "already allowed (ip_unprivileged_port_start = $local_floor)"
    else
        sysctl -w net.ipv4.ip_unprivileged_port_start=777 >/dev/null \
            && say "now: net.ipv4.ip_unprivileged_port_start = 777"
    fi
    printf '# FGO Arcade: the ALL.Net server needs port 777.\nnet.ipv4.ip_unprivileged_port_start = 777\n' > "$SYSCTL_FILE" \
        && say "kept across reboots in $SYSCTL_FILE"
fi

if [ "$DO_CABINET_NET" = 1 ]; then
    step "cabinet network addresses on lo"
    missing=""
    ip -4 addr show lo | grep -q "${ADDR1%%/*}/"  || missing="$missing $ADDR1"
    ip -4 addr show lo | grep -q "${ADDR2%%/*}/" || missing="$missing $ADDR2"
    if [ -z "$missing" ]; then
        say "already there: $ADDR1 $ADDR2"
    else
        for a in $missing; do
            ip addr add "$a" dev lo && say "added $a to lo"
        done
    fi
    # `ip addr add` is gone after a reboot, so keep a unit that repeats it.
    cat > "$UNIT" <<'EOF'
# FGO Arcade: the cabinet virtual network, which the platform probe expects.
# Written by fgoa-wine's install-sudo.sh; `install-sudo.sh --remove` deletes it again.
[Unit]
Description=FGO Arcade cabinet network addresses on lo
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/ip addr add 192.168.100.1/24 dev lo
ExecStart=-/usr/bin/ip addr add 192.168.100.11/24 dev lo

[Install]
WantedBy=multi-user.target
EOF
    systemctl enable --now fgoa-cabinet-net.service >/dev/null 2>&1 \
        && say "kept across reboots by $UNIT (enabled, started)" \
        || warn "could not enable the unit; add the addresses by hand after each reboot"
fi

step "check"
ip -4 addr show lo | grep -E "$ADDR1|$ADDR2" | sed 's/^/  /' | sed 's/  */ /g' || true
printf '  %s\n' "ip_unprivileged_port_start = $(sysctl -n net.ipv4.ip_unprivileged_port_start 2>/dev/null)"
printf '\nDone. Nothing else in this project needs root: ./install.sh --verify reports both of these too.\n'
