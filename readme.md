# 🛰️ Telegravity: Zero-Trust Autonomous Bridge

## Project Overview
Telegravity is an ultra-secure, remote Concierge Agent built for the **Kaggle 5-Day AI Agents Intensive**. It bridges a mobile Telegram Bot interface directly to a local execution environment via the `google-antigravity` SDK. It allows System Administrators and Developers to perform complex Vibe Coding, debugging, and server management entirely through natural language on the go.

## Core Architecture (The 3 Components)

### 1. Three-Tier Security Pipeline & Human-in-the-Loop (Guardrails)
Allowing an LLM to execute bash commands remotely is inherently dangerous. Telegravity implements a "Defense in Depth" pipeline:
* **Tier 1 (Static Analyzer):** A Python regex blocklist instantly terminates critical threat patterns (e.g., `rm -rf /`).
* **Tier 2 (LLM-as-a-Judge):** A secondary semantic guardrail (isolated Antigravity Agent) evaluates the context. If the AI Judge detects destructive intent, execution is blocked.
* **Tier 3 (HitL):** Validated tool calls are halted pending explicit cryptographic approval via an `[Approve] / [Deny]` Telegram Inline Keyboard. Zero actions hit the host system unverified.

### 2. Dual-Tier Memory Architecture (Zero Context Bloat)
Traditional bots force-feed huge chat histories into every prompt. Telegravity uses two elegant layers:
* **Short-Term Stateful Session:** Using Antigravity SDK's native session management, context is held in RAM without redundant token consumption.
* **Automated Skill Synthesis (Long-Term):** Following successful executions, a background Reflection Loop analyzes the session. If it detects a valuable workaround, it autonomously writes a `.md` guide to a persistent `skills/` directory, allowing the agent to continuously learn without hardcoding.

### 3. Native Tool Calling & Payload Management
The agent acts as an autonomous shell operator, generating tool calls via `<EXECUTE>` XML blocks. The Python bridge securely executes them locally via subprocess and manages payload constraints. If a command generates massive logs, Telegravity intercepts the overflow and converts it into a downloadable document file, optimizing the mobile UX.

## Setup Instructions

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create a .env file and secure your environment
echo "TELEGRAM_BOT_TOKEN=your_bot_token" >> .env
echo "ALLOWED_USER_ID=123456789" >> .env # MANDATORY: Your Telegram ID

# 3. Launch the bridge
python telegravity.py
