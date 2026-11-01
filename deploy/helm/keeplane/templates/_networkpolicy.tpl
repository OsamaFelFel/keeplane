{{- /*
Shared pieces of the opt-in NetworkPolicies. A destination is either
{cidr, ports} or {namespaceSelector, podSelector, ports}; selectors are label
maps rendered as matchLabels. A podSelector without a namespaceSelector means
pods in the release namespace.
*/ -}}

{{- /* One peer (the item under to: or from:). Arguments: list <setting> <entry>. */ -}}
{{- define "keeplane.networkPolicy.peer" -}}
{{- $where := index . 0 }}
{{- $entry := index . 1 }}
{{- if not (kindIs "map" $entry) }}
{{- fail (printf "%s: each entry needs a cidr, or a namespaceSelector and/or podSelector" $where) }}
{{- end }}
{{- $selected := or $entry.namespaceSelector $entry.podSelector }}
{{- if and $entry.cidr $selected }}
{{- fail (printf "%s: use either cidr or namespaceSelector/podSelector in one entry, not both" $where) }}
{{- end }}
{{- $peer := dict }}
{{- if $entry.cidr }}
{{- $_ := set $peer "ipBlock" (dict "cidr" (toString $entry.cidr)) }}
{{- end }}
{{- with $entry.namespaceSelector }}
{{- $_ := set $peer "namespaceSelector" (dict "matchLabels" .) }}
{{- end }}
{{- with $entry.podSelector }}
{{- $_ := set $peer "podSelector" (dict "matchLabels" .) }}
{{- end }}
{{- if $peer }}
{{- list $peer | toYaml }}
{{- else }}
{{- fail (printf "%s: each entry needs a cidr, or a non-empty namespaceSelector or podSelector; an empty selector would match everything" $where) }}
{{- end }}
{{- end }}

{{- /* One egress rule per destination, TCP only. Arguments: list <setting> <entries>. */ -}}
{{- define "keeplane.networkPolicy.egressRules" -}}
{{- $where := index . 0 }}
{{- range $entry := index . 1 }}
{{- if not (and (kindIs "map" $entry) $entry.ports) }}
{{- fail (printf "%s: each entry needs ports, such as ports: [443]" $where) }}
{{- end }}
- to:
    {{- include "keeplane.networkPolicy.peer" (list $where $entry) | nindent 4 }}
  ports:
    {{- range $port := $entry.ports }}
    - protocol: TCP
      port: {{ int $port }}
    {{- end }}
{{- end }}
{{- end }}

{{- /* Cluster DNS on UDP and TCP 53. */ -}}
{{- define "keeplane.networkPolicy.dnsRule" -}}
- to:
    {{- include "keeplane.networkPolicy.peer" (list "networkPolicy.dns" .Values.networkPolicy.dns) | nindent 4 }}
  ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
{{- end }}

{{- /* The managed gateway copies, as the gateway Service and NetworkPolicy select them. */ -}}
{{- define "keeplane.networkPolicy.gatewayPods" -}}
app.kubernetes.io/name: agentgateway-standalone
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- /*
Refuse settings that would leave a policy half-open or point at objects the
chart does not install. Included once, from app-networkpolicy.yaml.
*/ -}}
{{- define "keeplane.networkPolicy.validate" -}}
{{- $np := .Values.networkPolicy }}
{{- $egress := $np.egress }}
{{- $managed := eq .Values.gateway.mode "managed" }}
{{- if $np.appIngressEnabled }}
{{- if not (or $np.publicEntry.namespaceSelector $np.publicEntry.podSelector) }}
{{- fail "networkPolicy.appIngressEnabled needs networkPolicy.publicEntry.namespaceSelector or podSelector: the labels of your ingress controller's namespace or pods" }}
{{- end }}
{{- if ne .Values.app.service.type "ClusterIP" }}
{{- fail "networkPolicy.appIngressEnabled requires app.service.type=ClusterIP: the policy admits only the public entry, so a NodePort or LoadBalancer Service would not answer" }}
{{- end }}
{{- end }}
{{- if and (not $managed) $egress.gatewayDatabase }}
{{- fail "networkPolicy.egress.gatewayDatabase belongs to managed mode; the chart creates no policy for a gateway it does not install" }}
{{- end }}
{{- if and $managed $egress.gatewayDatabase (ne (index .Values "agentgateway-standalone").mode "database") }}
{{- fail "networkPolicy.egress.gatewayDatabase needs agentgateway-standalone.mode=database; a read-only gateway has no database" }}
{{- end }}
{{- if and $managed $egress.suppliedGateway }}
{{- fail "networkPolicy.egress.suppliedGateway belongs to existing mode; in managed mode the app reaches the gateway copies the chart installs" }}
{{- end }}
{{- if and (not .Values.app.postgres.enabled) $egress.postgres }}
{{- fail "networkPolicy.egress.postgres is set but app.postgres.enabled is false" }}
{{- end }}
{{- if $np.egressEnabled }}
{{- if not $egress.modelEndpoints }}
{{- fail "networkPolicy.egressEnabled needs networkPolicy.egress.modelEndpoints: list the model provider and runner endpoints the gateway and the app's provider-key checks may reach" }}
{{- end }}
{{- if and .Values.app.postgres.enabled (not $egress.postgres) }}
{{- fail "networkPolicy.egressEnabled with app.postgres needs networkPolicy.egress.postgres: the address of app.postgres.host and its port" }}
{{- end }}
{{- if and $managed (eq (index .Values "agentgateway-standalone").mode "database") (not $egress.gatewayDatabase) }}
{{- fail "networkPolicy.egressEnabled with the managed gateway in database mode needs networkPolicy.egress.gatewayDatabase: the gateway database address and port" }}
{{- end }}
{{- if and (not $managed) (not $egress.suppliedGateway) }}
{{- fail "networkPolicy.egressEnabled in existing mode needs networkPolicy.egress.suppliedGateway: the address of gateway.url and of every gateway.copyUrls entry" }}
{{- end }}
{{- end }}
{{- end }}
