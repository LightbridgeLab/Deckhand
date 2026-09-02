import AppKit
import Foundation

// MARK: - Deckhand Menu Bar App
// Standalone lightweight macOS status bar item for Deckhand Core.
// Compile with: swiftc -O src/mac/DeckhandMenu.swift -o .deckhand/DeckhandMenu

enum IconStyle: String {
    case anchorBadge = "anchorBadge"
    case dotOnly = "dotOnly"
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var statusItem: NSStatusItem!
    private var menu: NSMenu!
    private var pollTimer: Timer?
    private var isOnline = false
    private var healthData: [String: Any]?
    private var projectDir: URL!

    // Header items
    private var statusMenuItem: NSMenuItem!
    private var detailsMenuItem: NSMenuItem!
    private var pluginsMenuItem: NSMenuItem!
    private var startMenuItem: NSMenuItem!
    private var stopMenuItem: NSMenuItem!
    private var restartMenuItem: NSMenuItem!
    private var openDashboardMenuItem: NSMenuItem!
    private var openDocsMenuItem: NSMenuItem!
    private var openGitHubMenuItem: NSMenuItem!
    private var viewLogsMenuItem: NSMenuItem!

    // Icon style items
    private var anchorBadgeMenuItem: NSMenuItem!
    private var dotOnlyMenuItem: NSMenuItem!

    private var iconStyle: IconStyle {
        get {
            let saved = UserDefaults.standard.string(forKey: "deckhand.iconStyle") ?? ""
            return IconStyle(rawValue: saved) ?? .anchorBadge
        }
        set {
            UserDefaults.standard.set(newValue.rawValue, forKey: "deckhand.iconStyle")
            updateButtonIcon()
            updateIconStyleMenu()
        }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Ensure no dock icon (runs purely in status bar)
        NSApplication.shared.setActivationPolicy(.accessory)

        // Resolve project directory
        projectDir = findProjectRoot()

        // Create status bar item
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.title = ""
            button.imagePosition = .imageOnly
            button.image = makeIcon(online: false)
            button.toolTip = "Deckhand Core"
        }

        buildMenu()
        statusItem.menu = menu

        // Immediate check: if Core is not running on initial launch, auto-start it
        checkHealth { [weak self] online in
            if !online {
                self?.startService()
            }
        }
        pollTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            self?.checkHealth()
        }
    }

    // MARK: - Project Directory Discovery

    private func findProjectRoot() -> URL {
        if let envRoot = ProcessInfo.processInfo.environment["DECKHAND_ROOT"],
           FileManager.default.fileExists(atPath: "\(envRoot)/Makefile") {
            return URL(fileURLWithPath: envRoot)
        }

        // Check current working directory
        let cwd = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        if FileManager.default.fileExists(atPath: cwd.appendingPathComponent("Makefile").path) {
            return cwd
        }

        // Check executable parent directories
        var searchURL = URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
        for _ in 0..<4 {
            if FileManager.default.fileExists(atPath: searchURL.appendingPathComponent("Makefile").path) {
                return searchURL
            }
            searchURL = searchURL.deletingLastPathComponent()
        }

        // Fallback default
        return URL(fileURLWithPath: "/Users/sebastien/dev/projects/Deckhand")
    }

    // MARK: - Core URL Discovery

    private func getBaseURL() -> URL {
        let runtimePath = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/deckhand/runtime.toml").path
        if let content = try? String(contentsOfFile: runtimePath, encoding: .utf8) {
            for line in content.components(separatedBy: .newlines) {
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                if trimmed.hasPrefix("url =") {
                    let parts = trimmed.components(separatedBy: "\"")
                    if parts.count >= 2, let parsedURL = URL(string: parts[1]) {
                        return parsedURL
                    }
                }
            }
        }
        return URL(string: "http://127.0.0.1:18765")!
    }

    // MARK: - Menu Setup

    private func buildMenu() {
        menu = NSMenu()
        menu.autoenablesItems = false
        menu.delegate = self

        // Status line: high-contrast header, non-clickable
        statusMenuItem = NSMenuItem()
        statusMenuItem.target = nil
        statusMenuItem.action = nil
        statusMenuItem.isEnabled = true
        menu.addItem(statusMenuItem)

        // Subtitle line: details (plugins, clients, uptime), non-clickable
        detailsMenuItem = NSMenuItem()
        detailsMenuItem.target = nil
        detailsMenuItem.action = nil
        detailsMenuItem.isEnabled = true
        detailsMenuItem.isHidden = true
        menu.addItem(detailsMenuItem)

        // Active plugins line, non-clickable
        pluginsMenuItem = NSMenuItem()
        pluginsMenuItem.target = nil
        pluginsMenuItem.action = nil
        pluginsMenuItem.isEnabled = true
        pluginsMenuItem.isHidden = true
        menu.addItem(pluginsMenuItem)

        menu.addItem(NSMenuItem.separator())

        // Service actions
        startMenuItem = NSMenuItem(title: "Start Service", action: #selector(startService), keyEquivalent: "")
        startMenuItem.target = self
        menu.addItem(startMenuItem)

        stopMenuItem = NSMenuItem(title: "Stop Service", action: #selector(stopService), keyEquivalent: "")
        stopMenuItem.target = self
        stopMenuItem.isHidden = true
        menu.addItem(stopMenuItem)

        restartMenuItem = NSMenuItem(title: "Restart Service", action: #selector(restartService), keyEquivalent: "")
        restartMenuItem.target = self
        restartMenuItem.isHidden = true
        menu.addItem(restartMenuItem)

        menu.addItem(NSMenuItem.separator())

        // Web and Docs
        openDashboardMenuItem = NSMenuItem(title: "Open Web Dashboard", action: #selector(openWebDashboard), keyEquivalent: "")
        openDashboardMenuItem.target = self
        menu.addItem(openDashboardMenuItem)

        openDocsMenuItem = NSMenuItem(title: "API Documentation (/docs)", action: #selector(openDocsInBrowser), keyEquivalent: "")
        openDocsMenuItem.target = self
        menu.addItem(openDocsMenuItem)

        openGitHubMenuItem = NSMenuItem(title: "Documentation (GitHub)", action: #selector(openGitHubInBrowser), keyEquivalent: "")
        openGitHubMenuItem.target = self
        menu.addItem(openGitHubMenuItem)

        viewLogsMenuItem = NSMenuItem(title: "View Logs", action: #selector(viewLogs), keyEquivalent: "")
        viewLogsMenuItem.target = self
        menu.addItem(viewLogsMenuItem)

        menu.addItem(NSMenuItem.separator())

        // NOTE: Icon Style toggle commented out for now to keep the menu interface as clean as possible.
        // Clean up / remove this code later if users never express interest in custom icon styles.
        /*
        let iconStyleParent = NSMenuItem(title: "Menu Bar Icon", action: nil, keyEquivalent: "")
        let iconSubmenu = NSMenu()
        iconSubmenu.autoenablesItems = false

        anchorBadgeMenuItem = NSMenuItem(title: "Anchor with Status Badge", action: #selector(selectAnchorBadgeStyle), keyEquivalent: "")
        anchorBadgeMenuItem.target = self
        iconSubmenu.addItem(anchorBadgeMenuItem)

        dotOnlyMenuItem = NSMenuItem(title: "Status Dot Only", action: #selector(selectDotOnlyStyle), keyEquivalent: "")
        dotOnlyMenuItem.target = self
        iconSubmenu.addItem(dotOnlyMenuItem)

        iconStyleParent.submenu = iconSubmenu
        menu.addItem(iconStyleParent)
        updateIconStyleMenu()

        menu.addItem(NSMenuItem.separator())
        */

        // Quit
        let quitMenuItem = NSMenuItem(title: "Quit Deckhand", action: #selector(quitApp), keyEquivalent: "q")
        quitMenuItem.target = self
        menu.addItem(quitMenuItem)

        // Initial appearance
        applyStatusHeader(online: false)
    }

    private func updateIconStyleMenu() {
        guard anchorBadgeMenuItem != nil, dotOnlyMenuItem != nil else { return }
        let style = iconStyle
        anchorBadgeMenuItem.state = (style == .anchorBadge) ? .on : .off
        dotOnlyMenuItem.state = (style == .dotOnly) ? .on : .off
    }

    @objc private func selectAnchorBadgeStyle() {
        iconStyle = .anchorBadge
    }

    @objc private func selectDotOnlyStyle() {
        iconStyle = .dotOnly
    }

    // MARK: - Icon Generation

    private func makeIcon(online: Bool) -> NSImage {
        switch iconStyle {
        case .anchorBadge:
            return makeAnchorBadgeIcon(online: online)
        case .dotOnly:
            return makeDotOnlyIcon(online: online)
        }
    }

    private func updateButtonIcon() {
        if let button = statusItem.button {
            button.image = makeIcon(online: isOnline)
        }
    }

    private func makeAnchorBadgeIcon(online: Bool) -> NSImage {
        let size = NSSize(width: 18, height: 18)
        let image = NSImage(size: size, flipped: false) { rect in
            // Draw anchor
            let str = "⚓️" as NSString
            let font = NSFont.systemFont(ofSize: 13)
            let attr: [NSAttributedString.Key: Any] = [.font: font]
            let strSize = str.size(withAttributes: attr)
            let pt = NSPoint(
                x: (rect.width - strSize.width) / 2 - 1,
                y: (rect.height - strSize.height) / 2
            )
            str.draw(at: pt, withAttributes: attr)

            // Draw integrated status badge in bottom-right corner with background cutout
            let bgRect = NSRect(x: 9.5, y: 0.5, width: 8.0, height: 8.0)
            let bgPath = NSBezierPath(ovalIn: bgRect)
            NSColor.windowBackgroundColor.setFill()
            bgPath.fill()

            let dotRect = NSRect(x: 10.5, y: 1.5, width: 6.0, height: 6.0)
            let dotPath = NSBezierPath(ovalIn: dotRect)
            (online ? NSColor.systemGreen : NSColor.systemGray).setFill()
            dotPath.fill()

            return true
        }
        image.isTemplate = false
        return image
    }

    private func makeDotOnlyIcon(online: Bool) -> NSImage {
        if let symbol = NSImage(systemSymbolName: "circle.fill", accessibilityDescription: "Deckhand") {
            let config = NSImage.SymbolConfiguration(paletteColors: [online ? .systemGreen : .systemGray])
            if let tinted = symbol.withSymbolConfiguration(config) {
                return tinted
            }
        }
        let size = NSSize(width: 16, height: 16)
        let image = NSImage(size: size, flipped: false) { rect in
            let dotRect = NSRect(x: 3.5, y: 3.5, width: 9.0, height: 9.0)
            let dotPath = NSBezierPath(ovalIn: dotRect)
            (online ? NSColor.systemGreen : NSColor.systemGray).setFill()
            dotPath.fill()
            return true
        }
        image.isTemplate = false
        return image
    }

    // MARK: - Health Polling

    private func checkHealth(completion: ((Bool) -> Void)? = nil) {
        let baseURL = getBaseURL()
        let healthURL = baseURL.appendingPathComponent("health")

        var request = URLRequest(url: healthURL)
        request.timeoutInterval = 1.5

        let task = URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self = self else { return }
                let online = (response as? HTTPURLResponse)?.statusCode == 200
                if online,
                   let data = data,
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    self.updateStatus(online: true, baseURL: baseURL, data: json)
                } else {
                    self.updateStatus(online: false, baseURL: baseURL, data: nil)
                }
                completion?(online)
            }
        }
        task.resume()
    }

    private func applyStatusHeader(online: Bool) {
        let prefix = "Deckhand status: "
        let statusWord = online ? "Running" : "Stopped"
        let fullText = "\(prefix)\(statusWord)"
        let attr = NSMutableAttributedString(string: fullText)
        let fullRange = NSRange(location: 0, length: fullText.utf16.count)
        let statusRange = (fullText as NSString).range(of: statusWord)

        attr.addAttribute(.font, value: NSFont.boldSystemFont(ofSize: 13), range: fullRange)
        attr.addAttribute(.foregroundColor, value: NSColor.labelColor, range: fullRange)

        if online {
            attr.addAttribute(.foregroundColor, value: NSColor.systemGreen, range: statusRange)
        } else {
            attr.addAttribute(.foregroundColor, value: NSColor.systemRed, range: statusRange)
        }
        statusMenuItem.attributedTitle = attr
    }

    private func updateStatus(online: Bool, baseURL: URL, data: [String: Any]?) {
        isOnline = online
        healthData = data

        updateButtonIcon()
        applyStatusHeader(online: online)

        if online {
            // Service controls: hide Start, show Stop & Restart
            startMenuItem.isHidden = true
            stopMenuItem.isHidden = false
            restartMenuItem.isHidden = false

            openDashboardMenuItem.isEnabled = true
            openDocsMenuItem.isEnabled = true

            if let dict = data {
                let uptime = Int(dict["uptime_seconds"] as? Double ?? 0)
                let clients = dict["websocket_clients"] as? Int ?? 0
                let agentsDict = dict["agents"] as? [String: Any]
                let agentCount = agentsDict?["count"] as? Int ?? 0
                let pluginsDict = dict["plugins"] as? [String: Any]
                let pluginModules = pluginsDict?["modules"] as? [String] ?? []
                let pluginCount = pluginModules.count

                let uptimeStr = formatUptime(uptime)
                var parts: [String] = []
                if pluginCount > 0 {
                    parts.append("Plugins: \(pluginCount)")
                }
                parts.append("Clients: \(clients)")
                if agentCount > 0 {
                    parts.append("Agents: \(agentCount)")
                }
                parts.append("Uptime: \(uptimeStr)")

                let detailsText = parts.joined(separator: "  •  ")
                let detailsAttr = NSAttributedString(
                    string: detailsText,
                    attributes: [
                        .font: NSFont.systemFont(ofSize: 11),
                        .foregroundColor: NSColor.secondaryLabelColor
                    ]
                )
                detailsMenuItem.attributedTitle = detailsAttr
                detailsMenuItem.isHidden = false

                // Active plugins breakdown
                if !pluginModules.isEmpty {
                    let cleanNames = pluginModules.map { mod in
                        mod.replacingOccurrences(of: "deckhand.plugins.", with: "")
                            .replacingOccurrences(of: "_usage", with: "")
                            .replacingOccurrences(of: "_", with: " ")
                            .capitalized
                    }.joined(separator: ", ")

                    let pluginText = "Active Usage: \(cleanNames)"
                    pluginsMenuItem.attributedTitle = NSAttributedString(
                        string: pluginText,
                        attributes: [
                            .font: NSFont.systemFont(ofSize: 11),
                            .foregroundColor: NSColor.secondaryLabelColor
                        ]
                    )
                    pluginsMenuItem.isHidden = false
                } else {
                    pluginsMenuItem.isHidden = true
                }
            }
        } else {
            // Service controls: show Start, hide Stop & Restart
            detailsMenuItem.isHidden = true
            pluginsMenuItem.isHidden = true
            startMenuItem.isHidden = false
            stopMenuItem.isHidden = true
            restartMenuItem.isHidden = true

            openDashboardMenuItem.isEnabled = false
            openDocsMenuItem.isEnabled = false
        }
    }

    private func formatUptime(_ seconds: Int) -> String {
        if seconds < 60 { return "\(seconds)s" }
        let mins = seconds / 60
        if mins < 60 { return "\(mins)m" }
        let hours = mins / 60
        return "\(hours)h \(mins % 60)m"
    }

    // MARK: - Actions

    @objc private func startService() {
        runMakeCommand("start")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            self?.checkHealth()
        }
    }

    @objc private func stopService() {
        runMakeCommand("stop")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in
            self?.checkHealth()
        }
    }

    @objc private func restartService() {
        runMakeCommand("restart")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            self?.checkHealth()
        }
    }

    @objc private func openWebDashboard() {
        let baseURL = getBaseURL()
        NSWorkspace.shared.open(baseURL)
    }

    @objc private func openDocsInBrowser() {
        let baseURL = getBaseURL()
        let docsURL = baseURL.appendingPathComponent("docs")
        NSWorkspace.shared.open(docsURL)
    }

    @objc private func openGitHubInBrowser() {
        if let url = URL(string: "https://github.com/LightbridgeLab/Deckhand") {
            NSWorkspace.shared.open(url)
        }
    }

    @objc private func viewLogs() {
        let logPath = projectDir.appendingPathComponent(".deckhand/server.log").path
        if FileManager.default.fileExists(atPath: logPath) {
            NSWorkspace.shared.open(URL(fileURLWithPath: logPath))
        } else {
            let alert = NSAlert()
            alert.messageText = "No Log File Found"
            alert.informativeText = "The log file at \(logPath) does not exist yet. Start the service first."
            alert.runModal()
        }
    }

    @objc private func quitApp() {
        if isOnline {
            runMakeCommand("stop")
        }
        NSApplication.shared.terminate(nil)
    }

    // MARK: - Shell Runner

    private func runMakeCommand(_ target: String) {
        let process = Process()
        process.currentDirectoryURL = projectDir
        process.executableURL = URL(fileURLWithPath: "/usr/bin/make")
        process.arguments = [target]

        // Ensure PATH includes uv, homebrew, cargo, etc.
        var env = ProcessInfo.processInfo.environment
        let extraPaths = "/opt/homebrew/bin:/usr/local/bin:\(NSHomeDirectory())/.local/bin:\(NSHomeDirectory())/.cargo/bin"
        if let existing = env["PATH"] {
            env["PATH"] = "\(extraPaths):\(existing)"
        } else {
            env["PATH"] = "\(extraPaths):/usr/bin:/bin:/usr/sbin:/sbin"
        }
        process.environment = env

        do {
            try process.run()
        } catch {
            print("Failed to run make \(target): \(error)")
        }
    }
}

// MARK: - Main Entry Point

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
