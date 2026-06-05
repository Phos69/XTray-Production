using System.Drawing;
using System.IO;
using System.Text.Json;
using System.Windows;
using XTray.Tray.Backend;
using XTray.Tray.Infrastructure;
using XTray.Tray.UI;
using Forms = System.Windows.Forms;
using MessageBox = System.Windows.MessageBox;
using WpfApplication = System.Windows.Application;

namespace XTray.Tray;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Any(arg => string.Equals(arg, "--cli", StringComparison.OrdinalIgnoreCase)))
        {
            ConsoleBridge.AttachToParent();
            return BackendLocator.RunCli(args);
        }

        using var guard = new SingleInstanceGuard();
        if (!guard.TryAcquire())
        {
            return 0;
        }

        var app = new WpfApplication { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        TrayCrashLogger.Configure(app);
        try
        {
            using var backend = new JsonRpcClient();
            using var tray = new TrayApplication(app, backend);
            var exitCode = app.Run();
            TrayCrashLogger.MarkCleanShutdown();
            return exitCode;
        }
        catch (Exception ex)
        {
            TrayCrashLogger.LogCrash("main loop exception", ex);
            MessageBox.Show(
                ex.Message,
                "XTray",
                MessageBoxButton.OK,
                MessageBoxImage.Error
            );
            return 1;
        }
    }
}

internal sealed class TrayApplication : IDisposable
{
    private readonly WpfApplication _app;
    private readonly JsonRpcClient _backend;
    private readonly Forms.NotifyIcon _notifyIcon;
    private readonly GlobalHotkeyPoller _hotkeyPoller;
    private TrayPopupWindow? _popup;
    private OptionsWindow? _options;
    private bool _disposed;

    public TrayApplication(WpfApplication app, JsonRpcClient backend)
    {
        _app = app;
        _backend = backend;
        _notifyIcon = CreateNotifyIcon();
        _hotkeyPoller = new GlobalHotkeyPoller(() => _ = TogglePopupAsync());
        _hotkeyPoller.Update(enabled: true, sequence: "Ctrl+Alt+X");
        _ = InitializeAsync();
    }

    private Forms.NotifyIcon CreateNotifyIcon()
    {
        var icon = LoadIcon();
        var notifyIcon = new Forms.NotifyIcon
        {
            Text = "XTray",
            Icon = icon,
            Visible = true,
            ContextMenuStrip = BuildMenu(),
        };
        notifyIcon.MouseUp += (_, args) =>
        {
            if (args.Button == Forms.MouseButtons.Left)
            {
                _ = ShowPopupAsync();
            }
        };
        notifyIcon.DoubleClick += (_, _) => _ = ShowPopupAsync();
        return notifyIcon;
    }

    private Forms.ContextMenuStrip BuildMenu()
    {
        var menu = new Forms.ContextMenuStrip();
        menu.Items.Add(MenuItem("Open XTray", () => ShowPopupAsync()));
        menu.Items.Add(MenuItem("Options", () => ShowOptionsAsync()));
        menu.Items.Add(new Forms.ToolStripSeparator());
        menu.Items.Add(MenuItem("Computer Manager", () => CallBackendAsync("app.open_computer_manager")));
        menu.Items.Add(MenuItem("Network Manager", () => CallBackendAsync("app.open_network_manager")));
        menu.Items.Add(MenuItem("Import From LAN PC", () => ImportFromLanAsync()));
        menu.Items.Add(new Forms.ToolStripSeparator());
        menu.Items.Add(MenuItem("Check For Updates", () => CheckUpdatesAsync()));
        menu.Items.Add(MenuItem("Diagnostics ZIP", () => DiagnosticsAsync()));
        menu.Items.Add(MenuItem("Open Logs", () => CallBackendAsync("app.open_logs")));
        menu.Items.Add(MenuItem("Restart Backend", () => RestartBackendAsync()));
        menu.Items.Add(new Forms.ToolStripSeparator());
        menu.Items.Add(MenuItem("Quit", QuitAsync));
        return menu;
    }

    private static Forms.ToolStripMenuItem MenuItem(string text, Func<Task> action)
    {
        var item = new Forms.ToolStripMenuItem(text);
        item.Click += async (_, _) =>
        {
            try
            {
                await action();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.Message, "XTray", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        };
        return item;
    }

    private async Task InitializeAsync()
    {
        try
        {
            var snapshot = new TraySnapshot(
                await _backend.CallAsync("settings.get", timeout: TimeSpan.FromSeconds(10))
            );
            var hotkeys = snapshot.Root.ObjectOrEmpty("hotkeys");
            _hotkeyPoller.Update(
                hotkeys.BoolOr("toggle_panel_enabled", true),
                hotkeys.StringOr("toggle_panel", "Ctrl+Alt+X")
            );
        }
        catch (Exception ex)
        {
            _notifyIcon.ShowBalloonTip(
                4000,
                "XTray backend",
                ex.Message,
                Forms.ToolTipIcon.Error
            );
        }
    }

    private async Task ShowPopupAsync()
    {
        if (_popup is null)
        {
            _popup = new TrayPopupWindow(_backend);
            _popup.Closed += (_, _) => _popup = null;
        }

        if (!_popup.IsVisible && !_popup.HasStoredWindowBounds)
        {
            PositionNearTray(_popup);
        }
        if (!_popup.IsVisible)
        {
            _popup.Show();
        }
        _popup.Activate();
        await _popup.RefreshAsync();
        _hotkeyPoller.Update(
            _popup.LastSnapshot?.HotkeyEnabled ?? true,
            _popup.LastSnapshot?.ToggleHotkey ?? "Ctrl+Alt+X"
        );
    }

    private async Task TogglePopupAsync()
    {
        if (ShouldHidePopupForToggle(_popup))
        {
            _popup!.Hide();
            return;
        }

        await ShowPopupAsync();
    }

    internal static bool ShouldHidePopupForToggle(Window? popup) => popup is { IsVisible: true };

    private async Task ShowOptionsAsync()
    {
        if (_options is null)
        {
            _options = new OptionsWindow(_backend);
            _options.Closed += (_, _) => _options = null;
        }

        await _options.RefreshAsync();
        if (!_options.IsVisible)
        {
            _options.Show();
        }
        _options.Activate();
    }

    private async Task CallBackendAsync(string method, object? parameters = null)
    {
        await _backend.CallAsync(method, parameters, timeout: TimeSpan.FromSeconds(30));
    }

    private async Task ImportFromLanAsync()
    {
        await _backend.CallAsync("sync.import", timeout: TimeSpan.FromSeconds(60));
        _notifyIcon.ShowBalloonTip(
            3000,
            "XTray sync",
            "Import completed.",
            Forms.ToolTipIcon.Info
        );
    }

    private async Task CheckUpdatesAsync()
    {
        var update = await _backend.CallAsync("updates.check", timeout: TimeSpan.FromSeconds(30));
        if (update.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined)
        {
            _notifyIcon.ShowBalloonTip(
                3000,
                "XTray updates",
                "XTray is up to date.",
                Forms.ToolTipIcon.Info
            );
            return;
        }

        var version = update.StringOr("version", "new");
        var result = MessageBox.Show(
            $"XTray {version} is available. Download and install it now?",
            "XTray Updates",
            MessageBoxButton.YesNo,
            MessageBoxImage.Information
        );
        if (result == MessageBoxResult.Yes)
        {
            await _backend.CallAsync(
                "updates.download_install",
                new { update },
                timeout: TimeSpan.FromMinutes(5)
            );
            Quit();
        }
    }

    private async Task DiagnosticsAsync()
    {
        var result = await _backend.CallAsync("diagnostics.bundle", timeout: TimeSpan.FromSeconds(30));
        _notifyIcon.ShowBalloonTip(
            5000,
            "XTray diagnostics",
            result.StringOr("path", "Diagnostics bundle created."),
            Forms.ToolTipIcon.Info
        );
    }

    private async Task RestartBackendAsync()
    {
        await _backend.RestartAsync();
        _notifyIcon.ShowBalloonTip(
            3000,
            "XTray backend",
            "Backend restarted.",
            Forms.ToolTipIcon.Info
        );
        await InitializeAsync();
    }

    private Task QuitAsync()
    {
        Quit();
        return Task.CompletedTask;
    }

    private void Quit()
    {
        Dispose();
        _app.Shutdown();
    }

    private static void PositionNearTray(Window window)
    {
        var cursor = Forms.Cursor.Position;
        var workArea = SystemParameters.WorkArea;
        window.Left = Math.Min(
            Math.Max(workArea.Left, cursor.X - window.Width + 24),
            workArea.Right - window.Width
        );
        window.Top = Math.Min(
            Math.Max(workArea.Top, cursor.Y - window.Height - 12),
            workArea.Bottom - window.Height
        );
    }

    private static Icon LoadIcon()
    {
        var localIcon = Path.Combine(AppContext.BaseDirectory, "XTray.ico");
        if (File.Exists(localIcon))
        {
            return new Icon(localIcon);
        }
        return SystemIcons.Application;
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        _popup?.Close();
        _options?.Close();
        _hotkeyPoller.Dispose();
        _notifyIcon.Visible = false;
        _notifyIcon.Dispose();
    }
}
