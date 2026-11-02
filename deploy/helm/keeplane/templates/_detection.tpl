{{- /*
Personal-data detection (Spec 005 ST20). app.personalDataDetection.enabled sets
the app's install setting; it never turns detection on, which stays an admin
choice under Data classes. Helm refuses the setups it can tell are wrong. It
cannot see which image target app.image was built from, so a missing detector
is reported by the app instead (start-up log and the Data classes page).
*/ -}}

{{- /* The smallest memory limit the detector fits in: about 750 MiB for the
language model plus the app itself. */ -}}
{{- define "keeplane.detection.minimumMemory" -}}1073741824{{- end }}

{{- /* A Kubernetes memory quantity in bytes, or fail naming the setting.
Accepts a number, or digits with an optional decimal part and one of the
suffixes Ki Mi Gi Ti Pi Ei k M G T P E. Argument: list <setting> <value>. */ -}}
{{- define "keeplane.memoryBytes" -}}
{{- $where := index . 0 }}
{{- $value := index . 1 }}
{{- if or (kindIs "float64" $value) (kindIs "int" $value) (kindIs "int64" $value) }}
{{- float64 $value }}
{{- else }}
{{- $text := toString $value }}
{{- $match := regexFind "^[0-9]+(\\.[0-9]+)?(Ki|Mi|Gi|Ti|Pi|Ei|k|M|G|T|P|E)?$" $text }}
{{- if not $match }}
{{- fail (printf "%s: write the memory as a number of bytes or with a unit such as 1536Mi or 2Gi (got %q)" $where $text) }}
{{- end }}
{{- $number := regexFind "^[0-9]+(\\.[0-9]+)?" $text }}
{{- $unit := trimPrefix $number $text }}
{{- $units := dict "" 1.0 "k" 1e3 "M" 1e6 "G" 1e9 "T" 1e12 "P" 1e15 "E" 1e18 "Ki" 1024.0 "Mi" 1048576.0 "Gi" 1073741824.0 "Ti" 1099511627776.0 "Pi" 1125899906842624.0 "Ei" 1152921504606846976.0 }}
{{- mulf (float64 $number) (index $units $unit) }}
{{- end }}
{{- end }}

{{- define "keeplane.detection.check" -}}
{{- if .Values.app.personalDataDetection.enabled }}
{{- if not (or .Values.app.postgres.enabled .Values.app.localTrial.enabled) }}
{{- fail "app.personalDataDetection needs app.postgres or app.localTrial: with detection on, the app is ready only once its database and the language model are, and without either setting the chart gives the app no database, so it would never become ready" }}
{{- end }}
{{- if ne .Values.gateway.mode "existing" }}
{{- fail "app.personalDataDetection requires gateway.mode=existing with Keeplane's checks set up on that gateway, sending messages: the managed gateway in this chart doesn't run Keeplane's checks yet, so no request would be checked. See docs/guide/gateway-configuration.md#keeplanes-checks-on-a-customer-run-gateway" }}
{{- end }}
{{- $resources := .Values.app.resources | default dict }}
{{- $limits := get $resources "limits" | default dict }}
{{- with get $limits "memory" }}
{{- $bytes := include "keeplane.memoryBytes" (list "app.resources.limits.memory" .) | float64 }}
{{- if lt $bytes (include "keeplane.detection.minimumMemory" $ | float64) }}
{{- fail (printf "app.personalDataDetection needs app.resources.limits.memory of at least 1Gi; the language model alone uses about 750 MiB (got %v)" .) }}
{{- end }}
{{- end }}
{{- end }}
{{- end }}
