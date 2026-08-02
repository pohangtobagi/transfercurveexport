# FET Analysis v59

Each project is now an independent workspace.

Per-project isolated state:
- Uploaded Excel file bytes and filename
- Active saved log ID
- Upload/log source mode
- File uploader generation
- Selected worksheet
- Device Information
- Existing direction/sliders/log analysis state

Switching projects snapshots the current project and loads only the selected
project's file and log workspace. Uploading or editing a file in one project
does not affect any other project.
