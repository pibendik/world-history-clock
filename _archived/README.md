# Archived Code

## flutter_app/
The Flutter client was archived in favour of the PWA web app.

The PWA (`clockapp/web/index.html`) covers the same use cases and is installable on Android/iOS
via "Add to Home Screen" without requiring a native build pipeline.

If native platform widgets (home screen clock widget, lock screen widget) are needed in the future,
the core business logic should live in the FastAPI service — the Flutter client can be restored
and wired to the `/api/v1/year/{year}` endpoint with minimal code.

The Flutter spec/implementation is preserved here for reference.
