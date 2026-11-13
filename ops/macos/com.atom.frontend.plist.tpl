<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.atom.frontend</string>
  <key>WorkingDirectory</key>
  <string>__ATOM_HOME__</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>npx</string>
    <string>--yes</string>
    <string>serve</string>
    <string>-s</string>
    <string>dist</string>
    <string>-l</string>
    <string>4173</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>__ATOM_LOGS__/frontend.log</string>
  <key>StandardErrorPath</key>
  <string>__ATOM_LOGS__/frontend.err.log</string>
</dict>
</plist>
