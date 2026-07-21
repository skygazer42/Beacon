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

{{- define "beacon-cloud-saas-v1.postgresName" -}}
{{- printf "%s-postgres" (include "beacon-cloud-saas-v1.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.minioName" -}}
{{- printf "%s-minio" (include "beacon-cloud-saas-v1.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.minioInitName" -}}
{{- printf "%s-minio-init" (include "beacon-cloud-saas-v1.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.demoPVCName" -}}
{{- printf "%s-demo" (include "beacon-cloud-saas-v1.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "beacon-cloud-saas-v1.edgeSimulatorName" -}}
{{- printf "%s-edge-simulator" (include "beacon-cloud-saas-v1.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
