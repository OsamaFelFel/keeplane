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
