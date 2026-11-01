{{- /*
Every managed gateway copy's own private address, one per gateway.copies,
from the StatefulSet and headless Service in gateway-copies.yaml.
*/ -}}
{{- define "keeplane.gatewayCopyUrls" -}}
{{- $urls := list }}
{{- range $index := until (int .Values.gateway.copies) }}
{{- $urls = append $urls (printf "http://%s-gateway-%d.%s-gateway-copies.%s.svc:4000" $.Release.Name $index $.Release.Name $.Release.Namespace) }}
{{- end }}
{{- join "," $urls }}
{{- end }}

{{/* The customer-run gateway's CA (existing mode only), for the app and preflight Job. */}}
{{- define "keeplane.gatewayCa.check" -}}
{{- if and .Values.gateway.caSecret (ne .Values.gateway.mode "existing") -}}
{{- fail "gateway.caSecret applies only to gateway.mode=existing; the app reaches the managed gateway copies over plain HTTP inside the cluster" -}}
{{- end -}}
{{- end -}}

{{- define "keeplane.gatewayCa.env" -}}
{{- if .Values.gateway.caSecret }}
- name: KEEPLANE_GATEWAY_CA_FILE
  value: /run/keeplane-gateway-ca/ca.crt
{{- end }}
{{- end -}}

{{- define "keeplane.gatewayCa.mount" -}}
{{- if .Values.gateway.caSecret }}
- name: gateway-ca
  mountPath: /run/keeplane-gateway-ca
  readOnly: true
{{- end }}
{{- end -}}

{{- define "keeplane.gatewayCa.volume" -}}
{{- if .Values.gateway.caSecret }}
- name: gateway-ca
  secret:
    secretName: {{ .Values.gateway.caSecret | quote }}
    defaultMode: 0440
    items:
      - key: ca.crt
        path: ca.crt
{{- end }}
{{- end -}}

{{- /*
agentgateway-standalone.extraVolumes as the managed gateway copies mount them,
given the agentgateway-standalone values. A Secret volume, or a projected
volume with a Secret source, gets defaultMode 0440 when it sets none, as every
Secret Keeplane mounts itself; a looser mode is refused. Kubernetes makes the
files owned by root with the pod's fsGroup as their group, so the non-root
gateway user can read them only through fsGroup, and Helm refuses a Secret
volume without one. app.yaml already refuses a gateway fsGroup with
app.postgres or app.localTrial, so those installs use secretKeyRef.
*/ -}}
{{- define "keeplane.gatewayExtraVolumes" -}}
{{- $fsGroup := index (.podSecurityContext | default dict) "fsGroup" -}}
{{- $volumes := list -}}
{{- range $index, $original := (.extraVolumes | default list) -}}
{{- $volume := deepCopy $original -}}
{{- $where := printf "agentgateway-standalone.extraVolumes[%d] (%s)" $index ($volume.name | default "unnamed") -}}
{{- $holder := dict -}}
{{- $secrets := list -}}
{{- if hasKey $volume "secret" -}}
{{- $holder = $volume.secret | default dict -}}
{{- $_ := set $volume "secret" $holder -}}
{{- $secrets = list $holder -}}
{{- else if hasKey $volume "projected" -}}
{{- $holder = $volume.projected | default dict -}}
{{- $_ := set $volume "projected" $holder -}}
{{- range ($holder.sources | default list) -}}
{{- if and (kindIs "map" .) (hasKey . "secret") -}}
{{- $secrets = append $secrets (.secret | default dict) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- if $secrets -}}
{{- if or (kindIs "invalid" $fsGroup) (not $fsGroup) -}}
{{- fail (printf "%s mounts a Secret into the managed gateway copies, but agentgateway-standalone.podSecurityContext.fsGroup is unset. Its files would be owned by root, so the non-root gateway could read them only if every user in the pod could. Give the gateway this value through an agentgateway-standalone.extraEnv entry with valueFrom.secretKeyRef. Only an install without app.postgres or app.localTrial may set podSecurityContext.fsGroup (such as 65532) instead; with either, the gateway shares the provider-key volume and fsGroup stays unset." $where) -}}
{{- end -}}
{{- if kindIs "invalid" (index $holder "defaultMode") -}}
{{- $_ := set $holder "defaultMode" 288 -}}
{{- else -}}
{{- include "keeplane.gatewaySecretMode.check" (dict "mode" (index $holder "defaultMode") "where" $where) -}}
{{- end -}}
{{- range $secret := $secrets -}}
{{- range $item := ($secret.items | default list) -}}
{{- if and (kindIs "map" $item) (not (kindIs "invalid" (index $item "mode"))) -}}
{{- include "keeplane.gatewaySecretMode.check" (dict "mode" (index $item "mode") "where" (printf "%s item %s" $where ($item.key | default "unnamed"))) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- $volumes = append $volumes $volume -}}
{{- end -}}
{{- toYaml $volumes -}}
{{- end -}}

{{- /*
Refuses a file mode on a Secret the installer mounts into the managed gateway
copies unless it is owner and group read (0440) or stricter: no write or
execute bit and nothing for other users. Takes a dict with "mode" and "where".
*/ -}}
{{- define "keeplane.gatewaySecretMode.check" -}}
{{- $mode := .mode -}}
{{- if not (or (kindIs "float64" $mode) (kindIs "int64" $mode) (kindIs "int" $mode)) -}}
{{- fail (printf "%s sets a Secret file mode that is not a number (%v). Leave it unset for 0440, or give an octal number such as 0440 or 0400." .where $mode) -}}
{{- end -}}
{{- $mode = int $mode -}}
{{- $owner := mod (div $mode 64) 8 -}}
{{- $group := mod (div $mode 8) 8 -}}
{{- $other := mod $mode 8 -}}
{{- if or (lt $mode 0) (gt $mode 511) (ne $other 0) (and (ne $owner 0) (ne $owner 4)) (and (ne $group 0) (ne $group 4)) -}}
{{- fail (printf "%s gives Secret files mode %#o. The managed gateway copies accept only owner and group read (0440) or stricter, such as 0400: no write or execute bit and nothing for other users. Leave the mode unset and the chart uses 0440." .where $mode) -}}
{{- end -}}
{{- end -}}
