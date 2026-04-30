"""Compatibility imports for local inference descriptors and helpers."""

from __future__ import annotations

from agent.core.local_inference_endpoints import (
    LocalInferenceConfigError,
    LocalInferenceRuntimeCapabilities,
    LocalInferenceRuntimeDescriptor,
    describe_local_inference_runtime,
    list_local_inference_runtime_descriptors,
    resolve_local_inference_base_url,
    supported_local_runtimes,
)
from agent.core.local_inference_probes import (
    LOCAL_INFERENCE_HEALTH_PROBE,
    LOCAL_INFERENCE_MODELS_PROBE,
    LOCAL_INFERENCE_PROBE_AVAILABLE,
    LOCAL_INFERENCE_PROBE_CONFIG_ERROR,
    LOCAL_INFERENCE_PROBE_MALFORMED,
    LOCAL_INFERENCE_PROBE_MODEL_MISSING,
    LOCAL_INFERENCE_PROBE_TOOL_SUPPORT_UNKNOWN,
    LOCAL_INFERENCE_PROBE_UNAVAILABLE,
    LocalInferenceProbeClassification,
    LocalInferenceProbeDescriptor,
    build_local_inference_probe_descriptors,
    classify_local_inference_probe_result,
)

__all__ = (
    "LOCAL_INFERENCE_HEALTH_PROBE",
    "LOCAL_INFERENCE_MODELS_PROBE",
    "LOCAL_INFERENCE_PROBE_AVAILABLE",
    "LOCAL_INFERENCE_PROBE_CONFIG_ERROR",
    "LOCAL_INFERENCE_PROBE_MALFORMED",
    "LOCAL_INFERENCE_PROBE_MODEL_MISSING",
    "LOCAL_INFERENCE_PROBE_TOOL_SUPPORT_UNKNOWN",
    "LOCAL_INFERENCE_PROBE_UNAVAILABLE",
    "LocalInferenceConfigError",
    "LocalInferenceProbeClassification",
    "LocalInferenceProbeDescriptor",
    "LocalInferenceRuntimeCapabilities",
    "LocalInferenceRuntimeDescriptor",
    "build_local_inference_probe_descriptors",
    "classify_local_inference_probe_result",
    "describe_local_inference_runtime",
    "list_local_inference_runtime_descriptors",
    "resolve_local_inference_base_url",
    "supported_local_runtimes",
)
