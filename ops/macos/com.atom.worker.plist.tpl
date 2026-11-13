<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.atom.worker</string>
  <key>WorkingDirectory</key>
  <string>__ATOM_HOME__/backend</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    <key>ATOM_WORKER_REGIME</key>
    <string>1</string>
    <key>ATOM_WORKER_CLIENT</key>
    <string>1</string>
  </dict>
  <key>ProgramArguments</key>
  <array>
    <string>__ATOM_HOME__/backend/venv/bin/python</string>
    <string>-m</string>
    <string>app.services.client_worker</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>15</integer>
  <key>StandardOutPath</key>
  <string>__ATOM_LOGS__/worker.log</string>
  <key>StandardErrorPath</key>
  <string>__ATOM_LOGS__/worker.err.log</string>
</dict>
</plist>
