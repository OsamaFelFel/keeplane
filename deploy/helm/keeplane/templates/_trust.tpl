{{- /*
trust.extraCaBundle: extra CA certificates (PEM) that the app copies and the
managed gateway copies trust for their outbound HTTPS calls, such as a model
endpoint behind a private CA, in addition to each image's system CAs, never
instead of them. Off by default. Only the named key of the Secret or ConfigMap
is mounted, as the file ca.crt, and only into an init container.

- The app's init container prepare-trust-bundle writes the image's system CA
  file followed by these CAs to an in-memory folder, and the app's
  SSL_CERT_FILE names the result.
- Each managed gateway copy's init container prepare-trust-bundle (app image)
  checks the same source and writes only its CA certificates to an in-memory
  folder. The gateway reads that folder through SSL_CERT_DIR, and its system
  CA file through SSL_CERT_FILE, which the chart sets to the pinned image's
  /etc/ssl/certs/ca-certificates.crt rather than relying on the image.
- Either init container refuses a bundle with no certificate, a damaged one or
  a private key, so that pod doesn't start; the raw source is never mounted
  into the app or gateway container.

Both read the CAs when they start, so a changed bundle takes effect after the
app and gateway copies restart.
*/ -}}

{{- define "keeplane.trust.on" -}}
{{- $bundle := (.Values.trust | default dict).extraCaBundle | default dict -}}
{{- if or $bundle.secretName $bundle.configMapName }}true{{ end -}}
{{- end -}}

{{- define "keeplane.trust.check" -}}
{{- $bundle := (.Values.trust | default dict).extraCaBundle | default dict -}}
{{- $name := "^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$" -}}
{{- if and $bundle.secretName $bundle.configMapName -}}
{{- fail "trust.extraCaBundle: set secretName or configMapName, not both" -}}
{{- end -}}
{{- range $field := list "secretName" "configMapName" -}}
{{- $value := index $bundle $field | default "" -}}
{{- if and $value (or (gt (len $value) 253) (not (regexMatch $name $value))) -}}
{{- fail (printf "trust.extraCaBundle.%s %q is not a Kubernetes object name: use lowercase letters, digits, '-' and '.', starting and ending with a letter or digit" $field $value) -}}
{{- end -}}
{{- end -}}
{{- if include "keeplane.trust.on" . -}}
{{- $key := $bundle.key | default "" -}}
{{- if or (not $key) (gt (len $key) 253) (not (regexMatch "^[-._a-zA-Z0-9]+$" $key)) (eq $key ".") (eq $key "..") -}}
{{- fail (printf "trust.extraCaBundle.key %q is not a Secret or ConfigMap key: name the key that holds the PEM bundle, such as ca.crt (letters, digits, '-', '_' and '.')" $key) -}}
{{- end -}}
{{- if and (eq .Values.gateway.mode "managed") .Values.gateway.install -}}
{{- range $entry := ((index .Values "agentgateway-standalone").extraEnv | default list) -}}
{{- if and (kindIs "map" $entry) (has $entry.name (list "SSL_CERT_FILE" "SSL_CERT_DIR")) -}}
{{- fail (printf "Leave %s out of agentgateway-standalone.extraEnv while trust.extraCaBundle is set: the chart adds the extra CAs to the gateway's system CAs itself, and this variable would replace them" $entry.name) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- /* The extra CA volume, given a dict with "root" and "mode" (file mode). */ -}}
{{- define "keeplane.trust.sourceVolume" -}}
{{- $bundle := .root.Values.trust.extraCaBundle -}}
- name: keeplane-extra-ca-source
  {{- if $bundle.secretName }}
  secret:
    secretName: {{ $bundle.secretName | quote }}
  {{- else }}
  configMap:
    name: {{ $bundle.configMapName | quote }}
  {{- end }}
    defaultMode: {{ .mode }}
    items:
      - key: {{ $bundle.key | quote }}
        path: ca.crt
{{- end -}}

{{- define "keeplane.trust.sourceMount" -}}
- name: keeplane-extra-ca-source
  mountPath: /run/keeplane-extra-ca-source
  readOnly: true
{{- end -}}

{{- /* The checking init container, given a dict with "root", "arguments"
(after the script) and "output" (the volume it writes). */ -}}
{{- define "keeplane.trust.checkingContainer" -}}
- name: prepare-trust-bundle
  image: {{ .root.Values.app.image | quote }}
  imagePullPolicy: {{ .root.Values.app.pullPolicy }}
  command:
    - python
    - /app/prepare_trust_bundle.py
    {{- range .arguments }}
    - {{ . }}
    {{- end }}
  volumeMounts:
    {{- include "keeplane.trust.sourceMount" . | nindent 4 }}
    - name: {{ .output.name }}
      mountPath: {{ .output.path }}
  securityContext:
    runAsNonRoot: true
    runAsUser: 65532
    runAsGroup: 65532
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop: [ALL]
{{- end -}}

{{- /* App pods: the source (group read, through the pod's fsGroup) and the
in-memory folder for the combined bundle. */ -}}
{{- define "keeplane.trust.appVolumes" -}}
{{- if include "keeplane.trust.on" . }}
{{ include "keeplane.trust.sourceVolume" (dict "root" . "mode" "0440") }}
- name: keeplane-trust
  emptyDir:
    medium: Memory
    sizeLimit: 16Mi
{{- end }}
{{- end -}}

{{- define "keeplane.trust.appMount" -}}
{{- if include "keeplane.trust.on" . }}
- name: keeplane-trust
  mountPath: /run/keeplane-trust
  readOnly: true
{{- end }}
{{- end -}}

{{- define "keeplane.trust.appEnv" -}}
{{- if include "keeplane.trust.on" . }}
- name: SSL_CERT_FILE
  value: /run/keeplane-trust/ca-bundle.pem
{{- end }}
{{- end -}}

{{- define "keeplane.trust.initContainer" -}}
{{- if include "keeplane.trust.on" . }}
{{ include "keeplane.trust.checkingContainer" (dict "root" . "arguments" (list "/run/keeplane-extra-ca-source/ca.crt" "/run/keeplane-trust/ca-bundle.pem") "output" (dict "name" "keeplane-trust" "path" "/run/keeplane-trust")) }}
{{- end }}
{{- end -}}

{{- /* Managed gateway copies. The init container runs without the
pod's fsGroup (the gateway has none), so the source holds just the named key,
a public CA certificate, with mode 0444. The gateway container mounts only the
checked output. */ -}}
{{- define "keeplane.trust.gatewayInitContainer" -}}
{{- if include "keeplane.trust.on" . }}
{{ include "keeplane.trust.checkingContainer" (dict "root" . "arguments" (list "--extra-only" "/run/keeplane-extra-ca-source/ca.crt" "/run/keeplane-extra-ca/ca.crt") "output" (dict "name" "keeplane-extra-ca" "path" "/run/keeplane-extra-ca")) }}
{{- end }}
{{- end -}}

{{- /* The pinned gateway image's system CA file (its own SSL_CERT_FILE);
tests/e2e/test_kind_private_ca.py checks that the image still has it. */ -}}
{{- define "keeplane.trust.gatewaySystemFile" -}}
/etc/ssl/certs/ca-certificates.crt
{{- end -}}

{{- define "keeplane.trust.gatewayEnv" -}}
{{- if include "keeplane.trust.on" . }}
- name: SSL_CERT_FILE
  value: {{ include "keeplane.trust.gatewaySystemFile" . }}
- name: SSL_CERT_DIR
  value: /run/keeplane-extra-ca
{{- end }}
{{- end -}}

{{- define "keeplane.trust.gatewayMount" -}}
{{- if include "keeplane.trust.on" . }}
- name: keeplane-extra-ca
  mountPath: /run/keeplane-extra-ca
  readOnly: true
{{- end }}
{{- end -}}

{{- define "keeplane.trust.gatewayVolume" -}}
{{- if include "keeplane.trust.on" . }}
{{ include "keeplane.trust.sourceVolume" (dict "root" . "mode" "0444") }}
- name: keeplane-extra-ca
  emptyDir:
    medium: Memory
    sizeLimit: 2Mi
{{- end }}
{{- end -}}
