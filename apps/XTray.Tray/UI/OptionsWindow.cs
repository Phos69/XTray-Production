using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using XTray.Tray.Backend;
using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using ComboBox = System.Windows.Controls.ComboBox;
using Control = System.Windows.Controls.Control;
using Brushes = System.Windows.Media.Brushes;
using HorizontalAlignment = System.Windows.HorizontalAlignment;
using MessageBox = System.Windows.MessageBox;
using Orientation = System.Windows.Controls.Orientation;
using TabControl = System.Windows.Controls.TabControl;
using TextBox = System.Windows.Controls.TextBox;

namespace XTray.Tray.UI;

internal sealed class OptionsWindow : Window
{
    private readonly JsonRpcClient _backend;
    private readonly ComboBox _theme = new();
    private readonly CheckBox _hotkeyEnabled = new() { Content = "Enable panel hotkey" };
    private readonly TextBox _hotkey = new() { MinWidth = 180 };
    private readonly CheckBox _mqttEnabled = new() { Content = "Enable MQTT" };
    private readonly TextBox _mqttHost = new() { MinWidth = 220 };
    private readonly TextBox _mqttPort = new() { MinWidth = 80 };
    private readonly TextBox _mqttUsername = new() { MinWidth = 180 };
    private readonly PasswordBox _mqttPassword = new() { MinWidth = 180 };
    private readonly CheckBox _mqttTls = new() { Content = "TLS" };
    private readonly TextBox _mediaProfileColumns = new() { MinWidth = 80 };
    private readonly TextBox _displayGridColumns = new() { MinWidth = 80 };
    private readonly Dictionary<string, CheckBox> _trayChecks = new();
    private readonly Border _host = new();
    private TrayThemePalette _themePalette = TrayThemePalette.FromSettings(default);
    private JsonElement _settings;

    public OptionsWindow(JsonRpcClient backend)
    {
        _backend = backend;
        Title = "XTray Options";
        Width = 620;
        Height = 680;
        MinWidth = 480;
        MinHeight = 500;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        Content = _host;
        BuildShell();
    }

    public async Task RefreshAsync()
    {
        var settings = await _backend.CallAsync("settings.get", timeout: TimeSpan.FromSeconds(20));
        _settings = settings.Clone();
        LoadSettings(_settings);
    }

    private void BuildShell()
    {
        _trayChecks.Clear();
        var root = new DockPanel
        {
            Background = _themePalette.SurfaceBrush,
        };
        var footer = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
            Margin = new Thickness(12),
        };
        var save = ActionButton("Save", SaveAsync);
        var close = new Button
        {
            Content = "Close",
            Padding = new Thickness(12, 5, 12, 5),
            MinWidth = 80,
            Margin = new Thickness(8, 0, 0, 0),
        };
        close.Click += (_, _) => Close();
        footer.Children.Add(save);
        footer.Children.Add(close);
        DockPanel.SetDock(footer, Dock.Bottom);
        root.Children.Add(footer);

        var tabs = new TabControl { Margin = new Thickness(12) };
        tabs.Items.Add(Tab("General", GeneralPage()));
        tabs.Items.Add(Tab("Media", MediaPage()));
        tabs.Items.Add(Tab("Devices", DevicesPage()));
        tabs.Items.Add(Tab("Buttons", ButtonsPage()));
        root.Children.Add(tabs);
        _host.Child = root;
    }

    private UIElement GeneralPage()
    {
        var content = Page();
        content.Children.Add(Heading("Appearance"));
        content.Children.Add(FormRow("Theme", _theme));
        content.Children.Add(Heading("Hotkey"));
        content.Children.Add(_hotkeyEnabled);
        content.Children.Add(FormRow("Toggle panel", _hotkey));
        content.Children.Add(Heading("MQTT"));
        content.Children.Add(_mqttEnabled);
        content.Children.Add(FormRow("Host", _mqttHost));
        content.Children.Add(FormRow("Port", _mqttPort));
        content.Children.Add(FormRow("Username", _mqttUsername));
        content.Children.Add(FormRow("Password", _mqttPassword));
        content.Children.Add(_mqttTls);
        return Scroll(content);
    }

    private UIElement MediaPage()
    {
        var content = Page();
        content.Children.Add(Heading("Tab visibility"));
        AddTrayOption(content, "show_media_tab", "Media tab");
        AddTrayOption(content, "show_network_tab", "Network tab");
        AddTrayOption(content, "show_adapters_tab", "Adapters tab");
        AddTrayOption(content, "show_drives_tab", "Drives tab");
        content.Children.Add(Heading("Media controls"));
        AddTrayOption(content, "show_display_profiles", "Display profile buttons");
        AddTrayOption(content, "show_media_displays", "Display faceplates");
        AddTrayOption(content, "show_audio_output", "Audio output selector");
        AddTrayOption(content, "show_pc_volume", "PC volume");
        AddTrayOption(content, "show_display_volume", "Display volume");
        AddTrayOption(content, "show_media_drives", "Drive faceplates");
        content.Children.Add(Heading("Layout"));
        content.Children.Add(FormRow("Profile columns", _mediaProfileColumns));
        return Scroll(content);
    }

    private UIElement DevicesPage()
    {
        var content = Page();
        content.Children.Add(Heading("Popup buttons"));
        AddTrayOption(content, "show_displays_popup", "Displays popup");
        AddTrayOption(content, "show_adapters_popup", "Adapters popup");
        content.Children.Add(FormRow("Display columns", _displayGridColumns));
        content.Children.Add(Heading("Indicators"));
        AddTrayOption(content, "show_mqtt_indicator", "MQTT indicator");
        AddTrayOption(content, "show_home_assistant_indicator", "Home Assistant indicator");
        return Scroll(content);
    }

    private UIElement ButtonsPage()
    {
        var content = Page();
        content.Children.Add(Heading("Launch buttons"));
        AddTrayOption(content, "show_options_button", "Options button");
        AddTrayOption(content, "show_network_manager_button", "Network Manager button");
        AddTrayOption(content, "show_computer_manager_button", "Computer Manager button");
        AddTrayOption(content, "show_restart_button", "Restart menu action");
        return Scroll(content);
    }

    private void LoadSettings(JsonElement settings)
    {
        _themePalette = TrayThemePalette.FromSettings(settings);
        BuildShell();
        _theme.Items.Clear();
        foreach (var item in settings.ArrayOrEmpty("theme_names"))
        {
            if (item.ValueKind == JsonValueKind.String)
            {
                _theme.Items.Add(item.GetString());
            }
        }
        var theme = settings.StringOr("theme", "system");
        _theme.SelectedItem = theme;
        if (_theme.SelectedItem is null)
        {
            _theme.Items.Add(theme);
            _theme.SelectedItem = theme;
        }

        var hotkeys = settings.ObjectOrEmpty("hotkeys");
        _hotkeyEnabled.IsChecked = hotkeys.BoolOr("toggle_panel_enabled", true);
        _hotkey.Text = hotkeys.StringOr("toggle_panel", "Ctrl+Alt+X");

        var mqtt = settings.ObjectOrEmpty("mqtt");
        _mqttEnabled.IsChecked = mqtt.BoolOr("enabled");
        _mqttHost.Text = mqtt.StringOr("host");
        _mqttPort.Text = mqtt.IntOr("port", 1883).ToString();
        _mqttUsername.Text = mqtt.StringOr("username");
        _mqttPassword.Password = "";
        _mqttTls.IsChecked = mqtt.BoolOr("tls");

        var tray = settings.ObjectOrEmpty("tray_options");
        foreach (var (key, check) in _trayChecks)
        {
            check.IsChecked = tray.BoolOr(key, true);
        }
        _mediaProfileColumns.Text = tray.IntOr("media_profile_columns", 3).ToString();
        _displayGridColumns.Text = tray.IntOr("display_grid_columns", 2).ToString();
    }

    private async Task SaveAsync()
    {
        var selectedTheme = _theme.SelectedItem?.ToString() ?? "system";
        await _backend.CallAsync("settings.update_theme", new { theme = selectedTheme });
        await _backend.CallAsync(
            "settings.update_hotkeys",
            new
            {
                updates = new Dictionary<string, object?>
                {
                    ["toggle_panel_enabled"] = _hotkeyEnabled.IsChecked == true,
                    ["toggle_panel"] = _hotkey.Text,
                },
            }
        );

        var mqttUpdates = new Dictionary<string, object?>
        {
            ["enabled"] = _mqttEnabled.IsChecked == true,
            ["host"] = _mqttHost.Text,
            ["port"] = int.TryParse(_mqttPort.Text, out var port) ? port : 1883,
            ["username"] = string.IsNullOrWhiteSpace(_mqttUsername.Text) ? null : _mqttUsername.Text,
            ["tls"] = _mqttTls.IsChecked == true,
        };
        if (!string.IsNullOrEmpty(_mqttPassword.Password))
        {
            mqttUpdates["password"] = _mqttPassword.Password;
        }
        await _backend.CallAsync("settings.update_mqtt", new { updates = mqttUpdates });

        var trayUpdates = _trayChecks.ToDictionary(
            item => item.Key,
            item => (object?)(item.Value.IsChecked == true)
        );
        trayUpdates["media_profile_columns"] = int.TryParse(_mediaProfileColumns.Text, out var profileColumns)
            ? profileColumns
            : 3;
        trayUpdates["display_grid_columns"] = int.TryParse(_displayGridColumns.Text, out var displayColumns)
            ? displayColumns
            : 2;
        await _backend.CallAsync("settings.update_tray_options", new { updates = trayUpdates });
        await RefreshAsync();
        MessageBox.Show(
            "Options saved.",
            "XTray",
            MessageBoxButton.OK,
            MessageBoxImage.Information
        );
    }

    private void AddTrayOption(StackPanel parent, string key, string label)
    {
        if (_trayChecks.ContainsKey(key))
        {
            return;
        }
        var check = new CheckBox
        {
            Content = label,
            Margin = new Thickness(0, 4, 0, 4),
            Foreground = _themePalette.TextBrush,
        };
        _trayChecks[key] = check;
        parent.Children.Add(check);
    }

    private Button ActionButton(string text, Func<Task> action)
    {
        var button = new Button
        {
            Content = text,
            Padding = new Thickness(12, 5, 12, 5),
            MinWidth = 80,
        };
        LegacyTrayControls.ApplyButtonStyle(
            button,
            _themePalette,
            text == "Save" ? _themePalette.Accent : _themePalette.Control,
            text == "Save" ? _themePalette.AccentText : _themePalette.Text,
            text == "Save" ? _themePalette.Accent : _themePalette.Border,
            text == "Save" ? _themePalette.AccentHover : _themePalette.ControlHover,
            text == "Save" ? _themePalette.AccentPressed : _themePalette.ControlPressed
        );
        button.Click += async (_, _) =>
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
        return button;
    }

    private static UIElement Heading(string text)
    {
        return new TextBlock
        {
            Text = text,
            FontSize = 16,
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(0, 12, 0, 8),
        };
    }

    private static UIElement FormRow(string label, Control control)
    {
        var grid = new Grid { Margin = new Thickness(0, 3, 0, 6) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(130) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        var text = new TextBlock
        {
            Text = label,
            VerticalAlignment = VerticalAlignment.Center,
            Foreground = Brushes.DimGray,
        };
        Grid.SetColumn(text, 0);
        Grid.SetColumn(control, 1);
        grid.Children.Add(text);
        grid.Children.Add(control);
        return grid;
    }

    private static TabItem Tab(string title, UIElement content)
    {
        return new TabItem { Header = title, Content = content };
    }

    private static StackPanel Page()
    {
        return new StackPanel { Margin = new Thickness(14) };
    }

    private static ScrollViewer Scroll(UIElement content)
    {
        return new ScrollViewer
        {
            Content = content,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
        };
    }
}
