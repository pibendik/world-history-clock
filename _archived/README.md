# Archived Code

## clock.py / clock_rich.py

The original terminal prototypes. `clock.py` is a minimal ANSI terminal clock;
`clock_rich.py` is a polished version using the `rich` library with live layout,
colour-coded eras and a spinner. Both were superseded by the PWA + FastAPI backend.

`requirements.txt` here lists the terminal prototype dependencies.

## flutter_app/

The Flutter client was archived in favour of the PWA web app.

The PWA (`web/index.html`) covers the same use cases and is installable on Android/iOS
via "Add to Home Screen" without requiring a native build pipeline.

If native platform widgets (home screen clock widget, lock screen widget) are needed in the future,
the core business logic lives in the FastAPI service — the Flutter client can be restored
and wired to the `/api/v1/year/{year}` endpoint with minimal code.

