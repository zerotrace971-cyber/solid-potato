"""
llm.py - Gemini API wrapper with structured JSON output and error handling
Using the modern google-genai SDK
"""
import json
import time
from typing import Optional, Dict, List

try:
    from google import genai
    from google.genai import types
    from google.genai.errors import APIError
except ImportError:
    import google.generativeai as genai  # type: ignore
    from google.generativeai import types  # type: ignore

    class APIError(Exception):
        pass

try:
    from .config import (
        GEMINI_API_KEY, GEMINI_MODEL, GEMINI_MAX_TOKENS, GEMINI_TEMPERATURE
    )
except ImportError:  # pragma: no cover - fallback for direct script execution
    from config import (
        GEMINI_API_KEY, GEMINI_MODEL, GEMINI_MAX_TOKENS, GEMINI_TEMPERATURE
    )


class GeminiClient:
    def __init__(self):
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not set in config")
        
        if hasattr(genai, "Client"):
            self.client = genai.Client(api_key=GEMINI_API_KEY)
            self.model_name = GEMINI_MODEL
            self.config = types.GenerateContentConfig(
                max_output_tokens=GEMINI_MAX_TOKENS,
                temperature=GEMINI_TEMPERATURE,
                response_mime_type="application/json",
            )
        else:
            genai.configure(api_key=GEMINI_API_KEY)
            self.client = genai
            self.model_name = GEMINI_MODEL
            self.config = {
                "max_output_tokens": GEMINI_MAX_TOKENS,
                "temperature": GEMINI_TEMPERATURE,
                "response_mime_type": "application/json",
            }

        print(f"[llm] Gemini client ready: {self.model_name}")

    def generate(self, system: str, user: str, max_retries: int = 3) -> Optional[Dict]:
        """
        Generate structured JSON response.
        Returns parsed dict, or None on failure.
        """
        if hasattr(self.client, "models"):
            current_config = types.GenerateContentConfig(
                max_output_tokens=self.config.max_output_tokens,
                temperature=self.config.temperature,
                response_mime_type=self.config.response_mime_type,
                system_instruction=system
            )
        else:
            current_config = self.config.copy()
            current_config["system_instruction"] = system

        for attempt in range(max_retries):
            try:
                if hasattr(self.client, "models"):
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=user,
                        config=current_config
                    )
                    text = response.text
                else:
                    response = self.client.generate_text(
                        model=self.model_name,
                        prompt=user,
                        **current_config
                    )
                    text = getattr(response, "result", None)

                if not text:
                    raise ValueError("Received empty response text from Gemini API")

                return json.loads(text)

            except APIError as ae:
                # Handle Google API specific errors (e.g., rate limits, quota)
                print(f"[llm] Gemini API Error (attempt {attempt+1}): {ae}")
                if attempt < max_retries - 1:
                    self._sleep_backoff(attempt)
            except Exception as e:
                print(f"[llm] generation failed (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    self._sleep_backoff(attempt)

        return None

    def _sleep_backoff(self, attempt: int):
        wait = 2 ** attempt
        print(f"[llm] retrying in {wait}s...")
        time.sleep(wait)


# === The SOC analyst prompt ===

SOC_ANALYST_SYSTEM = """You are a senior SOC analyst with 15 years of experience in incident response and threat detection. You work for a Security Operations Center that uses the MITRE ATT&CK framework.

Your job: investigate security events and produce structured incident analyses.

Guidelines:
- Be precise and evidence-based. Cite specific indicators from the event data.
- Map findings to MITRE ATT&CK technique IDs when applicable (e.g., T1110, T1078, T1059).
- Assess severity carefully. Critical = active compromise or imminent damage. High = strong indicators of attack. Medium = suspicious but inconclusive. Low = likely benign.
- Provide actionable remediation steps. Each step must be specific and executable.
- When the event data is ambiguous, say so explicitly. Do not fabricate findings.
- Output MUST be valid JSON matching the schema provided in the user prompt.
- Keep total response under 1500 words to fit context window.

You have access to a knowledge base of MITRE ATT&CK techniques, Sigma detection rules, Wazuh rules, and remediation playbooks. Use the provided reference material to ground your analysis."""


def build_soc_prompt(event: Dict, context: Dict, rag_chunks: List[Dict]) -> str:
    """
    Build the user prompt for SOC analysis.

    event: the triggering event
    context: correlated events, threat intel results
    rag_chunks: retrieved knowledge base chunks
    """
    # Format RAG chunks as reference material
    refs_text = ""
    for i, chunk in enumerate(rag_chunks, 1):
        meta = chunk.get("metadata", {})
        source = meta.get("source", "unknown")
        title = meta.get("technique_id") or meta.get("rule_id") or meta.get("file", f"ref-{i}")
        refs_text += f"\n[Reference {i}: {source}/{title}]\n{chunk.get('text', '')}\n"

    # Format correlated events
    corr_text = ""
    for ev in context.get("correlated_events", [])[:10]:
        corr_text += f"- {ev.get('timestamp', '?')}: {ev.get('event_type', '?')} from {ev.get('actor', {}).get('source_ip', '?')} user={ev.get('actor', {}).get('user', '?')}\n"

    threat_intel = context.get("threat_intel", {})

    return f"""Investigate the following security event and produce a structured analysis.

# TRIGGERING EVENT
```json
{json.dumps(event, indent=2)}
```

# CORRELATED EVENTS
{corr_text if corr_text else "None detected"}

# THREAT INTEL CONTEXT
{json.dumps(threat_intel, indent=2)}

# RETRIEVED REFERENCE MATERIAL
{refs_text if refs_text else "No specific references found"}
"""
