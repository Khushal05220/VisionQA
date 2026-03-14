# 🔭 VisionQA – Voice Controlled Multimodal Visual QA Agent

A production-level AI agent system for visual website testing using voice commands, Google ADK, Gemini multimodal AI, and browser automation.

## ✨ Features

- **🎤 Voice Control** – Speak commands like "Test the login page" using Web Speech API
- **🤖 ADK Agent System** – Multi-tool agentic AI that autonomously decides actions
- **👁️ Visual UI Understanding** – Uses Gemini vision to understand screenshots (NO DOM selectors)
- **📋 Auto Test Planning** – AI generates comprehensive test plans from natural language
- **🎬 Live Browser Testing** – Watch the agent interact with websites in real-time
- **💾 Persistent Storage** – Test cases, results, and plans stored in Firestore
- **📸 Screenshot Capture** – Visual evidence at every test step
- **🔄 WebSocket Streaming** – Real-time logs, actions, and screenshots in the dashboard
- **☁️ Cloud Ready** – Deployable to Google Cloud Run

## 🏗️ Architecture

```
User Voice → Speech-to-Text → Frontend Dashboard → WebSocket → FastAPI Backend
                                                                    ↓
                                                              ADK Agent
                                                                    ↓
                                                    ┌───────────────┼───────────────┐
                                                    ↓               ↓               ↓
                                                Planner         Executor        Verifier
                                                    ↓               ↓               ↓
                                              Gemini AI      Playwright       Gemini Vision
                                                    ↓               ↓               ↓
                                              Test Plans      Browser Actions   Visual Checks
                                                    ↓               ↓               ↓
                                                        Firestore / Cloud Storage
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Google API Key (for Gemini)
- Playwright browsers

### Installation

```bash
cd visionqa

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Copy environment template
copy .env.example .env
# Edit .env with your Google API key
```

### Running Locally

```bash
# Set Python path
set PYTHONPATH=.  # Windows
# export PYTHONPATH=.  # macOS/Linux

# Start the server
uvicorn visionqa.backend.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 in your browser to access the dashboard.

## 🎤 Voice Commands

| Command | What It Does |
|---------|-------------|
| "Open https://example.com" | Navigates to the URL |
| "Test this page" | Runs visual analysis and testing |
| "Create test cases for login page" | Generates structured test cases |
| "Save test cases" | Persists test cases to Firestore |
| "Run test plan" | Executes all steps in a test plan |
| "Check if dashboard loads" | Visual verification |
| "Take a screenshot" | Captures current page state |

## 🛠️ Agent Tools

The agent has 11 tools it can use autonomously:

| Tool | Description |
|------|-------------|
| `open_page` | Navigate to a URL |
| `take_screenshot` | Capture page screenshot |
| `analyze_ui` | Identify UI elements visually |
| `click` | Click by visual description |
| `type_text` | Type into visually identified fields |
| `verify_screen` | Verify screen matches expected state |
| `save_test_case` | Save test case to database |
| `create_test_plan` | Generate AI test plan |
| `run_test_plan` | Execute a saved test plan |
| `press_key` | Press keyboard keys |
| `scroll` | Scroll the page |

## 📡 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/command` | Send text command to agent |
| POST | `/api/voice` | Send voice transcript |
| POST | `/api/test/workflow` | Run full test workflow |
| POST | `/api/agent/reset` | Reset agent session |
| GET | `/api/test-cases` | List test cases |
| GET | `/api/test-plans` | List test plans |
| GET | `/api/test-results` | List test results |
| WS | `/ws/{session_id}` | WebSocket for live streaming |

## ☁️ Cloud Deployment

### Google Cloud Run

```bash
cd deploy

# Build container
gcloud builds submit --tag gcr.io/YOUR_PROJECT/visionqa

# Deploy to Cloud Run
gcloud run deploy visionqa \
  --image gcr.io/YOUR_PROJECT/visionqa \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --set-env-vars "GOOGLE_API_KEY=your_key,BROWSER_HEADLESS=true"
```

## 📁 Project Structure

```
visionqa/
├── backend/
│   ├── main.py              # FastAPI app with all endpoints
│   ├── websocket.py          # WebSocket manager
│   └── config.py             # Configuration management
├── agent/
│   ├── agent.py              # Root ADK agent with tools
│   ├── planner.py            # Test plan generation sub-agent
│   ├── executor.py           # Test execution sub-agent
│   ├── orchestrator.py       # High-level orchestration
│   └── prompts.py            # System prompts
├── tools/
│   ├── browser_tool.py       # Playwright automation
│   ├── screenshot_tool.py    # Screenshot capture & storage
│   ├── gemini_tool.py        # Gemini multimodal analysis
│   ├── verify_tool.py        # Visual verification
│   └── speech_tool.py        # Speech processing
├── services/
│   ├── test_manager.py       # Test CRUD operations
│   └── plan_generator.py     # AI test plan generation
├── database/
│   └── firestore_client.py   # Firestore + local fallback
├── frontend/
│   ├── index.html            # Dashboard UI
│   ├── styles.css            # Premium dark theme
│   └── app.js                # Frontend logic
├── deploy/
│   ├── Dockerfile            # Cloud Run deployment
│   └── .dockerignore
├── requirements.txt
├── .env.example
└── README.md
```

## 📄 License

MIT
