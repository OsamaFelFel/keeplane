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
#  - No outside name lookups. The node's resolver is Docker's embedded DNS,
#    which kind publishes on the node's gateway address and which looks names
#    up from the runner, outside the bridge rules above. Inside the node,
#    every packet to that resolver (127.0.0.11 once Docker's rules redirect
#    it) is refused, for the node itself and, through CoreDNS's forward, for
#    every pod. CoreDNS still answers cluster names itself. A systemd unit in
#    the node adds the rules again on every boot, so they hold across a
#    node restart too.
set -eu
BRIDGE=kind-isolated
MODEL_PORT=18082
NODE=keeplane-isolated-control-plane
ip link show "$BRIDGE" >/dev/null
iptables -I DOCKER-USER 1 -i "$BRIDGE" ! -o "$BRIDGE" -j DROP
iptables -I INPUT 1 -i "$BRIDGE" -j DROP
iptables -I INPUT 1 -i "$BRIDGE" -p tcp --dport "$MODEL_PORT" -j ACCEPT
iptables -I INPUT 1 -i "$BRIDGE" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -S DOCKER-USER
iptables -S INPUT | grep -- "$BRIDGE"

docker exec -i "$NODE" sh -c 'cat > /usr/local/sbin/close-outside-dns' <<'SCRIPT'
#!/bin/sh
set -eu
iptables -C INPUT -d 127.0.0.11 -p udp -j REJECT 2>/dev/null \
  || iptables -I INPUT 1 -d 127.0.0.11 -p udp -j REJECT
iptables -C INPUT -d 127.0.0.11 -p tcp -j REJECT --reject-with tcp-reset 2>/dev/null \
  || iptables -I INPUT 1 -d 127.0.0.11 -p tcp -j REJECT --reject-with tcp-reset
SCRIPT
docker exec -i "$NODE" sh -c 'cat > /etc/systemd/system/close-outside-dns.service' <<'UNIT'
[Unit]
Description=Refuse outside name lookups (isolated-network test)
Before=containerd.service kubelet.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh /usr/local/sbin/close-outside-dns

[Install]
WantedBy=multi-user.target
UNIT
docker exec "$NODE" systemctl daemon-reload
docker exec "$NODE" systemctl enable --now close-outside-dns.service
docker exec "$NODE" iptables -S INPUT | grep -- 127.0.0.11
