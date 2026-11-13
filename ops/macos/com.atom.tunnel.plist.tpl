<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.atom.tunnel</string>
  <key>ProgramArguments</key>
  <array>
    <string>__CLOUDFLARED__</string>
    <string>tunnel</string>
    <string>--no-autoupdate</string>
    <string>run</string>
    <string>--token</string>
    <string>__TUNNEL_TOKEN__</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>20</integer>
  <key>StandardOutPath</key>
  <string>__ATOM_LOGS__/tunnel.log</string>
  <key>StandardErrorPath</key>
  <string>__ATOM_LOGS__/tunnel.err.log</string>
</dict>
</plist>
