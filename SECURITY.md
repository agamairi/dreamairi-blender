# Security Policy

## Overview

DreamAiri-blender is designed with a "Security-First" approach to LLM-generated content. We assume LLM output may be untrusted or malformed.

## Threat Model & Protections

### 1. Arbitrary Code Execution
**Protection**: DreamAiri **never** uses `exec()` or `eval()` on LLM output. Instead, it uses a strict **Whitelist Tool Executor**. The LLM produces JSON instructions which are mapped to specific, verified Blender Python API calls.

### 2. Secret Exposure
**Protection**: 
- All logs are passed through a regex-based **Sanitizer** that redacts API keys, Bearer tokens, and sensitive headers.
- API keys can be stored temporarily in memory or in Blender's secure `AddonPreferences` (user choice).

### 3. Mesh Overload
**Protection**: 
- All generated meshes are checked against a user-defined **Triangle Budget**.
- If a mesh exceeds the budget, an automatic Decimate modifier is applied and applied to bring it within limits.
- Hard caps are enforced on expensive modifiers like Subdivision Surface (max level 2).

## Reporting a Vulnerability

If you discover a security vulnerability within this project, please open a GitHub Issue or reach out via [your preferred contact]. We take all reports seriously and will investigate promptly.
