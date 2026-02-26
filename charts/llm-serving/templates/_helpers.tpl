{{- define "llm-serving.modelfile" -}}
FROM {{ .ggufPath }}/{{ .ggufFile }}
{{- end -}}
