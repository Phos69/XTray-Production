using System.Globalization;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Windows.Threading;
using XTray.Tray.Backend;
using Brushes = System.Windows.Media.Brushes;
using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using ComboBox = System.Windows.Controls.ComboBox;
using Control = System.Windows.Controls.Control;
using FontFamily = System.Windows.Media.FontFamily;
using HorizontalAlignment = System.Windows.HorizontalAlignment;
using MessageBox = System.Windows.MessageBox;
using Orientation = System.Windows.Controls.Orientation;
using ProgressBar = System.Windows.Controls.ProgressBar;
using TabControl = System.Windows.Controls.TabControl;

namespace XTray.Tray.UI;

internal sealed class TrayPopupWindow : Window
{
    private readonly JsonRpcClient _backend;
    private readonly TrayIconCache _icons;
    private readonly Dictionary<string, LegacySidePopupWindow> _sidePopups = new();
    private readonly DispatcherTimer _pendingDeviceRefreshTimer;
    private readonly TraySnapshotCache _snapshotCache;
    private readonly TrayWindowStateStore _windowStateStore;
    private TrayThemePalette _theme = TrayThemePalette.FromSettings(default);
    private bool _isRefreshing;
    private bool _busy;
    private string _activeTab = "media";
    private string? _transientStatus;
    private string? _transientError;

    public TrayPopupWindow(JsonRpcClient backend)
        : this(backend, null, null)
    {
    }

    internal TrayPopupWindow(
        JsonRpcClient backend,
        TraySnapshotCache? snapshotCache,
        TrayWindowStateStore? windowStateStore = null
    )
    {
        _backend = backend;
        _icons = new TrayIconCache(backend);
        _snapshotCache = snapshotCache ?? TraySnapshotCache.Default();
        _windowStateStore = windowStateStore ?? TrayWindowStateStore.Default();
        Title = "XTray";
        Width = 430;
        Height = 650;
        MinWidth = 320;
        MinHeight = 300;
        ShowInTaskbar = false;
        Topmost = true;
        WindowStartupLocation = WindowStartupLocation.Manual;
        WindowStyle = WindowStyle.None;
        AllowsTransparency = true;
        ResizeMode = ResizeMode.CanResize;
        Background = Brushes.Transparent;
        TrayWindowChrome.EnableFramelessResize(this);
        _pendingDeviceRefreshTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(1200) };
        _pendingDeviceRefreshTimer.Tick += async (_, _) =>
        {
            _pendingDeviceRefreshTimer.Stop();
            await RefreshAsync(showLoading: false);
        };
        _windowStateStore.Attach(this, "main");
        if (_snapshotCache.TryLoad() is { } cached)
        {
            LastSnapshot = cached;
            _theme = TrayThemePalette.FromSettings(cached.Settings);
            Build(cached);
        }
        else
        {
            SetLoading("Starting XTray...");
        }
    }

    public TraySnapshot? LastSnapshot { get; private set; }

    public bool HasStoredWindowBounds => _windowStateStore.HasState("main");

    public Task RefreshAsync() => RefreshAsync(showLoading: true);

    private async Task RefreshAsync(bool showLoading)
    {
        if (_busy)
        {
            return;
        }
        _busy = true;
        try
        {
            if (LastSnapshot is null)
            {
                SetLoading(showLoading ? "Refreshing..." : "Starting XTray...");
            }
            else
            {
                ShowTransientStatus("Refreshing...", refreshing: true);
            }
            var root = await _backend.CallAsync("tray.snapshot", timeout: TimeSpan.FromSeconds(30));
            var snapshot = new TraySnapshot(root);
            await _icons.WarmAsync(IconIds(snapshot));
            if (snapshot.HasPendingDeviceData)
            {
                QueuePendingDeviceRefresh(snapshot);
                if (LastSnapshot is not null)
                {
                    ShowTransientStatus("Refreshing...", refreshing: true);
                }
                return;
            }

            LastSnapshot = snapshot;
            _theme = TrayThemePalette.FromSettings(snapshot.Settings);
            _snapshotCache.Save(snapshot);
            ClearTransientStatus();
            Build(snapshot);
            QueuePendingDeviceRefresh(snapshot);
        }
        catch (Exception ex)
        {
            SetError(ex.Message);
        }
        finally
        {
            _busy = false;
        }
    }

    private void Build(TraySnapshot snapshot)
    {
        var options = snapshot.TrayOptions;
        var tabs = BuildTabs(snapshot, options);
        var bottom = BuildBottomBar(snapshot, options);
        var headerActions = new List<Button>();
        if (options.ShowDisplaysPopup)
        {
            headerActions.Add(HeaderPopupButton(snapshot, "displays", "display.popup"));
        }
        if (options.ShowAdaptersPopup)
        {
            headerActions.Add(HeaderPopupButton(snapshot, "adapters", "adapter.popup"));
        }
        if (options.ShowDrivesTab)
        {
            headerActions.Add(HeaderPopupButton(snapshot, "drives", "drive.popup"));
        }
        Content = TrayWindowChrome.WithResizeGrip(Shell("XTray", headerActions, tabs, bottom, close: Hide));
        RenderSidePopups(snapshot);
    }

    private void ShowTransientStatus(string message, bool refreshing = false)
    {
        _isRefreshing = refreshing;
        _transientStatus = message;
        _transientError = null;
        if (LastSnapshot is not null)
        {
            Build(LastSnapshot);
        }
    }

    private void ShowTransientError(string message)
    {
        _isRefreshing = false;
        _transientStatus = null;
        _transientError = message;
        if (LastSnapshot is not null)
        {
            Build(LastSnapshot);
        }
    }

    private void ClearTransientStatus()
    {
        _isRefreshing = false;
        _transientStatus = null;
        _transientError = null;
    }

    private void QueuePendingDeviceRefresh(TraySnapshot snapshot)
    {
        if (snapshot.HasPendingDeviceData)
        {
            if (!_pendingDeviceRefreshTimer.IsEnabled)
            {
                _pendingDeviceRefreshTimer.Start();
            }
            return;
        }
        _pendingDeviceRefreshTimer.Stop();
    }

    private UIElement Shell(
        string title,
        IEnumerable<Button> actions,
        UIElement content,
        UIElement? bottom,
        Action close
    )
    {
        var root = new Border
        {
            Background = _theme.SurfaceBrush,
            BorderBrush = _theme.BorderBrush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(_theme.RadiusPanel),
            SnapsToDevicePixels = true,
        };
        var dock = new DockPanel { LastChildFill = true };
        root.Child = dock;

        var header = new Grid
        {
            Height = 32,
            Margin = new Thickness(4, 0, 4, 0),
            Background = Brushes.Transparent,
        };
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        header.MouseLeftButtonDown += (_, args) =>
        {
            if (args.ButtonState == MouseButtonState.Pressed)
            {
                DragMove();
            }
        };

        var logo = Logo(title);
        Grid.SetColumn(logo, 0);
        header.Children.Add(logo);

        var actionRow = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
        };
        foreach (var action in actions)
        {
            action.Margin = new Thickness(3, 1, 0, 1);
            actionRow.Children.Add(action);
        }
        Grid.SetColumn(actionRow, 1);
        header.Children.Add(actionRow);

        var closeAction = new TrayAction("Hide", "asset:xtray_tray_glyph", "");
        var closeButton = LegacyTrayControls.IconButton(
            closeAction,
            _theme,
            _icons,
            () =>
            {
                close();
                return Task.CompletedTask;
            },
            _theme.Accent,
            width: 32,
            height: 28
        );
        closeButton.Margin = new Thickness(4, 1, 0, 1);
        LegacyTrayControls.ApplyButtonStyle(
            closeButton,
            _theme,
            "transparent",
            _theme.Muted,
            "transparent",
            _theme.CloseHover,
            _theme.ClosePressed
        );
        Grid.SetColumn(closeButton, 2);
        header.Children.Add(closeButton);

        DockPanel.SetDock(header, Dock.Top);
        dock.Children.Add(header);

        if (bottom is not null)
        {
            DockPanel.SetDock(bottom, Dock.Bottom);
            dock.Children.Add(bottom);
        }
        dock.Children.Add(content);
        return root;
    }

    private FrameworkElement Logo(string title) => CreateLogo(title == "XTray" ? "tray" : title, _theme);

    internal static FrameworkElement CreateLogo(
        string wordmark,
        TrayThemePalette theme,
        double width = 118,
        double height = 28
    )
    {
        var canvasWidth = LogoViewboxWidthFor(wordmark);
        var canvas = new Canvas
        {
            Width = canvasWidth,
            Height = 320,
            SnapsToDevicePixels = true,
            UseLayoutRounding = true,
        };
        TextOptions.SetTextFormattingMode(canvas, TextFormattingMode.Display);
        TextOptions.SetTextRenderingMode(canvas, TextRenderingMode.Grayscale);
        canvas.Children.Add(new Polygon
        {
            Points = new PointCollection
            {
                new(40, 40),
                new(100, 40),
                new(170, 110),
                new(240, 40),
                new(300, 40),
                new(200, 140),
                new(305, 245),
                new(245, 245),
                new(170, 170),
                new(95, 245),
                new(35, 245),
                new(140, 140),
            },
            Fill = theme.TextBrush,
        });
        canvas.Children.Add(new Path
        {
            Data = Geometry.Parse("M30 230 H120 L135 245 H205 L220 230 H310 L295 275 H45 Z"),
            Fill = theme.AccentBrush,
        });
        AddWordmarkGeometry(canvas, wordmark, theme);
        return new Viewbox
        {
            Width = width,
            Height = height,
            MinWidth = Math.Min(104, width),
            Margin = new Thickness(4, 0, 0, 0),
            HorizontalAlignment = HorizontalAlignment.Left,
            VerticalAlignment = VerticalAlignment.Center,
            Stretch = Stretch.Uniform,
            Child = canvas,
        };
    }

    private static double LogoViewboxWidthFor(string wordmark)
    {
        const double textStartX = 360;
        const double charAdvance = 82;
        const double rightMargin = 40;
        return Math.Max(1200, textStartX + charAdvance * wordmark.Length + rightMargin);
    }

    private static void AddWordmarkGeometry(Canvas canvas, string wordmark, TrayThemePalette theme)
    {
        var typeface = new Typeface(
            new FontFamily("Arial Black, Impact, Arial Narrow, Segoe UI"),
            FontStyles.Normal,
            FontWeights.Black,
            FontStretches.Normal
        );
        var formatted = new FormattedText(
            wordmark,
            CultureInfo.InvariantCulture,
            System.Windows.FlowDirection.LeftToRight,
            typeface,
            174,
            Brushes.Black,
            1
        );
        canvas.Children.Add(new Path
        {
            Data = formatted.BuildGeometry(new System.Windows.Point(360, 42)),
            Fill = theme.TextBrush,
            Tag = $"wordmark:{wordmark}",
            SnapsToDevicePixels = true,
            UseLayoutRounding = true,
        });
    }

    private Button HeaderPopupButton(TraySnapshot snapshot, string key, string actionId)
    {
        var action = snapshot.TrayOptions.Action(actionId);
        return LegacyTrayControls.IconButton(
            action,
            _theme,
            _icons,
            () =>
            {
                ToggleSidePopup(snapshot, key);
                return Task.CompletedTask;
            },
            _theme.AccentText,
            active: _sidePopups.TryGetValue(key, out var popup) && popup.IsVisible,
            height: 30
        );
    }

    private UIElement BuildTabs(TraySnapshot snapshot, TrayOptions options)
    {
        var tabs = new TabControl
        {
            Margin = new Thickness(2, 8, 2, 0),
            Background = Brushes.Transparent,
            BorderThickness = new Thickness(0),
            TabStripPlacement = Dock.Top,
        };
        ApplyTabStyle(tabs);
        AddTab(tabs, "media", options.Action("tab.media"), BuildMediaTab(snapshot), options.ShowMediaTab);
        AddTab(tabs, "network", options.Action("tab.network"), BuildNetworkTab(snapshot), options.ShowNetworkTab);
        AddTab(tabs, "adapters", options.Action("tab.adapters"), BuildAdaptersTab(snapshot), options.ShowAdaptersTab);
        AddTab(tabs, "drives", options.Action("tab.drives"), BuildDrivesTab(snapshot), options.ShowDrivesTab);
        if (tabs.Items.Count == 0)
        {
            var empty = new StackPanel { Margin = new Thickness(16) };
            empty.Children.Add(LegacyTrayControls.Text("All tray tabs are hidden.", _theme, 13, FontWeights.SemiBold));
            empty.Children.Add(LegacyTrayControls.TextButton("Options", _theme, ShowOptionsWindowAsync, role: "primary"));
            AddTab(tabs, "fallback", new TrayAction("Options", "mdi:cog", "Options"), empty, visible: true);
        }
        foreach (TabItem item in tabs.Items)
        {
            if (Equals(item.Tag, _activeTab))
            {
                tabs.SelectedItem = item;
                break;
            }
        }
        tabs.SelectionChanged += (_, _) =>
        {
            if (tabs.SelectedItem is TabItem selected && selected.Tag is string key)
            {
                _activeTab = key;
            }
        };
        return tabs;
    }

    private void AddTab(TabControl tabs, string key, TrayAction action, UIElement content, bool visible)
    {
        if (!visible)
        {
            return;
        }
        var item = new TabItem
        {
            Tag = key,
            ToolTip = action.Label,
            Header = _icons.Icon(action.Icon, _theme.Text, 20, action.FallbackLabel),
            Content = LegacyTrayControls.Scroll(content),
        };
        tabs.Items.Add(item);
    }

    private void ApplyTabStyle(TabControl tabs)
    {
        var tabStyle = new Style(typeof(TabItem));
        tabStyle.Setters.Add(new Setter(Control.PaddingProperty, new Thickness(8, 3, 8, 3)));
        tabStyle.Setters.Add(new Setter(Control.MarginProperty, new Thickness(0, 0, 3, 2)));
        tabStyle.Setters.Add(new Setter(Control.BackgroundProperty, Brushes.Transparent));
        tabStyle.Setters.Add(new Setter(Control.BorderBrushProperty, Brushes.Transparent));
        tabStyle.Setters.Add(new Setter(Control.BorderThicknessProperty, new Thickness(1)));
        tabStyle.Setters.Add(new Setter(Control.TemplateProperty, TabTemplate()));
        tabStyle.Triggers.Add(new Trigger
        {
            Property = TabItem.IsSelectedProperty,
            Value = true,
            Setters =
            {
                new Setter(Control.BackgroundProperty, _theme.ControlHoverBrush),
                new Setter(Control.BorderBrushProperty, _theme.SubtleBorderBrush),
            },
        });
        tabStyle.Triggers.Add(new Trigger
        {
            Property = UIElement.IsMouseOverProperty,
            Value = true,
            Setters = { new Setter(Control.BackgroundProperty, _theme.ControlHoverBrush) },
        });
        tabs.ItemContainerStyle = tabStyle;
    }

    private static ControlTemplate TabTemplate()
    {
        var border = new FrameworkElementFactory(typeof(Border));
        border.SetValue(Border.CornerRadiusProperty, new CornerRadius(6));
        border.SetBinding(Border.BackgroundProperty, new System.Windows.Data.Binding("Background") { RelativeSource = System.Windows.Data.RelativeSource.TemplatedParent });
        border.SetBinding(Border.BorderBrushProperty, new System.Windows.Data.Binding("BorderBrush") { RelativeSource = System.Windows.Data.RelativeSource.TemplatedParent });
        border.SetBinding(Border.BorderThicknessProperty, new System.Windows.Data.Binding("BorderThickness") { RelativeSource = System.Windows.Data.RelativeSource.TemplatedParent });
        var presenter = new FrameworkElementFactory(typeof(ContentPresenter));
        presenter.SetValue(FrameworkElement.HorizontalAlignmentProperty, HorizontalAlignment.Center);
        presenter.SetValue(FrameworkElement.VerticalAlignmentProperty, VerticalAlignment.Center);
        presenter.SetBinding(ContentPresenter.ContentProperty, new System.Windows.Data.Binding("Header") { RelativeSource = System.Windows.Data.RelativeSource.TemplatedParent });
        presenter.SetBinding(ContentPresenter.ContentTemplateProperty, new System.Windows.Data.Binding("HeaderTemplate") { RelativeSource = System.Windows.Data.RelativeSource.TemplatedParent });
        presenter.SetBinding(FrameworkElement.MarginProperty, new System.Windows.Data.Binding("Padding") { RelativeSource = System.Windows.Data.RelativeSource.TemplatedParent });
        border.AppendChild(presenter);
        return new ControlTemplate(typeof(TabItem)) { VisualTree = border };
    }

    private UIElement BuildMediaTab(TraySnapshot snapshot)
    {
        var root = new StackPanel { Margin = new Thickness(0, 0, 0, 8) };
        foreach (var row in snapshot.TrayOptions.MediaRowOrder)
        {
            if (row == "media_displays")
            {
                AddMediaDisplaysSection(root, snapshot);
            }
            else if (row == "audio_output")
            {
                AddAudioSection(root, snapshot);
            }
        }
        return root;
    }

    private void AddMediaDisplaysSection(StackPanel root, TraySnapshot snapshot)
    {
        var options = snapshot.TrayOptions;
        if (!options.ShowDisplayProfiles && !options.ShowMediaDisplays)
        {
            return;
        }
        var action = options.Action("display.popup");
        var section = LegacyTrayControls.Section("Displays", action, _theme, _icons);
        var body = new StackPanel { Margin = new Thickness(0, 6, 0, 0) };
        if (options.ShowDisplayProfiles)
        {
            AddProfileButtons(body, snapshot);
        }
        if (options.ShowMediaDisplays)
        {
            AddDisplayFaceplates(body, snapshot);
        }
        section.Content = body;
        root.Children.Add(section);
    }

    private void AddProfileButtons(StackPanel body, TraySnapshot snapshot)
    {
        var profiles = snapshot.Profiles.ArrayOrEmpty("favorites")
            .Select(item => item.ValueKind == JsonValueKind.String ? item.GetString() ?? "" : item.ToString())
            .Where(item => !string.IsNullOrWhiteSpace(item))
            .ToArray();
        var grid = LegacyTrayControls.FaceplateGrid(snapshot.TrayOptions.MediaProfileColumns);
        if (profiles.Length == 0)
        {
            body.Children.Add(LegacyTrayControls.Text("No favorite profiles", _theme, 13, color: _theme.Muted));
            return;
        }
        var active = snapshot.Profiles.StringOr("active");
        var missing = snapshot.Profiles.ObjectOrEmpty("missing_displays");
        var iconMap = snapshot.Profiles.ObjectOrEmpty("icons");
        foreach (var name in profiles)
        {
            var state = missing.BoolOr(name, false)
                ? "missing"
                : string.Equals(active, name, StringComparison.OrdinalIgnoreCase)
                    ? "primary"
                    : "enabled";
            var icon = TrayOptions.NormalizeIcon(iconMap.StringOr(name, snapshot.TrayOptions.Action("profile.fallback").Icon));
            grid.Children.Add(LegacyTrayControls.Faceplate(
                Compact(name, 18),
                state == "primary" ? "Active" : "",
                state,
                icon,
                _theme,
                _icons,
                () => CallAndRefreshAsync("profiles.apply", new { name }),
                enabled: state != "missing",
                compact: true
            ));
        }
        body.Children.Add(grid);
    }

    private void AddDisplayFaceplates(StackPanel body, TraySnapshot snapshot)
    {
        if (snapshot.Displays.Count == 0)
        {
            body.Children.Add(LegacyTrayControls.Text("No displays", _theme, 13, color: _theme.Muted));
            return;
        }
        var grid = LegacyTrayControls.FaceplateGrid(snapshot.Displays.Count);
        foreach (var item in snapshot.Displays)
        {
            var display = item.ObjectOrEmpty("display");
            var enabled = item.BoolOr("enabled", display.BoolOr("enabled", true));
            var primary = enabled && display.BoolOr("primary", false);
            var state = primary ? "primary" : enabled ? "enabled" : "disabled";
            grid.Children.Add(LegacyTrayControls.Faceplate(
                Compact(item.DisplayName("Display")),
                primary ? "Primary" : enabled ? "Enabled" : "Disabled",
                state,
                "mdi:monitor",
                _theme,
                _icons,
                () =>
                {
                    ToggleSidePopup(snapshot, "displays");
                    return Task.CompletedTask;
                },
                compact: true
            ));
        }
        body.Children.Add(grid);
    }

    private void AddAudioSection(StackPanel root, TraySnapshot snapshot)
    {
        var options = snapshot.TrayOptions;
        if (!options.ShowAudioOutput && !options.ShowPcVolume && !options.ShowDisplayVolume)
        {
            return;
        }
        var section = LegacyTrayControls.Section("Audio", options.Action("media.audio_output"), _theme, _icons);
        var body = new StackPanel { Margin = new Thickness(0, 6, 0, 0) };
        var audio = snapshot.Audio;
        if (audio.StringOr("error") is { Length: > 0 } error)
        {
            body.Children.Add(LegacyTrayControls.Text(error, _theme, 13, color: _theme.CloseHover));
            section.Content = body;
            root.Children.Add(section);
            return;
        }
        if (options.ShowAudioOutput)
        {
            body.Children.Add(AudioSourceRow(audio));
        }
        if (options.ShowPcVolume && TryReadInt(audio, "pc_volume_percent", out var pcVolume))
        {
            var muted = audio.TryObjectProperty("pc_muted", out var mutedValue)
                && mutedValue.ValueKind is JsonValueKind.True or JsonValueKind.False
                && mutedValue.GetBoolean();
            body.Children.Add(VolumeRow(
                options.Action("media.pc_volume"),
                pcVolume,
                muted,
                percent => CallAndRefreshAsync("audio.set_volume", new { percent }),
                () => CallAndRefreshAsync("audio.set_muted", new { muted = !muted })
            ));
        }
        var displayVolume = audio.ObjectOrEmpty("display_volume");
        if (options.ShowDisplayVolume && displayVolume.ValueKind == JsonValueKind.Object && TryReadInt(displayVolume, "percent", out var displayPercent))
        {
            var display = displayVolume.ObjectOrEmpty("display_state");
            body.Children.Add(VolumeRow(
                options.Action("media.display_volume"),
                displayPercent,
                muted: false,
                percent => CallAndRefreshAsync("display.set_monitor_volume", new { display, percent }),
                mute: null,
                label: displayVolume.StringOr("title", "Display volume")
            ));
        }
        section.Content = body;
        root.Children.Add(section);
    }

    private UIElement AudioSourceRow(JsonElement audio)
    {
        var row = new Grid { Margin = new Thickness(0, 2, 0, 8) };
        row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(32) });
        row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        row.Children.Add(_icons.Icon("mdi:volume-high", _theme.Text, 22, "A"));
        var combo = new ComboBox
        {
            MinHeight = 32,
            Background = _theme.ControlBrush,
            Foreground = _theme.TextBrush,
            BorderBrush = _theme.BorderBrush,
        };
        var sources = audio.ArrayOrEmpty("sources");
        var defaultId = audio.ObjectOrEmpty("default_source").StringOr("endpoint_id");
        var selectedIndex = 0;
        for (var index = 0; index < sources.Count; index++)
        {
            var source = sources[index];
            combo.Items.Add(new ComboBoxItem
            {
                Content = source.SourceLabel(),
                Tag = source.Clone(),
            });
            if (!string.IsNullOrWhiteSpace(defaultId) && source.StringOr("endpoint_id") == defaultId)
            {
                selectedIndex = index;
            }
        }
        if (combo.Items.Count == 0)
        {
            combo.Items.Add("No audio outputs found");
            combo.IsEnabled = false;
        }
        combo.SelectedIndex = selectedIndex;
        combo.SelectionChanged += async (_, _) =>
        {
            if (combo.SelectedItem is ComboBoxItem { Tag: JsonElement source })
            {
                await RunActionAsync(() => CallAndRefreshAsync("audio.set_source", new { source }));
            }
        };
        Grid.SetColumn(combo, 1);
        row.Children.Add(combo);
        return row;
    }

    private UIElement VolumeRow(
        TrayAction action,
        int value,
        bool muted,
        Func<int, Task> apply,
        Func<Task>? mute,
        string? label = null
    )
    {
        var grid = new Grid { Margin = new Thickness(0, 4, 0, 10) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(32) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(28) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(42) });

        var icon = _icons.Icon(action.Icon, muted ? _theme.Muted : _theme.Text, 22, action.FallbackLabel);
        Grid.SetColumn(icon, 0);
        grid.Children.Add(icon);

        if (mute is not null)
        {
            var muteButton = LegacyTrayControls.IconButton(
                new TrayAction(muted ? "Unmute" : "Mute", muted ? "mdi:volume-off" : "mdi:volume-high", "M"),
                _theme,
                _icons,
                mute,
                muted ? _theme.Muted : _theme.Text,
                width: 24,
                height: 24
            );
            LegacyTrayControls.ApplyButtonStyle(
                muteButton,
                _theme,
                "transparent",
                _theme.Text,
                "transparent",
                _theme.ControlHover,
                _theme.ControlPressed
            );
            Grid.SetColumn(muteButton, 1);
            grid.Children.Add(muteButton);
        }

        var bar = new VolumeFillBar
        {
            Theme = _theme,
            Value = Math.Clamp(value, 0, 100),
            Height = 22,
            MinWidth = 72,
            ToolTip = $"{label ?? action.Label} {value}%",
        };
        bar.ValueCommitted += async (_, percent) => await RunActionAsync(() => apply(percent));
        Grid.SetColumn(bar, 2);
        grid.Children.Add(bar);

        var number = LegacyTrayControls.Text($"{value}%", _theme, 12, color: _theme.Muted);
        number.HorizontalAlignment = HorizontalAlignment.Right;
        Grid.SetColumn(number, 3);
        grid.Children.Add(number);
        return grid;
    }

    private UIElement BuildNetworkTab(TraySnapshot snapshot)
    {
        var root = new StackPanel();
        var devices = snapshot.NetworkDevices
            .Where(device => !device.BoolOr("offline"))
            .ToArray();
        if (devices.Length == 0)
        {
            root.Children.Add(LegacyTrayControls.Text(
                snapshot.IsNetworkRefreshing ? "Refreshing network devices..." : "Add devices in Network Manager.",
                _theme,
                13,
                color: _theme.Muted
            ));
            return root;
        }
        var grouped = devices.GroupBy(device => NormalizeKind(device.StringOr("kind", "network")));
        foreach (var group in grouped)
        {
            root.Children.Add(LegacyTrayControls.Text(KindLabel(group.Key), _theme, 14, FontWeights.SemiBold));
            foreach (var device in group)
            {
                root.Children.Add(NetworkDeviceRow(device, snapshot.TrayOptions));
            }
        }
        return root;
    }

    private UIElement NetworkDeviceRow(JsonElement device, TrayOptions options)
    {
        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(30) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var icon = _icons.Icon(device.StringOr("icon", options.Action("tab.network").Icon), _theme.Text, 24, "N");
        Grid.SetColumn(icon, 0);
        grid.Children.Add(icon);
        var labels = new StackPanel();
        labels.Children.Add(LegacyTrayControls.Text(device.StringOr("name", "Device"), _theme, 13, FontWeights.SemiBold));
        labels.Children.Add(LegacyTrayControls.Text(device.StringOr("ip"), _theme, 12, color: _theme.Muted));
        Grid.SetColumn(labels, 1);
        grid.Children.Add(labels);
        var url = device.StringOr("web_url").FirstNonEmpty(device.StringOr("url"));
        var open = LegacyTrayControls.IconTextButton(
            options.Action("network.device.open").FallbackLabel,
            options.Action("network.device.open").Icon,
            _theme.AccentText,
            _theme,
            _icons,
            () => CallAndRefreshAsync("network.open_device", new { url }),
            enabled: !string.IsNullOrWhiteSpace(url),
            role: "primary"
        );
        Grid.SetColumn(open, 2);
        grid.Children.Add(open);
        return LegacyTrayControls.Row(_theme, grid);
    }

    private UIElement BuildAdaptersTab(TraySnapshot snapshot)
    {
        var root = new StackPanel();
        root.Children.Add(LegacyTrayControls.TextButton(
            snapshot.TrayOptions.Action("adapter.network_connections").FallbackLabel,
            _theme,
            () => CallAndRefreshAsync("adapter.open_network_connections"),
            role: "primary"
        ));
        root.Children.Add(new Border { Height = 8, Opacity = 0 });
        foreach (var adapter in FilterAdapters(snapshot))
        {
            root.Children.Add(AdapterRow(adapter, snapshot.TrayOptions));
        }
        if (!FilterAdapters(snapshot).Any())
        {
            root.Children.Add(LegacyTrayControls.Text(
                snapshot.IsAdaptersRefreshing ? "Refreshing network adapters..." : "No network adapters",
                _theme,
                13,
                color: _theme.Muted
            ));
        }
        return root;
    }

    private UIElement AdapterRow(JsonElement adapter, TrayOptions options)
    {
        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var text = new StackPanel();
        text.Children.Add(LegacyTrayControls.Text(adapter.StringOr("name", "Adapter"), _theme, 13, FontWeights.SemiBold));
        text.Children.Add(LegacyTrayControls.Text(
            $"{adapter.StringOr("description")} {adapter.StringOr("primary_ipv4")}".Trim(),
            _theme,
            12,
            color: _theme.Muted
        ));
        text.Children.Add(LegacyTrayControls.Text(
            $"Status: {adapter.StringOr("status")} | MAC: {adapter.StringOr("mac_address")}",
            _theme,
            12,
            color: _theme.Muted
        ));
        grid.Children.Add(text);
        var enabled = adapter.BoolOr("enabled", !string.Equals(adapter.StringOr("status"), "disabled", StringComparison.OrdinalIgnoreCase));
        var buttons = new StackPanel { Orientation = Orientation.Horizontal };
        buttons.Children.Add(Margined(LegacyTrayControls.TextButton(
            enabled ? options.Action("adapter.disable").FallbackLabel : options.Action("adapter.enable").FallbackLabel,
            _theme,
            () => CallAndRefreshAsync("adapter.set_enabled", new { adapter, enabled = !enabled }),
            role: enabled ? null : "primary",
            minWidth: 68
        )));
        buttons.Children.Add(LegacyTrayControls.IconButton(
            options.Action("adapter.properties"),
            _theme,
            _icons,
            () => CallAndRefreshAsync("adapter.open_properties", new { adapter }),
            _theme.AccentText,
            width: 32,
            height: 30
        ));
        Grid.SetColumn(buttons, 1);
        grid.Children.Add(buttons);
        return LegacyTrayControls.Row(_theme, grid);
    }

    private UIElement BuildDrivesTab(TraySnapshot snapshot)
    {
        var root = new StackPanel();
        foreach (var drive in FilterDrives(snapshot))
        {
            root.Children.Add(DriveRow(drive, snapshot.TrayOptions));
        }
        if (!FilterDrives(snapshot).Any())
        {
            root.Children.Add(LegacyTrayControls.Text(
                snapshot.IsDrivesRefreshing ? "Refreshing drives..." : "No drives",
                _theme,
                13,
                color: _theme.Muted
            ));
        }
        return root;
    }

    private UIElement DriveRow(JsonElement drive, TrayOptions options)
    {
        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(96) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var text = new StackPanel();
        text.Children.Add(LegacyTrayControls.Text(
            $"{drive.StringOr("letter", "?")}: {drive.StringOr("label", drive.StringOr("drive_type"))}",
            _theme,
            13,
            FontWeights.SemiBold
        ));
        var size = JsonElementExtensions.FormatBytes(drive.LongOrNull("size"));
        var free = JsonElementExtensions.FormatBytes(drive.LongOrNull("free_space"));
        text.Children.Add(LegacyTrayControls.Text(
            string.IsNullOrWhiteSpace(size) ? drive.StringOr("status") : $"{free} free of {size}",
            _theme,
            12,
            color: _theme.Muted
        ));
        grid.Children.Add(text);
        var progress = new ProgressBar
        {
            Minimum = 0,
            Maximum = 100,
            Value = Math.Clamp(drive.IntOr("used_percent", 0), 0, 100),
            Height = 18,
            Margin = new Thickness(8, 0, 8, 0),
            Foreground = _theme.AccentBrush,
            Background = _theme.ControlPressedBrush,
        };
        Grid.SetColumn(progress, 1);
        grid.Children.Add(progress);
        var open = LegacyTrayControls.IconButton(
            options.Action("drive.open"),
            _theme,
            _icons,
            () => CallAndRefreshAsync("drive.open", new { drive }),
            _theme.AccentText,
            width: 32,
            height: 30
        );
        Grid.SetColumn(open, 2);
        grid.Children.Add(open);
        return LegacyTrayControls.Row(_theme, grid);
    }

    private UIElement BuildBottomBar(TraySnapshot snapshot, TrayOptions options)
    {
        var bar = new Border
        {
            BorderBrush = _theme.SubtleBorderBrush,
            BorderThickness = new Thickness(0, 1, 0, 0),
            Padding = new Thickness(6, 4, 6, 4),
        };
        var row = new DockPanel { LastChildFill = false };
        bar.Child = row;

        var indicators = new StackPanel { Orientation = Orientation.Horizontal };
        var mqtt = snapshot.Settings.ObjectOrEmpty("mqtt");
        if (options.ShowMqttIndicator)
        {
            indicators.Children.Add(StatusIndicator("asset:mqtt_logo", mqtt.BoolOr("enabled") ? "connected" : "disabled", "MQTT"));
        }
        if (options.ShowHomeAssistantIndicator)
        {
            indicators.Children.Add(StatusIndicator("asset:homeassistant_logo", mqtt.BoolOr("home_assistant_enabled") ? "connected" : "disabled", "Home Assistant"));
        }
        DockPanel.SetDock(indicators, Dock.Left);
        row.Children.Add(indicators);

        if (BuildTransientStatus() is { } transient)
        {
            DockPanel.SetDock(transient, Dock.Left);
            row.Children.Add(transient);
        }

        var actions = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
        };
        if (options.ShowOptionsButton)
        {
            actions.Children.Add(Margined(LegacyTrayControls.IconButton(
                options.Action("fallback.options"),
                _theme,
                _icons,
                ShowOptionsWindowAsync,
                _theme.AccentText,
                width: 32,
                height: 28
            )));
        }
        if (options.ShowNetworkManagerButton)
        {
            actions.Children.Add(Margined(LegacyTrayControls.IconButton(
                options.Action("network.manage"),
                _theme,
                _icons,
                () => CallAndRefreshAsync("app.open_network_manager"),
                _theme.AccentText,
                width: 32,
                height: 28
            )));
        }
        if (options.ShowComputerManagerButton)
        {
            actions.Children.Add(LegacyTrayControls.IconButton(
                options.Action("header.computer_manager"),
                _theme,
                _icons,
                () => CallAndRefreshAsync("app.open_computer_manager"),
                _theme.AccentText,
                width: 32,
                height: 28
            ));
        }
        DockPanel.SetDock(actions, Dock.Right);
        row.Children.Add(actions);
        return bar;
    }

    private UIElement? BuildTransientStatus()
    {
        var message = _transientError.FirstNonEmpty(_transientStatus, _isRefreshing ? "Refreshing..." : "");
        if (string.IsNullOrWhiteSpace(message))
        {
            return null;
        }
        var color = _transientError is null ? _theme.Muted : _theme.CloseHover;
        return new TextBlock
        {
            Text = message,
            Foreground = _theme.Brush(color),
            FontSize = 12,
            TextTrimming = TextTrimming.CharacterEllipsis,
            VerticalAlignment = VerticalAlignment.Center,
            MaxWidth = 180,
            Margin = new Thickness(8, 0, 8, 0),
            ToolTip = message,
        };
    }

    private UIElement StatusIndicator(string icon, string state, string tooltip)
    {
        var color = _theme.IndicatorColor(state);
        var border = new Border
        {
            Width = 30,
            Height = 28,
            ToolTip = $"{tooltip} {state}",
            Child = _icons.Icon(icon, color, 22, tooltip[..1]),
        };
        return border;
    }

    private void ToggleSidePopup(TraySnapshot snapshot, string key)
    {
        if (!_sidePopups.TryGetValue(key, out var popup))
        {
            popup = new LegacySidePopupWindow(key, _windowStateStore);
            _sidePopups[key] = popup;
        }
        if (popup.IsVisible)
        {
            popup.Hide();
            Build(snapshot);
            return;
        }
        RenderSidePopup(snapshot, key, popup);
        if (!popup.HasStoredWindowBounds)
        {
            PositionSidePopup(popup);
        }
        popup.Show();
        popup.Activate();
        Build(snapshot);
    }

    private void RenderSidePopups(TraySnapshot snapshot)
    {
        foreach (var (key, popup) in _sidePopups)
        {
            if (popup.IsVisible)
            {
                RenderSidePopup(snapshot, key, popup);
            }
        }
    }

    private void RenderSidePopup(TraySnapshot snapshot, string key, LegacySidePopupWindow popup)
    {
        var title = key switch
        {
            "adapters" => "Adapters",
            "drives" => "Drives",
            _ => "Displays",
        };
        var actionId = key switch
        {
            "adapters" => "adapter.refresh",
            "drives" => "drive.refresh",
            _ => "display.refresh",
        };
        var wordmark = key switch
        {
            "adapters" => "adapters",
            "drives" => "drives",
            _ => "displays",
        };
        var actions = new List<Button>
        {
            LegacyTrayControls.IconButton(
                snapshot.TrayOptions.Action(actionId),
                _theme,
                _icons,
                RefreshAsync,
                _theme.AccentText,
                width: 32,
                height: 28
            ),
        };
        if (key == "adapters")
        {
            actions.Add(LegacyTrayControls.IconButton(
                snapshot.TrayOptions.Action("adapter.network_connections"),
                _theme,
                _icons,
                () => CallAndRefreshAsync("adapter.open_network_connections"),
                _theme.AccentText,
                width: 32,
                height: 28
            ));
        }
        UIElement content = key switch
        {
            "adapters" => BuildAdaptersTab(snapshot),
            "drives" => BuildDrivesTab(snapshot),
            _ => BuildDisplaysPopup(snapshot),
        };
        popup.Render(_theme, title, wordmark, actions, LegacyTrayControls.Scroll(content), _icons);
    }

    private UIElement BuildDisplaysPopup(TraySnapshot snapshot)
    {
        var root = new StackPanel();
        if (snapshot.Displays.Count == 0)
        {
            root.Children.Add(LegacyTrayControls.Text("No displays", _theme, 13, color: _theme.Muted));
            return root;
        }
        var enabledCount = snapshot.Displays.Count(item => item.BoolOr("enabled", item.ObjectOrEmpty("display").BoolOr("enabled", true)));
        foreach (var item in snapshot.Displays)
        {
            root.Children.Add(DisplayRow(item, snapshot.TrayOptions, enabledCount));
        }
        return root;
    }

    private UIElement DisplayRow(JsonElement item, TrayOptions options, int enabledCount)
    {
        var display = item.ObjectOrEmpty("display");
        var enabled = item.BoolOr("enabled", display.BoolOr("enabled", true));
        var primary = enabled && display.BoolOr("primary", false);
        var stack = new StackPanel();
        var top = new Grid();
        top.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        top.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var title = new StackPanel();
        title.Children.Add(LegacyTrayControls.Text(item.DisplayName("Display"), _theme, 13, FontWeights.SemiBold));
        title.Children.Add(LegacyTrayControls.Text(DisplayMetrics(display), _theme, 12, color: _theme.Muted));
        top.Children.Add(title);
        var buttons = new StackPanel { Orientation = Orientation.Horizontal };
        if (primary)
        {
            buttons.Children.Add(Margined(LegacyTrayControls.TextButton(options.Action("display.primary").FallbackLabel, _theme, () => Task.CompletedTask, enabled: false, role: "primary")));
        }
        else if (enabled)
        {
            buttons.Children.Add(Margined(LegacyTrayControls.TextButton(options.Action("display.make_primary").FallbackLabel, _theme, () => CallAndRefreshAsync("display.set_primary", new { display }), role: "primary")));
        }
        var canToggle = !enabled || enabledCount > 1 || DisplayToggleAvailable(item);
        buttons.Children.Add(Margined(LegacyTrayControls.TextButton(
            enabled ? options.Action("display.disable").FallbackLabel : options.Action("display.enable").FallbackLabel,
            _theme,
            () => CallAndRefreshAsync("display.set_enabled", new { display, enabled = !enabled }),
            enabled: canToggle,
            role: enabled ? "warning" : "success",
            minWidth: 66
        )));
        Grid.SetColumn(buttons, 1);
        top.Children.Add(buttons);
        stack.Children.Add(top);

        var bottom = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
        if (!string.IsNullOrWhiteSpace(item.StringOr("power_on_ha_service")))
        {
            bottom.Children.Add(Margined(LegacyTrayControls.IconButton(options.Action("display.power_on"), _theme, _icons, () => CallAndRefreshAsync("display.call_power_service", new { display, turn_on = true }), _theme.Text, width: 40)));
        }
        if (!string.IsNullOrWhiteSpace(item.StringOr("power_off_ha_service")))
        {
            bottom.Children.Add(LegacyTrayControls.IconButton(options.Action("display.power_off"), _theme, _icons, () => CallAndRefreshAsync("display.call_power_service", new { display, turn_on = false }), _theme.Text, width: 40));
        }
        if (bottom.Children.Count > 0)
        {
            stack.Children.Add(bottom);
        }
        var row = LegacyTrayControls.Row(_theme, stack);
        row.ContextMenu = DisplayContextMenu(item, options, enabledCount);
        return row;
    }

    private ContextMenu DisplayContextMenu(JsonElement item, TrayOptions options, int enabledCount)
    {
        var display = item.ObjectOrEmpty("display");
        var enabled = item.BoolOr("enabled", display.BoolOr("enabled", true));
        var menu = new ContextMenu();
        var toggle = new MenuItem { Header = enabled ? options.Action("display.disable").Label : options.Action("display.enable").Label };
        toggle.IsEnabled = !enabled || enabledCount > 1 || DisplayToggleAvailable(item);
        toggle.Click += async (_, _) => await RunActionAsync(() => CallAndRefreshAsync("display.set_enabled", new { display, enabled = !enabled }));
        menu.Items.Add(toggle);
        if (enabled && !display.BoolOr("primary"))
        {
            var primary = new MenuItem { Header = options.Action("display.make_primary").Label };
            primary.Click += async (_, _) => await RunActionAsync(() => CallAndRefreshAsync("display.set_primary", new { display }));
            menu.Items.Add(primary);
        }
        return menu;
    }

    private void PositionSidePopup(Window popup)
    {
        var workArea = SystemParameters.WorkArea;
        popup.Left = Math.Min(Left + Width + 8, workArea.Right - popup.Width);
        if (popup.Left < workArea.Left)
        {
            popup.Left = workArea.Left;
        }
        popup.Top = Math.Min(Math.Max(workArea.Top, Top), workArea.Bottom - popup.Height);
    }

    private IReadOnlyList<JsonElement> FilterAdapters(TraySnapshot snapshot)
    {
        var allowed = snapshot.TrayOptions.VisibleAdapterIds;
        return allowed is null
            ? snapshot.Adapters
            : snapshot.Adapters
                .Where(adapter => allowed.Contains(adapter.StringOr("name").ToLowerInvariant()))
                .ToArray();
    }

    private IReadOnlyList<JsonElement> FilterDrives(TraySnapshot snapshot)
    {
        var allowed = snapshot.TrayOptions.VisibleDriveIds;
        return allowed is null
            ? snapshot.Drives
            : snapshot.Drives
                .Where(drive => allowed.Contains(drive.StringOr("letter").TrimEnd(':').ToUpperInvariant()))
                .ToArray();
    }

    private async Task ShowOptionsWindowAsync()
    {
        var window = new OptionsWindow(_backend);
        await window.RefreshAsync();
        window.Show();
        window.Activate();
    }

    private async Task CallAndRefreshAsync(string method, object? parameters = null)
    {
        if (LastSnapshot is not null)
        {
            ShowTransientStatus("Working...", refreshing: true);
        }
        try
        {
            await _backend.CallAsync(method, parameters, timeout: TimeSpan.FromSeconds(45));
            await RefreshAsync(showLoading: false);
        }
        catch (Exception ex)
        {
            ShowTransientError(ex.Message);
            throw;
        }
    }

    private async Task RunActionAsync(Func<Task> action)
    {
        if (_busy)
        {
            return;
        }
        try
        {
            await action();
        }
        catch (Exception ex)
        {
            ShowTransientError(ex.Message);
            MessageBox.Show(ex.Message, "XTray", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void SetLoading(string message)
    {
        Content = TrayWindowChrome.WithResizeGrip(new Border
        {
            Background = _theme.SurfaceBrush,
            BorderBrush = _theme.BorderBrush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(_theme.RadiusPanel),
            Child = new TextBlock
            {
                Text = message,
                FontSize = 14,
                Foreground = _theme.MutedBrush,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
            },
        });
    }

    private void SetError(string message)
    {
        if (LastSnapshot is not null)
        {
            ShowTransientError(message);
            return;
        }
        Content = TrayWindowChrome.WithResizeGrip(new Border
        {
            Background = _theme.SurfaceBrush,
            BorderBrush = _theme.BorderBrush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(_theme.RadiusPanel),
            Child = new TextBlock
            {
                Text = message,
                FontSize = 13,
                Foreground = _theme.Brush(_theme.CloseHover),
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(20),
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
            },
        });
    }

    private IEnumerable<string> IconIds(TraySnapshot snapshot)
    {
        foreach (var id in snapshot.TrayOptions.ActionIconIds())
        {
            yield return id;
        }
        foreach (var property in snapshot.Profiles.ObjectOrEmpty("icons").ObjectProperties())
        {
            var icon = TrayOptions.NormalizeIcon(property.Value.ValueKind == JsonValueKind.String ? property.Value.GetString() : "");
            if (!string.IsNullOrWhiteSpace(icon))
            {
                yield return icon;
            }
        }
        foreach (var device in snapshot.NetworkDevices)
        {
            var icon = TrayOptions.NormalizeIcon(device.StringOr("icon"));
            if (!string.IsNullOrWhiteSpace(icon))
            {
                yield return icon;
            }
        }
        yield return "asset:xtray_tray_glyph";
        yield return "asset:mqtt_logo";
        yield return "asset:homeassistant_logo";
    }

    private static bool TryReadInt(JsonElement element, string name, out int value)
    {
        value = 0;
        if (!element.TryObjectProperty(name, out var child))
        {
            return false;
        }
        if (child.ValueKind == JsonValueKind.Number && child.TryGetInt32(out value))
        {
            return true;
        }
        return child.ValueKind == JsonValueKind.String && int.TryParse(child.GetString(), out value);
    }

    private static string Compact(string value, int limit = 12)
    {
        var text = string.Join(" ", (value.FirstNonEmpty("Display")).Split(' ', StringSplitOptions.RemoveEmptyEntries));
        return text.Length <= limit ? text : text[..Math.Max(1, limit - 1)].TrimEnd() + "...";
    }

    private static string DisplayMetrics(JsonElement display)
    {
        var width = display.IntOr("width");
        var height = display.IntOr("height");
        var resolution = width > 0 && height > 0 ? $"{width}x{height}" : "Unknown";
        var refresh = display.IntOr("refresh_hz") > 0 ? $"{display.IntOr("refresh_hz")} Hz" : "Unknown";
        return $"{resolution} | {refresh}";
    }

    private static string NormalizeKind(string kind)
    {
        var text = kind.Trim().Replace("-", "_", StringComparison.Ordinal).Replace(" ", "_", StringComparison.Ordinal).ToLowerInvariant();
        return text is "iot" or "media" or "personal" ? text : "network";
    }

    private static string KindLabel(string kind) => kind switch
    {
        "iot" => "IoT",
        "media" => "Media",
        "personal" => "Personal devices",
        _ => "Network",
    };

    private static bool DisplayToggleAvailable(JsonElement item)
    {
        if (item.BoolOr("available") || item.BoolOr("enabled"))
        {
            return true;
        }
        if (item.ArrayOrEmpty("assigned_profiles").Count > 0)
        {
            return true;
        }
        return !string.IsNullOrWhiteSpace(item.ObjectOrEmpty("display").StringOr("adapter_name"));
    }

    private static UIElement Margined(UIElement element)
    {
        if (element is FrameworkElement frameworkElement)
        {
            frameworkElement.Margin = new Thickness(0, 0, 6, 0);
        }
        return element;
    }
}

internal sealed class LegacySidePopupWindow : Window
{
    private readonly string _stateKey;
    private readonly TrayWindowStateStore _windowStateStore;
    private TrayThemePalette _theme = TrayThemePalette.FromSettings(default);

    public LegacySidePopupWindow(string key)
        : this(key, null)
    {
    }

    public LegacySidePopupWindow(string key, TrayWindowStateStore? windowStateStore)
    {
        _stateKey = $"side.{key}";
        _windowStateStore = windowStateStore ?? TrayWindowStateStore.Default();
        Width = 360;
        Height = key == "adapters" ? 420 : 360;
        MinWidth = 320;
        MinHeight = 260;
        ShowInTaskbar = false;
        Topmost = true;
        WindowStyle = WindowStyle.None;
        AllowsTransparency = true;
        ResizeMode = ResizeMode.CanResize;
        Background = Brushes.Transparent;
        WindowStartupLocation = WindowStartupLocation.Manual;
        TrayWindowChrome.EnableFramelessResize(this);
        _windowStateStore.Attach(this, _stateKey);
    }

    public bool HasStoredWindowBounds => _windowStateStore.HasState(_stateKey);

    public void Render(
        TrayThemePalette theme,
        string title,
        string wordmark,
        IEnumerable<Button> actions,
        UIElement content,
        TrayIconCache icons
    )
    {
        _theme = theme;
        Content = TrayWindowChrome.WithResizeGrip(Shell(title, wordmark, actions, content, icons));
    }

    private UIElement Shell(
        string title,
        string wordmark,
        IEnumerable<Button> actions,
        UIElement content,
        TrayIconCache icons
    )
    {
        var border = new Border
        {
            Background = _theme.SurfaceBrush,
            BorderBrush = _theme.BorderBrush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(_theme.RadiusPanel),
        };
        var dock = new DockPanel { LastChildFill = true };
        border.Child = dock;
        var header = new Grid
        {
            Height = 32,
            Margin = new Thickness(4, 0, 4, 0),
            Background = Brushes.Transparent,
        };
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        header.MouseLeftButtonDown += (_, args) =>
        {
            if (args.ButtonState == MouseButtonState.Pressed)
            {
                DragMove();
            }
        };
        var logo = TrayPopupWindow.CreateLogo(wordmark, _theme, width: 132, height: 28);
        logo.ToolTip = title;
        Grid.SetColumn(logo, 0);
        header.Children.Add(logo);
        var actionRow = new StackPanel { Orientation = Orientation.Horizontal };
        foreach (var action in actions)
        {
            action.Margin = new Thickness(3, 1, 0, 1);
            actionRow.Children.Add(action);
        }
        Grid.SetColumn(actionRow, 1);
        header.Children.Add(actionRow);
        var close = LegacyTrayControls.IconButton(
            new TrayAction("Hide", "asset:xtray_tray_glyph", ""),
            _theme,
            icons,
            () =>
            {
                Hide();
                return Task.CompletedTask;
            },
            _theme.Accent,
            width: 32,
            height: 28
        );
        LegacyTrayControls.ApplyButtonStyle(close, _theme, "transparent", _theme.Muted, "transparent", _theme.CloseHover, _theme.ClosePressed);
        Grid.SetColumn(close, 2);
        header.Children.Add(close);
        DockPanel.SetDock(header, Dock.Top);
        dock.Children.Add(header);
        var host = new Border
        {
            Padding = new Thickness(8),
            Child = content,
        };
        dock.Children.Add(host);
        return border;
    }
}
