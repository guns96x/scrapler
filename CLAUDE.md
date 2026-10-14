# Scrapler Project Guidelines for Claude

@C:\Users\pavlo\.claude\WORKERS.md

## Video Generation via Google AI Pro ($0 API Cost)

Whenever asked to create, render, or generate video, invoke the local Google AI Video Bridge:

```powershell
powershell -ExecutionPolicy Bypass -File "$HOME\.gemini\config\scripts\Invoke-GoogleVideo.ps1" -Prompt "<cinematic scene description>" -OutputFile "<output.mp4>"
```
Do not attempt to use third-party paid video APIs.
