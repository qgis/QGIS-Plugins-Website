
#!/usr/bin/env bash
echo "🪛 Installing VSCode Extensions:"
echo "--------------------------------"


# Ensure .vscode directory exists
mkdir -p .vscode
mkdir -p .vscode-extensions
# Define the settings.json file path
SETTINGS_FILE=".vscode/settings.json"

# Ensure settings.json exists
if [[ ! -f "$SETTINGS_FILE" ]]; then
    echo "{}" > "$SETTINGS_FILE"
fi

# Update settings.json non-destructively
echo "Updating VSCode settings.json..."
jq '.["git.enableCommitSigning"] = true' \
   "$SETTINGS_FILE" > "$SETTINGS_FILE.tmp" && mv "$SETTINGS_FILE.tmp" "$SETTINGS_FILE"

echo "✅ VSCode settings.json updated successfully!"
echo "Contents of settings.json:"
cat "$SETTINGS_FILE"

# Install required extensions
code --user-data-dir='.vscode' \
--profile='nix-config' \
--extensions-dir='.vscode-extensions' . \
--install-extension ms-vscode-remote.remote-wsl@0.99.0 \
--install-extension ms-vscode.remote-server@1.5.2 \
--install-extension ms-vscode-remote.remote-ssh@0.120.0 \
--install-extension ms-vscode-remote.remote-containers@0.413.0 \
--install-extension batisteo.vscode-django@1.15.0 \
--install-extension zhuangtongfa.material-theme@3.19.0 \
--install-extension naumovs.color-highlight@2.8.0 \
--install-extension GitHub.copilot@1.250.0 \
--install-extension ms-vscode.remote-explorer@0.5.0 \
--install-extension teabyii.ayu@1.0.5 \
--install-extension ms-python.debugpy@2025.8.0 \
--install-extension ms-python.vscode-pylance@2025.5.1 \
--install-extension GitHub.copilot-chat@0.27.3 \
--install-extension ms-python.python@2025.6.1 \
--install-extension ms-vscode-remote.remote-ssh-edit@0.87.0 \
--install-extension ms-vscode-remote.vscode-remote-extensionpack@0.26.0 \
--install-extension syler.sass-indented@1.8.33 \
--install-extension eamodio.gitlens@17.1.1 \

# Launch VSCode with the sandboxed environment
code --user-data-dir='.vscode' \
--profile='nix-config' \
--extensions-dir='.vscode-extensions' .
