{{- define "keeplane.postgres.env" -}}
- name: KEEPLANE_DATABASE_HOST
  value: {{ required "app.postgres.host is required" .Values.app.postgres.host | quote }}
- name: KEEPLANE_DATABASE_PORT
  value: {{ .Values.app.postgres.port | quote }}
- name: KEEPLANE_DATABASE_NAME
  value: {{ required "app.postgres.database is required" .Values.app.postgres.database | quote }}
- name: KEEPLANE_DATABASE_PASSWORD_FILE
  value: /run/keeplane-database/password
- name: KEEPLANE_DATABASE_SSLMODE
  value: verify-full
- name: KEEPLANE_DATABASE_SSLROOTCERT_FILE
  value: /run/keeplane-database-ca/ca.crt
- name: DJANGO_SECRET_KEY_FILE
  value: /run/keeplane-identity/signing-secret
- name: PYTHONDONTWRITEBYTECODE
  value: "1"
{{- end -}}

{{- define "keeplane.postgres.publicOrigin" -}}
{{- if .Values.ingress.enabled -}}
{{- printf "https://%s" (required "ingress.host is required" .Values.ingress.host) -}}
{{- else -}}
{{- .Values.app.postgres.publicOrigin -}}
{{- end -}}
{{- end -}}

{{- define "keeplane.postgres.mounts" -}}
- name: database-credentials
  mountPath: /run/keeplane-database
  readOnly: true
- name: database-ca
  mountPath: /run/keeplane-database-ca
  readOnly: true
- name: identity
  mountPath: /run/keeplane-identity
  readOnly: true
{{- end -}}

{{- define "keeplane.postgres.ca" -}}
- name: database-ca
  secret:
    secretName: {{ required "app.postgres.caSecret is required" .Values.app.postgres.caSecret | quote }}
    defaultMode: 0440
    items:
      - key: ca.crt
        path: ca.crt
{{- end -}}
