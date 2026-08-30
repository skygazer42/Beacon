{{- define "beacon-cloud-saas-v1.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.labels" -}}
helm.sh/chart: {{ include "beacon-cloud-saas-v1.chart" . }}
app.kubernetes.io/name: {{ include "beacon-cloud-saas-v1.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "beacon-cloud-saas-v1.selectorLabels" -}}
app.kubernetes.io/name: {{ include "beacon-cloud-saas-v1.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "beacon-cloud-saas-v1.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "beacon-cloud-saas-v1.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.secretName" -}}
{{- if .Values.beaconCloud.secrets.existingSecret -}}
{{- .Values.beaconCloud.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secret" (include "beacon-cloud-saas-v1.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.imageRef" -}}
{{- $name := required "imageRef.name is required" .name -}}
{{- $repository := required (printf "%s.image.repository is required" $name) .image.repository -}}
{{- $tag := required (printf "%s.image.tag is required" $name) .image.tag -}}
{{- $digest := default "" .image.digest -}}
{{- if and .requireDigest (not $digest) -}}
{{- fail (printf "%s.image.digest is required and must pin the image by sha256" $name) -}}
{{- end -}}
{{- if and $digest (not (regexMatch "^sha256:[a-f0-9]{64}$" $digest)) -}}
{{- fail (printf "%s.image.digest must match sha256:<64 lowercase hex characters>" $name) -}}
{{- end -}}
{{- if $digest -}}
{{- printf "%s:%s@%s" $repository $tag $digest -}}
{{- else -}}
{{- printf "%s:%s" $repository $tag -}}
{{- end -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.postgresName" -}}
{{- printf "%s-postgres" (include "beacon-cloud-saas-v1.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.minioName" -}}
{{- printf "%s-minio" (include "beacon-cloud-saas-v1.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.demoPVCName" -}}
{{- printf "%s-demo" (include "beacon-cloud-saas-v1.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.runtimePVCName" -}}
{{- if .Values.beaconCloud.runtimeStorage.persistence.existingClaim -}}
{{- .Values.beaconCloud.runtimeStorage.persistence.existingClaim -}}
{{- else -}}
{{- printf "%s-runtime" (include "beacon-cloud-saas-v1.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.edgeSimulatorName" -}}
{{- printf "%s-edge-simulator" (include "beacon-cloud-saas-v1.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.backgroundWorkerName" -}}
{{- printf "%s-background-worker" (include "beacon-cloud-saas-v1.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.initializeJobName" -}}
{{- printf "%s-init-%d" (include "beacon-cloud-saas-v1.fullname" .) .Release.Revision | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.runtimeEnv" -}}
{{- $root := .root -}}
{{- $role := .role -}}
- name: BEACON_DEPLOYMENT_MODE
  value: {{ $root.Values.beaconCloud.env.deploymentMode | quote }}
- name: BEACON_BACKGROUND_ROLE
  value: {{ $role | quote }}
- name: BEACON_OPEN_API_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "beacon-cloud-saas-v1.secretName" $root }}
      key: beacon-open-api-token
- name: BEACON_REQUIRE_OPEN_API_TOKEN
  value: "1"
- name: BEACON_HEALTH_CHECK_HOST
  value: {{ $root.Values.beaconCloud.env.healthCheckHost | quote }}
- name: BEACON_DJANGO_DEBUG
  value: {{ $root.Values.beaconCloud.env.djangoDebug | quote }}
- name: BEACON_DJANGO_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "beacon-cloud-saas-v1.secretName" $root }}
      key: beacon-django-secret-key
- name: BEACON_DJANGO_ALLOWED_HOSTS
  value: {{ $root.Values.beaconCloud.env.djangoAllowedHosts | quote }}
- name: BEACON_DJANGO_SESSION_COOKIE_SECURE
  value: "1"
- name: BEACON_DJANGO_CSRF_COOKIE_SECURE
  value: "1"
- name: BEACON_DJANGO_TRUST_X_FORWARDED_PROTO
  value: "1"
- name: BEACON_DJANGO_CSRF_TRUSTED_ORIGINS
  value: {{ $root.Values.beaconCloud.env.djangoCsrfTrustedOrigins | quote }}
- name: BEACON_DJANGO_HSTS_SECONDS
  value: {{ $root.Values.beaconCloud.env.djangoHstsSeconds | quote }}
- name: BEACON_CLOUD_DB_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "beacon-cloud-saas-v1.secretName" $root }}
      key: beacon-cloud-db-url
- name: BEACON_REQUIRE_DATABASE_TLS
  {{- if $root.Values.postgres.enabled }}
  value: "0"
  {{- else }}
  value: "1"
  {{- end }}
{{- if $root.Values.postgres.enabled }}
- name: BEACON_PG_HOST
  value: {{ include "beacon-cloud-saas-v1.postgresName" $root | quote }}
- name: BEACON_PG_PORT
  value: {{ printf "%v" $root.Values.postgres.service.port | quote }}
{{- end }}
- name: BEACON_CLOUD_EDGE_TOKEN_PEPPER
  valueFrom:
    secretKeyRef:
      name: {{ include "beacon-cloud-saas-v1.secretName" $root }}
      key: beacon-edge-token-pepper
- name: BEACON_CLOUD_S3_BUCKET
  value: {{ $root.Values.minio.bucket | quote }}
- name: BEACON_CLOUD_S3_REGION
  value: {{ $root.Values.minio.region | quote }}
- name: BEACON_CLOUD_S3_ENDPOINT_URL
  {{- if $root.Values.minio.enabled }}
  value: {{ printf "http://%s:%v" (include "beacon-cloud-saas-v1.minioName" $root) $root.Values.minio.service.apiPort | quote }}
  {{- else }}
  value: {{ $root.Values.minio.externalEndpointURL | quote }}
  {{- end }}
- name: BEACON_ALLOW_INSECURE_OBJECT_STORAGE
  {{- if $root.Values.minio.enabled }}
  value: "1"
  {{- else }}
  value: "0"
  {{- end }}
- name: BEACON_CLOUD_S3_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ include "beacon-cloud-saas-v1.secretName" $root }}
      key: minio-root-user
- name: BEACON_CLOUD_S3_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "beacon-cloud-saas-v1.secretName" $root }}
      key: minio-root-password
- name: BEACON_CLOUD_IMAGE_PREVIEW_PROXY
  value: {{ $root.Values.beaconCloud.env.cloudImagePreviewProxy | quote }}
{{- if eq $role "init" }}
- name: BEACON_BOOTSTRAP_ADMIN_USERNAME
  valueFrom:
    secretKeyRef:
      name: {{ include "beacon-cloud-saas-v1.secretName" $root }}
      key: beacon-bootstrap-admin-username
- name: BEACON_BOOTSTRAP_ADMIN_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "beacon-cloud-saas-v1.secretName" $root }}
      key: beacon-bootstrap-admin-password
- name: BEACON_BOOTSTRAP_EDGE_CLUSTER_NAME
  value: {{ $root.Values.beaconCloud.env.bootstrapEdgeClusterName | quote }}
- name: BEACON_BOOTSTRAP_EDGE_TOKEN_FILE
  value: {{ $root.Values.beaconCloud.env.bootstrapEdgeTokenFile | quote }}
{{- end }}
{{- if eq $role "web" }}
- name: BEACON_GUNICORN_WORKERS
  value: {{ printf "%v" $root.Values.beaconCloud.gunicorn.workers | quote }}
- name: BEACON_GUNICORN_THREADS
  value: {{ printf "%v" $root.Values.beaconCloud.gunicorn.threads | quote }}
{{- end }}
{{- if eq $role "worker" }}
- name: BEACON_BACKGROUND_HEARTBEAT_PATH
  value: {{ $root.Values.backgroundWorker.heartbeat.path | quote }}
- name: BEACON_BACKGROUND_HEARTBEAT_SECONDS
  value: {{ printf "%v" $root.Values.backgroundWorker.heartbeat.intervalSeconds | quote }}
- name: BEACON_BACKGROUND_HEARTBEAT_MAX_AGE_SECONDS
  value: {{ printf "%v" $root.Values.backgroundWorker.heartbeat.maxAgeSeconds | quote }}
- name: BEACON_BACKGROUND_STANDBY_POLL_SECONDS
  value: {{ printf "%v" $root.Values.backgroundWorker.standbyPollSeconds | quote }}
{{- end }}
{{- if or (eq $role "web") (eq $role "worker") }}
- name: BEACON_MIGRATION_WAIT_ATTEMPTS
  value: {{ printf "%v" $root.Values.initialization.waitAttempts | quote }}
- name: BEACON_MIGRATION_WAIT_DELAY_SECONDS
  value: {{ printf "%v" $root.Values.initialization.waitDelaySeconds | quote }}
{{- end }}
{{- end -}}
