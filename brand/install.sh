#!/usr/bin/env bash
# OxeePhone installer for Ubuntu (22.04 / 24.04).
#
#   Fresh server (the script fetches the code into /opt/oxeephone):
#     curl -fsSL https://raw.githubusercontent.com/Oxeegen/OxeePhone/main/brand/install.sh | sudo bash
#
#   From a clone:
#     sudo ./brand/install.sh             # install, or complete an existing install
#     sudo ./brand/install.sh update      # latest release (or OXEE_REF=...), rebuild, restart
#     ./brand/install.sh status
#
# It installs Docker if needed, gets the code, writes .env (secrets generated
# once, never overwritten), picks free ports (an official Dograh on the same
# host keeps its own: OxeePhone shifts to the next free ones), builds the
# images and starts the stack: UI + API + recordings behind the proxy (HTTP
# and HTTPS), its own TURN server, Postgres / Redis / MinIO local to the host.
#
# Every answer can be given ahead in the environment (non-interactive runs):
#   OXEE_DIR            install directory              (/opt/oxeephone, or this clone)
#   OXEE_REF            git tag / branch to deploy     (latest oxeephone-v* tag)
#   OXEE_SERVER_IP      address of the server for the other machines   (detected)
#   OXEE_TLS_NAMES      every name users type, comma-separated         (IP + host names)
#   OXEE_PROJECT        Docker Compose project name    (oxeephone)
#   OXEE_*_PORT, OXEE_TURN_RELAY_MIN/MAX, OXEE_DB_BIND  (see brand/README.md)
#   OXEE_SERVER_TURN_HOST=coturn  Docker Desktop / no hairpin NAT
#   OXEE_YES=1          accept the proposed values without asking
set -euo pipefail

REPO_URL="${OXEE_REPO_URL:-https://github.com/Oxeegen/OxeePhone.git}"
ACTION="${1:-install}"

c_bold=$'\e[1m'; c_dim=$'\e[2m'; c_green=$'\e[32m'; c_yellow=$'\e[33m'; c_red=$'\e[31m'; c_off=$'\e[0m'
[ -t 1 ] || { c_bold=; c_dim=; c_green=; c_yellow=; c_red=; c_off=; }
say()  { printf '%s\n' "${c_bold}==>${c_off} $*"; }
ok()   { printf '%s\n' "${c_green}✓${c_off} $*"; }
warn() { printf '%s\n' "${c_yellow}!${c_off} $*" >&2; }
die()  { printf '%s\n' "${c_red}✗ $*${c_off}" >&2; exit 1; }

# Questions go to the terminal even when the script is piped into bash.
ask() {  # ask "question" default -> echo answer
    local question="$1" default="${2:-}" answer=""
    if [ "${OXEE_YES:-0}" = "1" ] || ! { : </dev/tty; } 2>/dev/null; then
        echo "$default"; return
    fi
    printf '%s' "$question${default:+ [$default]}: " >/dev/tty
    read -r answer </dev/tty || true
    echo "${answer:-$default}"
}

need_root() {
    [ "$(id -u)" = "0" ] || die "run it with sudo: $1"
}

# --- Docker -----------------------------------------------------------------------

ensure_docker() {
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        local v; v="$(docker compose version --short 2>/dev/null | sed 's/^v//')"
        # !override / !reset in the compose overlay need Compose >= 2.24.4.
        if [ "$(printf '%s\n2.24.4\n' "$v" | sort -V | head -1)" != "2.24.4" ]; then
            die "Docker Compose $v is too old (2.24.4 or newer needed): upgrade docker-compose-plugin"
        fi
        ok "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?'), Compose $v"
        return
    fi
    need_root "Docker is not installed"
    say "Installing Docker (get.docker.com)"
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker >/dev/null 2>&1 || true
    ok "Docker installed"
}

# --- Code -------------------------------------------------------------------------

latest_tag() {
    git -C "$1" tag -l 'oxeephone-v*' --sort=-v:refname | head -1
}

ensure_code() {
    local here; here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd || true)"
    if [ -z "${OXEE_DIR:-}" ] && [ -n "$here" ] && [ -f "$here/brand/docker-compose.brand.yaml" ]; then
        OXEE_DIR="$here"
    fi
    OXEE_DIR="${OXEE_DIR:-/opt/oxeephone}"
    if [ ! -d "$OXEE_DIR/.git" ]; then
        command -v git >/dev/null 2>&1 || { need_root "git is missing"; apt-get update -qq && apt-get install -y -qq git >/dev/null; }
        say "Fetching OxeePhone into $OXEE_DIR"
        git clone --quiet --recurse-submodules "$REPO_URL" "$OXEE_DIR"
        local ref="${OXEE_REF:-$(latest_tag "$OXEE_DIR")}"
        if [ -n "$ref" ]; then
            git -C "$OXEE_DIR" checkout --quiet "$ref"
            git -C "$OXEE_DIR" submodule update --quiet --init --recursive
        fi
    fi
    cd "$OXEE_DIR"
    git submodule update --quiet --init --recursive
    ok "Code: $OXEE_DIR ($(git describe --tags --always 2>/dev/null))"
}

# --- .env ---------------------------------------------------------------------------

env_get() { [ -f .env ] && grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }

env_set_default() {  # key value: written only when the key is missing
    local key="$1" value="$2"
    if [ -z "$(env_get "$key")" ]; then
        printf '%s=%s\n' "$key" "$value" >> .env
        ADDED+=("$key")
    fi
}

secret() { head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c "${1:-32}"; }

primary_ip() {
    ip route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") { print $(i + 1); exit }}'
}

default_names() {
    local ip="$1" names="$1" n
    for n in $(hostname -I 2>/dev/null) $(hostname -f 2>/dev/null) $(hostname 2>/dev/null); do
        n="${n%.}"
        case "$n" in
            ""|127.*|::1|localhost|*:*) continue ;;                 # loopback, IPv6 (add them by hand)
            172.1[7-9].*|172.2[0-9].*|172.3[01].*) continue ;;     # Docker bridges
        esac
        case ",${names,,}," in *",${n,,},"*) ;; *) names="$names,$n" ;; esac
    done
    echo "$names"
}

# --- Free ports ----------------------------------------------------------------------

used_ports() {
    # Listening sockets of the host, plus ports published by other Compose
    # projects (an official Dograh, an older OxeePhone...), ranges expanded.
    {
        ss -Htuln 2>/dev/null | awk '{print $5}' | sed -nE 's/.*:([0-9]+)$/\1/p'
        docker ps --format '{{.Label "com.docker.compose.project"}}|{{.Ports}}' 2>/dev/null \
            | awk -F'|' -v own="$PROJECT" '$1 != own {print $2}' | tr ',' '\n' \
            | sed -nE 's/.*:([0-9]+)(-([0-9]+))?->.*/\1 \3/p' \
            | while read -r a b; do if [ -n "$b" ]; then seq "$a" "$b"; else echo "$a"; fi; done
    } | sort -un
}

is_used() { grep -qx "$1" <<<"$USED"; }

# Docker Desktop publishes ports on the host OS, out of sight of `ss`: there,
# a port is only kept once a throwaway container managed to bind it.
docker_desktop() {
    [ -z "${DOCKER_DESKTOP:-}" ] && DOCKER_DESKTOP="$(docker info --format '{{.OperatingSystem}}' 2>/dev/null | grep -qi 'docker desktop' && echo 1 || echo 0)"
    [ "$DOCKER_DESKTOP" = 1 ]
}

bindable() {  # port [ip]
    docker_desktop || return 0
    docker run --rm -p "${2:+$2:}$1:$1" --entrypoint true nginx:1.27-alpine >/dev/null 2>&1
}

pick_port() {  # key default [bind ip] -> PICKED: .env value, else given, else default or next free
    # Sets a global (no subshell) so ports handed out earlier stay taken.
    local key="$1" port="$2" ip="${3:-}" current
    current="$(env_get "$key")"
    if [ -n "$current" ]; then PICKED="$current"; TAKEN+=$'\n'"$current"; return; fi
    if [ -n "${!key:-}" ]; then PICKED="${!key}"; TAKEN+=$'\n'"$PICKED"; return; fi
    while is_used "$port" || grep -qx "$port" <<<"$TAKEN" || ! bindable "$port" "$ip"; do port=$((port + 1)); done
    TAKEN+=$'\n'"$port"
    PICKED="$port"
}

pick_relay_range() {  # 49 consecutive free UDP ports for the TURN relay
    local start="${OXEE_TURN_RELAY_MIN:-$(env_get OXEE_TURN_RELAY_MIN)}"
    if [ -n "$start" ]; then echo "$start"; return; fi
    start=49152
    while :; do
        local p clash=0
        for p in $(seq "$start" $((start + 48))); do is_used "$p" && { clash=1; break; }; done
        [ "$clash" = 0 ] && { echo "$start"; return; }
        start=$((start + 100))
    done
}

# --- Configuration -------------------------------------------------------------------

configure() {
    PROJECT="${OXEE_PROJECT:-$(env_get COMPOSE_PROJECT_NAME)}"; PROJECT="${PROJECT:-oxeephone}"
    ADDED=(); TAKEN=""
    touch .env && chmod 600 .env
    USED="$(used_ports)"

    if docker ps --format '{{.Image}}' 2>/dev/null | grep -qiE 'dograhai/|dograh-hq/'; then
        warn "An official Dograh stack runs on this host: OxeePhone takes the next free ports."
    fi

    local ip names
    ip="$(env_get TURN_HOST)"; ip="${OXEE_SERVER_IP:-${ip:-$(primary_ip)}}"
    ip="$(ask "Address of this server for the other machines" "$ip")"
    [ -n "$ip" ] || die "no server address"
    names="$(env_get OXEE_TLS_NAMES)"; names="${OXEE_TLS_NAMES:-${names:-$(default_names "$ip")}}"
    names="$(ask "Names users type to reach it (comma-separated: IPs, VPN names...)" "$names")"

    local ui https api pg redis minio minio_console turn turns tunnel relay
    pick_port OXEE_UI_PORT 3010; ui=$PICKED
    pick_port OXEE_HTTPS_PORT 3443; https=$PICKED
    pick_port OXEE_API_PORT 8000; api=$PICKED
    pick_port OXEE_POSTGRES_PORT 5432 127.0.0.1; pg=$PICKED
    pick_port OXEE_REDIS_PORT 6379 127.0.0.1; redis=$PICKED
    pick_port OXEE_MINIO_PORT 9000 127.0.0.1; minio=$PICKED
    pick_port OXEE_MINIO_CONSOLE_PORT 9001 127.0.0.1; minio_console=$PICKED
    pick_port OXEE_TURN_PORT 3478; turn=$PICKED
    pick_port OXEE_TURNS_PORT 5349; turns=$PICKED
    pick_port OXEE_TUNNEL_METRICS_PORT 2000; tunnel=$PICKED
    relay=$(pick_relay_range)

    cat <<EOF

${c_bold}OxeePhone configuration${c_off} ${c_dim}($OXEE_DIR/.env)${c_off}
  Server address      $ip
  HTTPS names         $names
  UI (http / https)   $ui / $https
  API, MCP            $api
  TURN (tcp+udp)      $turn, TLS $turns, relay $relay-$((relay + 48))/udp
  Postgres / Redis    $pg / $redis   (local to this host)
  MinIO               $minio, console $minio_console   (local to this host)
EOF
    case "$(ask "Continue? (y/n)" y)" in y|Y|yes|o|O|oui) ;; *) die "stopped, nothing changed" ;; esac

    [ "$PROJECT" != "oxeephone" ] && env_set_default COMPOSE_PROJECT_NAME "$PROJECT"
    env_set_default OSS_JWT_SECRET "$(secret 64)"
    env_set_default POSTGRES_PASSWORD "$(secret 32)"
    env_set_default REDIS_PASSWORD "$(secret 32)"
    env_set_default MINIO_ROOT_USER "oxeephone"
    env_set_default MINIO_ROOT_PASSWORD "$(secret 32)"
    env_set_default TURN_SECRET "$(secret 32)"
    env_set_default ENABLE_COTURN "true"
    env_set_default TURN_HOST "$ip"
    env_set_default OXEE_TLS_NAMES "$names"
    env_set_default OXEE_UI_PORT "$ui"
    env_set_default OXEE_HTTPS_PORT "$https"
    env_set_default OXEE_API_PORT "$api"
    env_set_default OXEE_POSTGRES_PORT "$pg"
    env_set_default OXEE_REDIS_PORT "$redis"
    env_set_default OXEE_MINIO_PORT "$minio"
    env_set_default OXEE_MINIO_CONSOLE_PORT "$minio_console"
    env_set_default OXEE_TURN_PORT "$turn"
    env_set_default OXEE_TURNS_PORT "$turns"
    env_set_default OXEE_TURN_RELAY_MIN "$relay"
    env_set_default OXEE_TURN_RELAY_MAX "$((relay + 48))"
    env_set_default OXEE_TUNNEL_METRICS_PORT "$tunnel"
    # Postgres and Redis only serve the containers: keep them off the network.
    env_set_default OXEE_DB_BIND "127.0.0.1"
    # Server-side addresses (telephony webhooks, links in notifications);
    # browsers use the name they typed, through the proxy.
    env_set_default BACKEND_API_ENDPOINT "http://$ip:$api"
    env_set_default MINIO_PUBLIC_ENDPOINT "https://$ip:$https"
    # Docker Desktop / hosts without hairpin NAT: the API reaches coturn on
    # the Docker network ("coturn"); only when asked.
    [ -n "${OXEE_SERVER_TURN_HOST:-}" ] && env_set_default OXEE_SERVER_TURN_HOST "$OXEE_SERVER_TURN_HOST"

    if [ "${#ADDED[@]}" -gt 0 ]; then ok ".env: added ${ADDED[*]}"; else ok ".env: unchanged"; fi
}

firewall_hint() {
    command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active" || return 0
    e() { env_get "$1"; }
    warn "ufw is active. Open the OxeePhone ports to your users' networks, e.g.:"
    printf '    sudo ufw allow %s/tcp && sudo ufw allow %s/tcp && sudo ufw allow %s/tcp\n' "$(e OXEE_UI_PORT)" "$(e OXEE_HTTPS_PORT)" "$(e OXEE_API_PORT)"
    printf '    sudo ufw allow %s && sudo ufw allow %s && sudo ufw allow %s:%s/udp\n' "$(e OXEE_TURN_PORT)" "$(e OXEE_TURNS_PORT)" "$(e OXEE_TURN_RELAY_MIN)" "$(e OXEE_TURN_RELAY_MAX)"
}

# --- Stack -----------------------------------------------------------------------------

compose() {
    docker compose -f docker-compose.yaml -f brand/docker-compose.brand.yaml --profile local-turn "$@"
}

start_stack() {
    say "Building the images (first time: 10 to 15 minutes)"
    compose build
    say "Starting"
    compose up -d --remove-orphans
    local api; api="$(env_get OXEE_API_PORT)"
    say "Waiting for the API (migrations run at first start)"
    for _ in $(seq 1 90); do
        if curl -fsS -m 3 "http://127.0.0.1:${api:-8000}/api/v1/health" >/dev/null 2>&1; then
            ok "API is up"; return
        fi
        sleep 4
    done
    die "the API did not answer within 6 minutes: compose logs api (see ./brand/install.sh status)"
}

summary() {
    e() { env_get "$1"; }
    local first; first="$(e OXEE_TLS_NAMES | cut -d, -f1)"
    cat <<EOF

${c_green}${c_bold}OxeePhone $(git describe --tags --always 2>/dev/null) is running.${c_off}

  Open             $(e OXEE_TLS_NAMES | tr ',' '\n' | sed "s|.*|https://&:$(e OXEE_HTTPS_PORT)|" | paste -sd' ' -)
  On this server   http://localhost:$(e OXEE_UI_PORT)
  Certificate      https://$first:$(e OXEE_HTTPS_PORT)/oxee-ca.crt  (install it once per machine, see brand/proxy/README.md)
  MCP for agents   https://$first:$(e OXEE_HTTPS_PORT)/api/v1/mcp/  or  http://$first:$(e OXEE_API_PORT)/api/v1/mcp/

  Next: create the first account on the sign-up page (then set ENABLE_SIGNUP=false
  in .env and run this script again), and fill Models with your endpoint.
EOF
    firewall_hint
}

status() {
    compose ps
    local api; api="$(env_get OXEE_API_PORT)"
    if curl -fsS -m 3 "http://127.0.0.1:${api:-8000}/api/v1/health" >/dev/null 2>&1; then ok "API healthy"; else warn "API not answering"; fi
}

update() {
    local ref="${OXEE_REF:-}"
    say "Fetching the releases"
    git fetch --quiet --tags origin
    ref="${ref:-$(latest_tag .)}"
    [ -n "$ref" ] || die "no oxeephone-v* tag found: set OXEE_REF"
    git checkout --quiet "$ref"
    git submodule update --quiet --init --recursive
    ok "Code: $ref"
}

case "$ACTION" in
    install)
        ensure_docker; ensure_code; configure; start_stack; summary ;;
    update)
        ensure_docker; ensure_code; update; OXEE_YES=1 configure; start_stack; summary ;;
    status)
        ensure_code >/dev/null; PROJECT="${OXEE_PROJECT:-oxeephone}"; status ;;
    *)
        die "usage: install.sh [install|update|status]" ;;
esac
