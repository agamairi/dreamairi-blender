# DreamAiri-blender 🌌

**DreamAiri** is a lightweight, secure Blender add-on that brings the power of Large Language Models (LLMs) directly into your 3D workflow. Generate low-poly models, prototype scenes, and explore ideas using natural language.

---

## ✨ Features

- **Multi-Provider Support**: Connect to Ollama (local), OpenRouter, OpenAI, or Google Gemini.
- **Security-First Architecture**: Uses a strict **Whitelist Tool Executor**. No arbitrary Python execution, ever.
- **Low-Poly Focused**: Built-in constraints for triangle budgets and efficient modifier stacks.
- **Developer Friendly**: Clean JSON-based operation contract and robust logging with automatic secret redaction.
- **Integrated Workflow**: Edit your prompts in Blender's Text Editor and see status updates in real-time.

## 🚀 Quick Start

1. **Install**: Download the repository, zip the `dreamairi_blender` folder, and install via `Edit > Preferences > Add-ons`.
2. **Setup**: Open the N-panel (press `N` in the 3D View) and select the **DreamAiri-blender** tab.
3. **Configure**: Select your provider and enter your API key.
4. **Generate**: Type a prompt like *"Create a low-poly bowling pin with a red ring"* and hit **Generate**.

## 🛡️ Security

DreamAiri is built to be safe for the community. We use a strictly whitelisted execution model to ensure that LLMs only perform authorized Blender operations. For more details, see [SECURITY.md](SECURITY.md).

## 🛠️ Testing

Keep the codebase stable with our integrated test suite.

**Unit Tests**:
```bash
python -m unittest discover -s tests
```

**Blender Integration (Headless)**:
```bash
blender --background --factory-startup --python tests/blender_integration.py
```

## 🤝 Contributing

Contributions are welcome! Whether it's adding new whitelisted tools, improving prompts, or fixing bugs, feel free to open a PR.

---
*Created with ❤️ for the Blender Community.*
