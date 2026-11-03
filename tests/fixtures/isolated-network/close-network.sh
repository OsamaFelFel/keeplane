#!/bin/sh
# Close the isolated kind network's outside access on the runner, keeping
# only the model provider fixture (tests/e2e/kubernetes-isolated-cases.md).
# Run as root after the install. The bridge belongs to the fixed "kind"
# Docker network the workflow creates, so the rules hold across a node
# restart.
#
#  - Nothing from the network is forwarded anywhere else: no internet, no
#    registry, no other Docker network.
#  - The runner itself answers the network only on the model port and on
#    connections the runner opened (the published ingress and API ports).
set -eu
BRIDGE=kind-isolated
MODEL_PORT=18082
ip link show "$BRIDGE" >/dev/null
iptables -I DOCKER-USER 1 -i "$BRIDGE" ! -o "$BRIDGE" -j DROP
iptables -I INPUT 1 -i "$BRIDGE" -j DROP
iptables -I INPUT 1 -i "$BRIDGE" -p tcp --dport "$MODEL_PORT" -j ACCEPT
iptables -I INPUT 1 -i "$BRIDGE" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -S DOCKER-USER
iptables -S INPUT | grep -- "$BRIDGE"
