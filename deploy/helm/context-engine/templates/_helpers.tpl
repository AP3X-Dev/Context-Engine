{{/*
Expand the name of the chart.
*/}}
{{- define "context-engine.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "context-engine.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "context-engine.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "context-engine.labels" -}}
helm.sh/chart: {{ include "context-engine.chart" . }}
{{ include "context-engine.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: kubernetes-deployment
environment: {{ .Values.global.environment }}
team: {{ .Values.global.team }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "context-engine.selectorLabels" -}}
app.kubernetes.io/name: {{ include "context-engine.fullname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app: {{ .Values.global.appName }}
{{- end }}

{{/*
Component labels - adds component-specific labels
*/}}
{{- define "context-engine.componentLabels" -}}
{{ include "context-engine.labels" . }}
component: {{ .component }}
{{- end }}

{{/*
Component selector labels
*/}}
{{- define "context-engine.componentSelectorLabels" -}}
{{ include "context-engine.selectorLabels" . }}
component: {{ .component }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "context-engine.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "context-engine.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the namespace name
*/}}
{{- define "context-engine.namespace" -}}
{{- default .Release.Namespace .Values.namespace.name }}
{{- end }}

{{/*
Create Qdrant URL
*/}}
{{- define "context-engine.qdrantUrl" -}}
{{- if .Values.config.qdrantUrl }}
{{- .Values.config.qdrantUrl }}
{{- else }}
{{- printf "http://qdrant:%d" (int .Values.qdrant.service.httpPort) }}
{{- end }}
{{- end }}

{{/*
Create Memory MCP URL
*/}}
{{- define "context-engine.memoryMcpUrl" -}}
{{- if .Values.config.memory.mcpUrl }}
{{- .Values.config.memory.mcpUrl }}
{{- else }}
{{- printf "http://mcp-memory-http:%d/sse" (int .Values.mcpMemoryHttp.service.port) }}
{{- end }}
{{- end }}

{{/*
Image name helper
*/}}
{{- define "context-engine.image" -}}
{{- $tag := default .Chart.AppVersion .Values.image.tag }}
{{- printf "%s:%s" .Values.image.repository $tag }}
{{- end }}

{{/*
Pod security context
*/}}
{{- define "context-engine.podSecurityContext" -}}
{{- with .Values.podSecurityContext }}
{{- toYaml . }}
{{- end }}
{{- end }}

{{/*
Topology spread constraints helper
*/}}
{{- define "context-engine.topologySpreadConstraints" -}}
{{- if .config.enabled }}
topologySpreadConstraints:
  - maxSkew: {{ .config.maxSkew }}
    topologyKey: {{ .config.topologyKey }}
    whenUnsatisfiable: {{ .config.whenUnsatisfiable }}
    labelSelector:
      matchLabels:
        {{- include "context-engine.componentSelectorLabels" .context | nindent 8 }}
{{- end }}
{{- end }}

{{/*
HPA behavior configuration
*/}}
{{- define "context-engine.hpaBehavior" -}}
behavior:
  scaleDown:
    policies:
      - type: Percent
        value: 100
        periodSeconds: 15
    stabilizationWindowSeconds: 300
  scaleUp:
    policies:
      - type: Percent
        value: 100
        periodSeconds: 30
      - type: Pods
        value: 4
        periodSeconds: 30
    selectPolicy: Max
    stabilizationWindowSeconds: 0
{{- end }}
