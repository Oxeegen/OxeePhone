#!/bin/sh
# OxeePhone proxy: HTTPS certificate for every name of the server.
#
# Run by the nginx image before it starts (/docker-entrypoint.d). Unless
# OXEE_TLS_CUSTOM=true (your own server.crt / server.key mounted in
# /etc/nginx/oxee-certs), keeps a local certificate authority (ca.crt, served
# at /oxee-ca.crt) and a server certificate for localhost, 127.0.0.1 and the
# names in OXEE_TLS_NAMES (comma-separated: LAN IP, VPN hostname...). The
# server certificate is made again when that list changes.
set -e
DIR=/etc/nginx/oxee-certs
NAMES="localhost,127.0.0.1${OXEE_TLS_NAMES:+,$OXEE_TLS_NAMES}"

if [ "$OXEE_TLS_CUSTOM" = "true" ]; then
    echo "oxee-cert: using the provided certificate"
    exit 0
fi
mkdir -p "$DIR"
if [ -f "$DIR/server.crt" ] && [ "$(cat "$DIR/names" 2>/dev/null)" = "$NAMES" ]; then
    echo "oxee-cert: certificate up to date for $NAMES"
    exit 0
fi
command -v openssl >/dev/null 2>&1 || apk add --no-cache openssl >/dev/null

if [ ! -f "$DIR/ca.key" ]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
        -subj "/CN=OxeePhone local CA" \
        -keyout "$DIR/ca.key" -out "$DIR/ca.crt" 2>/dev/null
fi

SAN=""
for name in $(echo "$NAMES" | tr ',' ' '); do
    case "$name" in
        *:*|*[!0-9.]*) case "$name" in *:*) SAN="$SAN,IP:$name" ;; *) SAN="$SAN,DNS:$name" ;; esac ;;
        *) SAN="$SAN,IP:$name" ;;
    esac
done
printf "subjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n" "${SAN#,}" > "$DIR/ext.cnf"
openssl req -newkey rsa:2048 -nodes -subj "/CN=OxeePhone" \
    -keyout "$DIR/server.key" -out "$DIR/server.csr" 2>/dev/null
openssl x509 -req -in "$DIR/server.csr" -CA "$DIR/ca.crt" -CAkey "$DIR/ca.key" \
    -CAcreateserial -days 825 -extfile "$DIR/ext.cnf" -out "$DIR/server.crt" 2>/dev/null
rm -f "$DIR/server.csr"
echo "$NAMES" > "$DIR/names"
echo "oxee-cert: certificate made for $NAMES (${SAN#,})"
