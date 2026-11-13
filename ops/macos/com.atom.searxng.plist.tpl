<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.atom.searxng</string>
  <key>WorkingDirectory</key>
  <string>__ATOM_HOME__</string>
  <key>ProgramArguments</key>
  <array>
    <string>__DOCKER__</string>
    <string>compose</string>
    <string>-f</string>
    <string>__ATOM_HOME__/docker-compose.searxng.yml</string>
    <string>up</string>
    <string>--abort-on-container-exit</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>__ATOM_LOGS__/searxng.out.log</string>
  <key>StandardErrorPath</key>
  <string>__ATOM_LOGS__/searxng.err.log</string>
</dict>
</plist>
