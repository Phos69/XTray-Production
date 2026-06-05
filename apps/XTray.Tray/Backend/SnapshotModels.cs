using System.Globalization;
using System.Text.Json;

namespace XTray.Tray.Backend;

internal sealed class TraySnapshot
{
    public TraySnapshot(JsonElement root)
    {
        Root = root.Clone();
    }

    public JsonElement Root { get; }

    public string Version => Root.StringOr("version", "unknown");

    public JsonElement Settings => Root.ObjectOrEmpty("settings");

    public TrayOptions TrayOptions => TrayOptions.From(Settings.ObjectOrEmpty("tray_options"));

    public string ThemeName => Settings.StringOr("theme", "vibrant");

    public JsonElement ThemeData => Settings.ObjectOrEmpty("theme_data");

    public JsonElement Profiles => Root.ObjectOrEmpty("profiles");

    public JsonElement Audio => Root.ObjectOrEmpty("audio");

    public JsonElement Network => Root.ObjectOrEmpty("network");

    public IReadOnlyList<JsonElement> NetworkDevices => Network.ArrayOrEmpty("devices");

    public JsonElement Sync => Root.ObjectOrEmpty("sync");

    public IReadOnlyList<JsonElement> Displays => Root.ArrayOrEmpty("displays");

    public IReadOnlyList<JsonElement> Adapters => Root.ArrayOrEmpty("adapters");

    public IReadOnlyList<JsonElement> Drives => Root.ArrayOrEmpty("drives");

    public bool IsNetworkRefreshing => Network.PayloadIsRefreshing("devices");

    public bool IsAdaptersRefreshing => Root.PayloadIsRefreshing("adapters");

    public bool IsDrivesRefreshing => Root.PayloadIsRefreshing("drives");

    public bool HasPendingDeviceData => IsNetworkRefreshing || IsAdaptersRefreshing || IsDrivesRefreshing;

    public bool HotkeyEnabled =>
        Settings
            .ObjectOrEmpty("hotkeys")
            .BoolOr("toggle_panel_enabled", true);

    public string ToggleHotkey =>
        Settings
            .ObjectOrEmpty("hotkeys")
            .StringOr("toggle_panel", "Ctrl+Alt+X");
}

internal sealed class TrayOptions
{
    private static readonly string[] DefaultActionIds =
    {
        "display.popup",
        "display.refresh",
        "display.enable",
        "display.disable",
        "display.make_primary",
        "display.primary",
        "display.power_on",
        "display.power_off",
        "adapter.popup",
        "adapter.enable",
        "adapter.disable",
        "adapter.properties",
        "adapter.info",
        "drive.popup",
        "drive.open",
        "drive.add_network",
        "tab.media",
        "tab.network",
        "tab.adapters",
        "tab.drives",
        "media.audio_output",
        "media.pc_volume",
        "media.display_volume",
        "profile.fallback",
        "network.device.open",
        "network.device.ping",
        "network.manage",
        "header.computer_manager",
        "fallback.options",
    };
    private readonly JsonElement _root;
    private readonly JsonElement _actions;

    private TrayOptions(JsonElement root)
    {
        _root = root.Clone();
        _actions = _root.ObjectOrEmpty("action_icons");
    }

    public static TrayOptions From(JsonElement root) => new(root);

    public bool ShowMediaTab => Bool("show_media_tab", true);
    public bool ShowDisplayProfiles => Bool("show_display_profiles", true);
    public bool ShowAdaptersTab => Bool("show_adapters_tab", true);
    public bool ShowAdaptersPopup => Bool("show_adapters_popup", true);
    public bool ShowNetworkTab => Bool("show_network_tab", true);
    public bool ShowDrivesTab => Bool("show_drives_tab", true);
    public bool ShowDisplaysPopup => Bool("show_displays_popup", true);
    public bool ShowPcVolume => Bool("show_pc_volume", true);
    public bool ShowAudioOutput => Bool("show_audio_output", true);
    public bool ShowDisplayVolume => Bool("show_display_volume", true);
    public bool ShowMediaDisplays => Bool("show_media_displays", true);
    public bool ShowMediaDrives => Bool("show_media_drives", false);
    public bool ShowHomeAssistantIndicator => Bool("show_home_assistant_indicator", true);
    public bool ShowMqttIndicator => Bool("show_mqtt_indicator", true);
    public bool ShowOptionsButton => Bool("show_options_button", true);
    public bool ShowNetworkManagerButton => Bool("show_network_manager_button", true);
    public bool ShowComputerManagerButton => Bool("show_computer_manager_button", true);
    public bool ShowRestartButton => Bool("show_restart_button", true);
    public int MediaProfileColumns => Math.Clamp(_root.IntOr("media_profile_columns", 3), 2, 8);
    public int DisplayGridColumns => Math.Clamp(_root.IntOr("display_grid_columns", 2), 1, 8);
    public IReadOnlyList<string> MediaRowOrder =>
        _root.StringArrayOrEmpty("media_row_order")
            .Concat(new[] { "audio_output" })
            .Prepend("media_displays")
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Where(item => item is "media_displays" or "audio_output")
            .ToArray();
    public IReadOnlySet<string>? VisibleAdapterIds => StringSetOrNull("visible_adapter_ids");
    public IReadOnlySet<string>? VisibleDriveIds => StringSetOrNull("visible_drive_ids", normalizeDrive: true);

    public TrayAction Action(string id)
    {
        var raw = _actions.ObjectOrEmpty(id);
        return new TrayAction(
            raw.StringOr("label", DefaultLabel(id)),
            NormalizeIcon(raw.StringOr("icon", DefaultIcon(id))),
            raw.StringOr("fallback_label", DefaultFallback(id))
        );
    }

    public IEnumerable<string> ActionIconIds()
    {
        foreach (var property in _actions.ObjectProperties())
        {
            var icon = NormalizeIcon(property.Value.StringOr("icon"));
            if (!string.IsNullOrWhiteSpace(icon))
            {
                yield return icon;
            }
        }
        foreach (var id in DefaultActionIds)
        {
            var icon = DefaultIcon(id);
            if (!string.IsNullOrWhiteSpace(icon))
            {
                yield return icon;
            }
        }
    }

    private bool Bool(string key, bool fallback) => _root.BoolOr(key, fallback);

    private IReadOnlySet<string>? StringSetOrNull(string key, bool normalizeDrive = false)
    {
        if (!_root.TryObjectProperty(key, out var value) || value.ValueKind == JsonValueKind.Null)
        {
            return null;
        }
        if (value.ValueKind != JsonValueKind.Array)
        {
            return null;
        }
        var values = value.EnumerateArray()
            .Select(item => item.ValueKind == JsonValueKind.String ? item.GetString() : item.ToString())
            .Where(item => !string.IsNullOrWhiteSpace(item))
            .Select(item => normalizeDrive ? item!.Trim().TrimEnd(':').ToUpperInvariant() : item!.Trim().ToLowerInvariant())
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        return values.Count == 0 ? null : values;
    }

    public static string NormalizeIcon(string? value)
    {
        var text = (value ?? "").Trim();
        if (string.IsNullOrWhiteSpace(text))
        {
            return "";
        }
        return text.StartsWith("mdi:", StringComparison.OrdinalIgnoreCase) ? text : $"mdi:{text}";
    }

    private static string DefaultLabel(string id) => id switch
    {
        "display.popup" => "Displays",
        "adapter.popup" => "Adapters",
        "drive.popup" => "Drives",
        "tab.media" => "Media",
        "tab.network" => "Network",
        "tab.adapters" => "Network adapters",
        "tab.drives" => "Drives",
        "fallback.options" => "Options",
        "network.manage" => "Manage network devices",
        "header.computer_manager" => "Open Computer Manager",
        _ => id.Replace(".", " ", StringComparison.Ordinal).Replace("_", " ", StringComparison.Ordinal),
    };

    private static string DefaultFallback(string id) => id switch
    {
        "display.popup" => "Displays",
        "adapter.popup" => "Adapters",
        "drive.popup" => "Drives",
        "fallback.options" => "Options",
        "header.computer_manager" => "PC",
        "network.manage" => "Manage",
        _ => DefaultLabel(id),
    };

    private static string DefaultIcon(string id) => id switch
    {
        "display.popup" => "mdi:monitor-multiple",
        "display.refresh" => "mdi:refresh",
        "display.enable" => "mdi:monitor",
        "display.disable" => "mdi:monitor-off",
        "display.make_primary" => "mdi:monitor-star",
        "display.primary" => "mdi:monitor-star",
        "display.power_on" => "mdi:power-on",
        "display.power_off" => "mdi:power-off",
        "adapter.popup" => "mdi:lan",
        "adapter.enable" => "mdi:lan-connect",
        "adapter.disable" => "mdi:lan-disconnect",
        "adapter.properties" => "mdi:cog",
        "adapter.info" => "mdi:information-outline",
        "drive.popup" => "mdi:harddisk",
        "drive.open" => "mdi:folder-open",
        "drive.add_network" => "mdi:plus-network",
        "tab.media" => "mdi:multimedia",
        "tab.network" => "mdi:lan",
        "tab.adapters" => "mdi:lan-connect",
        "tab.drives" => "mdi:harddisk",
        "media.audio_output" => "mdi:volume-high",
        "media.pc_volume" => "mdi:desktop-tower-monitor",
        "media.display_volume" => "mdi:television",
        "profile.fallback" => "mdi:monitor",
        "network.device.open" => "mdi:open-in-new",
        "network.device.ping" => "mdi:network-pos",
        "network.manage" => "mdi:application-cog",
        "header.computer_manager" => "mdi:desktop-tower-monitor",
        "fallback.options" => "mdi:cog",
        _ => "",
    };
}

internal sealed record TrayAction(string Label, string Icon, string FallbackLabel);

internal static class JsonElementExtensions
{
    public static bool TryObjectProperty(
        this JsonElement element,
        string name,
        out JsonElement value
    )
    {
        if (element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out value))
        {
            return true;
        }
        value = default;
        return false;
    }

    public static JsonElement ObjectOrEmpty(this JsonElement element, string name)
    {
        if (element.TryObjectProperty(name, out var value) && value.ValueKind == JsonValueKind.Object)
        {
            return value;
        }
        using var document = JsonDocument.Parse("{}");
        return document.RootElement.Clone();
    }

    public static IReadOnlyList<JsonElement> ArrayOrEmpty(this JsonElement element, string name)
    {
        if (!element.TryObjectProperty(name, out var value))
        {
            return Array.Empty<JsonElement>();
        }
        return value.ArrayPayloadOrEmpty();
    }

    public static IReadOnlyList<JsonElement> AsArrayOrEmpty(this JsonElement element)
    {
        if (element.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<JsonElement>();
        }
        return element.EnumerateArray().Select(child => child.Clone()).ToArray();
    }

    public static IReadOnlyList<JsonElement> ArrayPayloadOrEmpty(this JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Array)
        {
            return element.EnumerateArray().Select(child => child.Clone()).ToArray();
        }
        if (
            element.ValueKind == JsonValueKind.Object
            && element.TryGetProperty("value", out var value)
            && value.ValueKind == JsonValueKind.Array
        )
        {
            return value.EnumerateArray().Select(child => child.Clone()).ToArray();
        }
        return Array.Empty<JsonElement>();
    }

    public static bool PayloadIsRefreshing(this JsonElement element, string name)
    {
        if (!element.TryObjectProperty(name, out var value) || value.ValueKind != JsonValueKind.Object)
        {
            return false;
        }
        if (!value.TryGetProperty("error", out var error) || error.ValueKind != JsonValueKind.String)
        {
            return false;
        }
        var message = error.GetString();
        return message?.Contains("refreshing", StringComparison.OrdinalIgnoreCase) == true;
    }

    public static IReadOnlyList<string> StringArrayOrEmpty(this JsonElement element, string name)
    {
        if (!element.TryObjectProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<string>();
        }
        return value.EnumerateArray()
            .Select(child => child.ValueKind == JsonValueKind.String ? child.GetString() : child.ToString())
            .Where(child => !string.IsNullOrWhiteSpace(child))
            .Select(child => child!)
            .ToArray();
    }

    public static IEnumerable<JsonProperty> ObjectProperties(this JsonElement element)
    {
        return element.ValueKind == JsonValueKind.Object
            ? element.EnumerateObject()
            : Enumerable.Empty<JsonProperty>();
    }

    public static JsonElement ObjectOrEmpty(this JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            return element;
        }
        using var document = JsonDocument.Parse("{}");
        return document.RootElement.Clone();
    }

    public static string StringOr(this JsonElement element, string name, string fallback = "")
    {
        if (!element.TryObjectProperty(name, out var value))
        {
            return fallback;
        }
        return value.ValueKind switch
        {
            JsonValueKind.String => value.GetString() ?? fallback,
            JsonValueKind.Number => value.ToString(),
            JsonValueKind.True => "true",
            JsonValueKind.False => "false",
            _ => fallback,
        };
    }

    public static int IntOr(this JsonElement element, string name, int fallback = 0)
    {
        if (!element.TryObjectProperty(name, out var value))
        {
            return fallback;
        }
        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var intValue))
        {
            return intValue;
        }
        if (value.ValueKind == JsonValueKind.String && int.TryParse(value.GetString(), out intValue))
        {
            return intValue;
        }
        return fallback;
    }

    public static long? LongOrNull(this JsonElement element, string name)
    {
        if (!element.TryObjectProperty(name, out var value))
        {
            return null;
        }
        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var longValue))
        {
            return longValue;
        }
        return null;
    }

    public static bool BoolOr(this JsonElement element, string name, bool fallback = false)
    {
        if (!element.TryObjectProperty(name, out var value))
        {
            return fallback;
        }
        return value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            JsonValueKind.Number => value.TryGetInt32(out var number) && number != 0,
            JsonValueKind.String => IsTruthy(value.GetString()),
            _ => fallback,
        };
    }

    public static string DisplayName(this JsonElement element, string fallback = "")
    {
        var display = element.ObjectOrEmpty("display");
        return element.StringOr("friendly_name")
            .FirstNonEmpty(
                display.StringOr("name"),
                display.StringOr("device_id"),
                fallback
            );
    }

    public static string SourceLabel(this JsonElement source)
    {
        return source.StringOr("label")
            .FirstNonEmpty(source.StringOr("interface_name"), source.StringOr("name"), "Audio");
    }

    public static string FormatBytes(long? value)
    {
        if (value is null)
        {
            return "";
        }
        var units = new[] { "B", "KB", "MB", "GB", "TB" };
        var amount = (double)value.Value;
        var unit = 0;
        while (amount >= 1024 && unit < units.Length - 1)
        {
            amount /= 1024;
            unit++;
        }
        return amount.ToString(unit == 0 ? "0" : "0.0", CultureInfo.InvariantCulture)
            + " "
            + units[unit];
    }

    public static string FirstNonEmpty(this string? value, params string?[] values)
    {
        if (!string.IsNullOrWhiteSpace(value))
        {
            return value;
        }
        foreach (var candidate in values)
        {
            if (!string.IsNullOrWhiteSpace(candidate))
            {
                return candidate;
            }
        }
        return "";
    }

    private static bool IsTruthy(string? value)
    {
        return value?.Trim().ToLowerInvariant() is "1" or "true" or "yes" or "y" or "on";
    }
}
