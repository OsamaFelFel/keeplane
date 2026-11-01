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
