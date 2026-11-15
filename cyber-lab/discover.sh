#!/usr/bin/env bash
#
# discover.sh — Inventaire des appareils de VOTRE réseau local (usage privé)
# -------------------------------------------------------------------------
# À exécuter depuis une machine connectée à votre box. N'utilisez cet outil
# que sur un réseau que vous possédez ou pour lequel vous avez une autorisation.
#
#   ./discover.sh            # mode passif : interface locale + table ARP (aucun scan)
#   ./discover.sh --sweep    # balayage ping actif de votre sous-réseau /24
#   ./discover.sh --sweep --net 192.168.1   # forcer le préfixe réseau
#
# Dépend uniquement d'outils standards (ip/ifconfig, ping, arp, getent/host).
# nmap n'est pas requis mais est utilisé s'il est présent (plus précis).

set -u

SWEEP=0
NETPREFIX=""

while [ $# -gt 0 ]; do
  case "$1" in
    --sweep) SWEEP=1 ;;
    --net) shift; NETPREFIX="$1" ;;
    -h|--help)
      sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "Option inconnue : $1" >&2; exit 2 ;;
  esac
  shift
done

echo "==============================================="
echo " Inventaire réseau local — $(date '+%Y-%m-%d %H:%M:%S')"
echo "==============================================="

# --- 1. Adresse IPv4 et sous-réseau locaux -------------------------------
LOCAL_IP=""
if command -v ip >/dev/null 2>&1; then
  LOCAL_IP=$(ip -4 addr show scope global 2>/dev/null \
    | awk '/inet /{print $2}' | cut -d/ -f1 | head -n1)
elif command -v ifconfig >/dev/null 2>&1; then
  LOCAL_IP=$(ifconfig 2>/dev/null \
    | awk '/inet /{print $2}' | grep -v '127.0.0.1' | head -n1)
fi

if [ -n "$LOCAL_IP" ]; then
  echo
  echo "[*] Adresse IPv4 locale : $LOCAL_IP"
  [ -z "$NETPREFIX" ] && NETPREFIX=$(echo "$LOCAL_IP" | cut -d. -f1-3)
  echo "[*] Sous-réseau déduit  : ${NETPREFIX}.0/24"
else
  echo "[!] Impossible de déterminer l'IP locale (interface absente ?)."
fi

# --- 2. Passerelle (souvent la box) --------------------------------------
if command -v ip >/dev/null 2>&1; then
  GW=$(ip route 2>/dev/null | awk '/default/{print $3; exit}')
  [ -n "${GW:-}" ] && echo "[*] Passerelle (box)    : $GW"
fi

# --- 3. Table ARP : appareils déjà connus (passif) -----------------------
echo
echo "[*] Table ARP (appareils vus récemment) :"
if command -v ip >/dev/null 2>&1; then
  ip neigh show 2>/dev/null | awk 'NF{print "    " $0}'
elif command -v arp >/dev/null 2>&1; then
  arp -a 2>/dev/null | awk '{print "    " $0}'
else
  echo "    (ni 'ip' ni 'arp' disponibles)"
fi

# --- 4. Balayage actif (optionnel) ---------------------------------------
if [ "$SWEEP" -eq 1 ]; then
  if [ -z "$NETPREFIX" ]; then
    echo "[!] Préfixe réseau inconnu, impossible de balayer. Utilisez --net." >&2
    exit 1
  fi
  echo
  echo "[*] Balayage de ${NETPREFIX}.0/24 (hôtes actifs)..."

  if command -v nmap >/dev/null 2>&1; then
    # Découverte d'hôtes sans scan de ports.
    nmap -sn "${NETPREFIX}.0/24" | awk '/Nmap scan report/{print "    " $0}'
  else
    # Repli : ping parallèle, puis relecture de la table ARP enrichie.
    for i in $(seq 1 254); do
      ( ping -c1 -W1 "${NETPREFIX}.$i" >/dev/null 2>&1 && echo "    ${NETPREFIX}.$i  actif" ) &
      # limite le nombre de pings simultanés
      if [ $((i % 32)) -eq 0 ]; then wait; fi
    done
    wait
    echo
    echo "[*] Résolution des noms (si disponible) :"
    for ip in $(ip neigh show 2>/dev/null | awk '/REACHABLE|STALE|DELAY/{print $1}'); do
      name=""
      if command -v getent >/dev/null 2>&1; then
        name=$(getent hosts "$ip" 2>/dev/null | awk '{print $2}')
      elif command -v host >/dev/null 2>&1; then
        name=$(host "$ip" 2>/dev/null | awk '/pointer/{print $5}')
      fi
      echo "    ${ip}  ${name:-(nom inconnu)}"
    done
  fi
fi

echo
echo "[i] Pour identifier une machine précise : relevez son adresse MAC"
echo "    (Windows: ipconfig /all — Linux/macOS: ip addr) et croisez-la"
echo "    avec cette liste, ou consultez la page d'admin de la box."
