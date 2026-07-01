"""rtlagent — an agentic RTL optimization harness on open-source EDA.

Reproduces the methodology of Dr.RTL (agentic timing optimization) and
MasterRTL (pre-synthesis PPA proxy) with yosys/Icarus, and adds an improved
harness (parallel candidates + proxy pre-ranking + skill memory) with
pluggable LLM backends (Anthropic, GLM, any OpenAI-compatible endpoint).
"""

__version__ = "0.1.0"
