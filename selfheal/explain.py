"""Root-cause explanation. Uses an LLM if ANTHROPIC_API_KEY is set (the 'LLM' in LLM+RAG),
otherwise falls back to a deterministic template so the demo works fully offline."""
import os


def template(inc):
    kb = inc["kb_matches"][0] if inc["kb_matches"] else None
    s = (f"Root cause: '{inc['root']}' ({inc['failure_type']}, confidence {inc['confidence']:.0%}). "
         f"Symptoms: {inc['symptoms']}. ")
    if inc["affected"]:
        s += f"Impact propagated to {', '.join(inc['affected'])} via the dependency graph"
        if inc["correlation"]:
            s += " (latency correlation " + ", ".join(f"{k}={v}" for k, v in inc["correlation"].items()) + ")"
        s += ". "
    if inc.get("logs"):
        s += "Log evidence: " + "; ".join(inc["logs"][:2]) + ". "
    if kb:
        s += f"Most similar past incident {kb['id']} (similarity {kb['similarity']}) was fixed by '{kb['action']}'. "
    s += f"Recommended action: {inc['action']}."
    return s


def explain(inc):
    base = template(inc)
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return base, "template"
    try:  # optional LLM path
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=os.environ.get("LLM_MODEL", "claude-sonnet-5-5"), max_tokens=250,
            messages=[{"role": "user", "content":
                       "You are an SRE assistant. In 3 sentences, explain this incident to an on-call engineer.\n" + base}])
        return msg.content[0].text, "llm"
    except Exception as e:  # never let the explainer break healing
        return base + f" (LLM unavailable: {type(e).__name__})", "template"
