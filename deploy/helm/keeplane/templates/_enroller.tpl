{{- /*
The private model enroller (ADR 027) in each managed gateway copy Pod, and the
app's per-copy guard-status check. Both are off by default.

The enroller is a second container in every gateway copy Pod of the
StatefulSet, so it shares that copy's network namespace and reads its
loopback-only applied state, as in the Docker preview. It opens no port, runs
as the app user with a read-only root file system, gets no Kubernetes API
token (the Pod already has none) and has resource limits.

The gateway Pod has no fsGroup with PostgreSQL (it shares the provider-key
volume), so Secret files mounted there could be read only by root. The
enroller's credentials therefore reach only its init container, as
secretKeyRef environment values, and prepare_enroller_files.py writes the ones
this copy needs into an in-memory folder that only the enroller mounts, read
only: the approvals role's password, this copy's own status role and password
(picked by Pod name, so no enroller holds another copy's status password), the
two gateway keys, the database CA and a random signing secret of its own. The
gateway container gets none of them.

The guard is a Pod-local folder (keeplane-guard, at /installed) that only the
enroller mounts read-write; the gateway container mounts it read-only and the
app never mounts it.
*/ -}}

{{- define "keeplane.enroller.on" -}}
{{- $enroller := .Values.gateway.enroller | default dict -}}
{{- if $enroller.enabled }}true{{ end -}}
{{- end -}}

{{- /* KEEPLANE_GUARD_STATUS_CHECK: on with the enroller, or when asked. */ -}}
{{- define "keeplane.guardStatusCheck.on" -}}
{{- if or .Values.app.guardStatusCheck (include "keeplane.enroller.on" .) }}true{{ end -}}
{{- end -}}

{{- /* Refuse unsafe or incomplete enroller and guard-status settings. Included from checks/first/model-enroller.yaml. */ -}}
{{- define "keeplane.enroller.check" -}}
{{- $enroller := .Values.gateway.enroller | default dict -}}
{{- $managed := eq .Values.gateway.mode "managed" -}}
{{- if $enroller.enabled -}}
{{- if not $managed -}}
{{- fail "gateway.enroller.enabled applies only to the managed gateway. Keeplane writes no guard on a customer-run gateway (gateway.mode=existing): its checks read the saved approvals on every request, so model changes apply without an enroller. Leave gateway.enroller.enabled false." -}}
{{- end -}}
{{- if not .Values.app.postgres.enabled -}}
{{- fail "gateway.enroller needs app.postgres: each copy's enroller records what it confirmed in the guard-status table, which only PostgreSQL keeps. The local trial's SQLite file stays with the app." -}}
{{- end -}}
{{- $role := "^[a-z_][a-z0-9_]{0,62}$" -}}
{{- $copies := int .Values.gateway.copies -}}
{{- $approvals := toString ($enroller.approvalsUser | default "") -}}
{{- if not (regexMatch $role $approvals) -}}
{{- fail "gateway.enroller.approvalsUser must name the enroller's read-only approvals role in lowercase letters, digits and underscores (see docs/guide/guard-status-roles.md)" -}}
{{- end -}}
{{- $roles := $enroller.statusRoles | default list -}}
{{- if not (kindIs "slice" $roles) -}}
{{- fail "gateway.enroller.statusRoles must be a list with one status role per gateway copy" -}}
{{- end -}}
{{- if ne (len $roles) $copies -}}
{{- fail (printf "gateway.enroller.statusRoles must list exactly one status role per gateway copy, in copy order: gateway.copies is %d, but %d roles are listed" $copies (len $roles)) -}}
{{- end -}}
{{- range $index, $name := $roles -}}
{{- if not (and (kindIs "string" $name) (regexMatch $role $name)) -}}
{{- fail (printf "gateway.enroller.statusRoles[%d] must be a role name in lowercase letters, digits and underscores" $index) -}}
{{- end -}}
{{- end -}}
{{- $appUser := toString .Values.app.postgres.user -}}
{{- $migrationUser := toString .Values.app.postgres.migration.user -}}
{{- if not (regexMatch $role $appUser) -}}
{{- fail "gateway.enroller needs app.postgres.user in lowercase letters, digits and underscores: the guard-status grants name the app role" -}}
{{- end -}}
{{- $all := concat (list $appUser $migrationUser $approvals) $roles -}}
{{- if ne (len (uniq $all)) (len $all) -}}
{{- fail "gateway.enroller needs its own roles: the approvals role and every copy's status role must differ from each other, from app.postgres.user and from app.postgres.migration.user" -}}
{{- end -}}
{{- if not $enroller.approvalsSecret -}}
{{- fail "gateway.enroller.approvalsSecret is required: an installer-made Secret with key password for gateway.enroller.approvalsUser" -}}
{{- end -}}
{{- if not $enroller.statusSecret -}}
{{- fail "gateway.enroller.statusSecret is required: an installer-made Secret with keys copy-0-password, copy-1-password and so on, one per gateway copy's status role" -}}
{{- end -}}
{{- $shared := list .Values.app.postgres.credentialsSecret .Values.app.postgres.migration.credentialsSecret .Values.app.postgres.identitySecret .Values.gateway.keysSecret -}}
{{- if or (has $enroller.approvalsSecret $shared) (has $enroller.statusSecret $shared) -}}
{{- fail "gateway.enroller.approvalsSecret and statusSecret must be Secrets of their own, not the app's, the migration's, the identity or the gateway keys Secret" -}}
{{- end -}}
{{- $last := printf "%s-gateway-%d" .Release.Name (sub $copies 1) -}}
{{- if gt (len $last) 63 -}}
{{- fail (printf "gateway.enroller names each copy by its Pod name, which must be at most 63 characters; %s is longer. Use a shorter release name." $last) -}}
{{- end -}}
{{- $limits := dig "resources" "limits" (dict) $enroller -}}
{{- if not (and (kindIs "map" $limits) $limits.cpu $limits.memory) -}}
{{- fail "gateway.enroller.resources.limits needs cpu and memory: the enroller runs beside every gateway copy and must not take its resources" -}}
{{- end -}}
{{- /* The enroller's own volumes; installer volumes may not reuse their names. */ -}}
{{- $reserved := list "keeplane-guard" "keeplane-enroller-files" "keeplane-enroller-provider-keys" -}}
{{- range .Values.gateway.extraVolumes -}}
{{- if and (kindIs "map" .) (has (toString .name) $reserved) -}}
{{- fail (printf "gateway.extraVolumes uses the name %s, which the model enroller needs; rename that volume" .name) -}}
{{- end -}}
{{- end -}}
{{- range .Values.gateway.extraVolumeMounts -}}
{{- if and (kindIs "map" .) (eq (trimSuffix "/" (toString .mountPath)) "/installed") -}}
{{- fail "gateway.extraVolumeMounts mounts something at /installed, where the gateway reads the enroller's guard; choose another path" -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- if .Values.app.guardStatusCheck -}}
{{- if not $managed -}}
{{- fail "app.guardStatusCheck applies only to the managed gateway: a customer-run gateway (gateway.mode=existing) has no enroller and no guard-status rows, so leave it false" -}}
{{- end -}}
{{- if not .Values.app.postgres.enabled -}}
{{- fail "app.guardStatusCheck needs app.postgres: the guard-status table exists only in PostgreSQL" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "keeplane.enroller.securityContext" -}}
runAsNonRoot: true
runAsUser: 65532
runAsGroup: 65532
privileged: false
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- /* Writes this copy's credentials and makes the guard folder private, then exits. */ -}}
{{- define "keeplane.enroller.initContainer" -}}
{{- $enroller := .Values.gateway.enroller -}}
- name: prepare-model-enroller
  image: {{ .Values.app.image | quote }}
  imagePullPolicy: {{ .Values.app.pullPolicy }}
  command: [python, "-I", /app/prepare_enroller_files.py]
  env:
    - name: KEEPLANE_GATEWAY_COPY
      valueFrom:
        fieldRef:
          fieldPath: metadata.name
    - name: KEEPLANE_ENROLLER_COPY_PREFIX
      value: {{ printf "%s-gateway-" .Release.Name | quote }}
    - name: KEEPLANE_ENROLLER_STATUS_ROLES
      value: {{ join "," $enroller.statusRoles | quote }}
    - name: KEEPLANE_ENROLLER_APPROVALS_PASSWORD
      valueFrom:
        secretKeyRef:
          name: {{ $enroller.approvalsSecret | quote }}
          key: password
    {{- range $index := until (int .Values.gateway.copies) }}
    - name: KEEPLANE_ENROLLER_STATUS_PASSWORD_{{ $index }}
      valueFrom:
        secretKeyRef:
          name: {{ $enroller.statusSecret | quote }}
          key: {{ printf "copy-%d-password" $index }}
    {{- end }}
    - name: KEEPLANE_ENROLLER_DATABASE_CA
      valueFrom:
        secretKeyRef:
          name: {{ required "app.postgres.caSecret is required" .Values.app.postgres.caSecret | quote }}
          key: ca.crt
    - name: KEEPLANE_ENROLLER_GATEWAY_ADMIN_KEY
      valueFrom:
        secretKeyRef:
          name: {{ .Values.gateway.keysSecret | quote }}
          key: admin-key
    - name: KEEPLANE_ENROLLER_GATEWAY_RUNTIME_KEY
      valueFrom:
        secretKeyRef:
          name: {{ .Values.gateway.keysSecret | quote }}
          key: runtime-key
  volumeMounts:
    - name: keeplane-enroller-files
      mountPath: /run/keeplane-enroller
    - name: keeplane-guard
      mountPath: /guard
  securityContext:
    {{- include "keeplane.enroller.securityContext" . | nindent 4 }}
  resources:
    {{- toYaml $enroller.resources | nindent 4 }}
{{- end -}}

{{- define "keeplane.enroller.container" -}}
{{- $enroller := .Values.gateway.enroller -}}
{{- $files := "/run/keeplane-enroller/files" -}}
- name: model-enroller
  image: {{ .Values.app.image | quote }}
  imagePullPolicy: {{ .Values.app.pullPolicy }}
  command:
    - python
    - /app/manage.py
    - run_model_enroller
    - --callback-host
    - {{ printf "%s-app:3000" .Release.Name | quote }}
  env:
    - name: GATEWAY_URL
      value: http://127.0.0.1:4000
    - name: GATEWAY_MODE
      value: managed
    - name: GATEWAY_ADMIN_KEY_FILE
      value: {{ $files }}/gateway-admin-key
    - name: GATEWAY_RUNTIME_KEY_FILE
      value: {{ $files }}/gateway-runtime-key
    - name: RUNTIME_AUTHORIZER_KEY_FILE
      value: /installed/callback-key
    - name: RUNTIME_GUARD_MANIFEST_FILE
      value: /installed/manifest.json
    - name: GATEWAY_FILE_CONFIG
      value: /installed/gateway.json
    - name: PROVIDER_KEY_DIR
      value: /provider-keys
    - name: PUBLIC_ORIGIN
      value: {{ include "keeplane.postgres.publicOrigin" . | quote }}
    - name: KEEPLANE_DATABASE_HOST
      value: {{ .Values.app.postgres.host | quote }}
    - name: KEEPLANE_DATABASE_PORT
      value: {{ .Values.app.postgres.port | quote }}
    - name: KEEPLANE_DATABASE_NAME
      value: {{ .Values.app.postgres.database | quote }}
    - name: KEEPLANE_DATABASE_SSLMODE
      value: verify-full
    - name: KEEPLANE_DATABASE_SSLROOTCERT_FILE
      value: {{ $files }}/database-ca.crt
    - name: KEEPLANE_DATABASE_USER
      value: {{ $enroller.approvalsUser | quote }}
    - name: KEEPLANE_DATABASE_PASSWORD_FILE
      value: {{ $files }}/approvals-password
    - name: KEEPLANE_DATABASE_READ_ONLY
      value: "1"
    - name: KEEPLANE_GATEWAY_COPY
      valueFrom:
        fieldRef:
          fieldPath: metadata.name
    - name: KEEPLANE_GUARD_STATUS_DATABASE_USER_FILE
      value: {{ $files }}/status-user
    - name: KEEPLANE_GUARD_STATUS_DATABASE_PASSWORD_FILE
      value: {{ $files }}/status-password
    - name: DJANGO_SECRET_KEY_FILE
      value: {{ $files }}/signing-secret
    - name: PYTHONDONTWRITEBYTECODE
      value: "1"
  volumeMounts:
    - name: keeplane-guard
      mountPath: /installed
      subPath: installed
    - name: keeplane-enroller-files
      mountPath: /run/keeplane-enroller
      readOnly: true
    - name: keeplane-enroller-provider-keys
      mountPath: /provider-keys
      readOnly: true
  securityContext:
    {{- include "keeplane.enroller.securityContext" . | nindent 4 }}
  resources:
    {{- toYaml $enroller.resources | nindent 4 }}
{{- end -}}

{{- /* The gateway container reads the guard and nothing else of the enroller's. */ -}}
{{- define "keeplane.enroller.gatewayMount" -}}
- name: keeplane-guard
  mountPath: /installed
  subPath: installed
  readOnly: true
{{- end -}}

{{- define "keeplane.enroller.volumes" -}}
- name: keeplane-guard
  emptyDir:
    sizeLimit: 16Mi
- name: keeplane-enroller-files
  emptyDir:
    medium: Memory
    sizeLimit: 1Mi
- name: keeplane-enroller-provider-keys
  persistentVolumeClaim:
    claimName: {{ required "app.postgres.providerKeysClaim is required" .Values.app.postgres.providerKeysClaim | quote }}
    readOnly: true
{{- end -}}

{{- /* The migration Job's grants for the guard-status table, run after migrate. */ -}}
{{- define "keeplane.enroller.configureCommand" -}}
{{- $enroller := .Values.gateway.enroller -}}
{{- $parts := list "python /app/manage.py configure_guard_status_access" (printf "--app-role %s" .Values.app.postgres.user) (printf "--enroller-role %s" $enroller.approvalsUser) -}}
{{- range $index, $role := $enroller.statusRoles -}}
{{- $parts = append $parts (printf "--copy %s-gateway-%d=%s" $.Release.Name $index $role) -}}
{{- end -}}
{{- join " " $parts -}}
{{- end -}}
