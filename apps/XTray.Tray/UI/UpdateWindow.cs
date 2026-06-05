using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text.Json.Serialization;
using System.Windows;
using System.Windows.Controls;
using XTray.Tray.Backend;
using Button = System.Windows.Controls.Button;
using CheckBox = System.Windows.Controls.CheckBox;
using DataBinding = System.Windows.Data.Binding;
using MessageBox = System.Windows.MessageBox;
using Orientation = System.Windows.Controls.Orientation;
using ProgressBar = System.Windows.Controls.ProgressBar;
using WpfHorizontalAlignment = System.Windows.HorizontalAlignment;

namespace XTray.Tray.UI;

internal sealed class UpdateWindow : Window
{
    private static readonly HttpClient Http = CreateHttpClient();

    private readonly JsonRpcClient _backend;
    private readonly CheckBox _showBetas = new()
    {
        Content = "Show public beta releases",
        IsChecked = true,
        Margin = new Thickness(0, 0, 0, 8),
    };
    private readonly DataGrid _releases = new()
    {
        AutoGenerateColumns = false,
        IsReadOnly = true,
        SelectionMode = DataGridSelectionMode.Single,
        SelectionUnit = DataGridSelectionUnit.FullRow,
        MinHeight = 210,
    };
    private readonly ProgressBar _downloadProgress = new()
    {
        Height = 18,
        Minimum = 0,
        Maximum = 100,
    };
    private readonly ProgressBar _installProgress = new()
    {
        Height = 18,
        Minimum = 0,
        Maximum = 100,
    };
    private readonly TextBlock _status = new()
    {
        Text = "Checking for updates...",
        TextWrapping = TextWrapping.Wrap,
        Margin = new Thickness(0, 8, 0, 0),
    };
    private readonly Button _refresh;
    private readonly Button _install;
    private readonly Button _close;
    private List<UpdateReleaseInfo> _allReleases = new();
    private bool _busy;

    public UpdateWindow(JsonRpcClient backend)
    {
        _backend = backend;
        Title = "XTray Updates";
        Width = 720;
        Height = 520;
        MinWidth = 620;
        MinHeight = 440;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;

        _refresh = Button("Refresh", RefreshAsync);
        _install = Button("Install Selected", InstallSelectedAsync);
        _close = new Button
        {
            Content = "Close",
            MinWidth = 90,
            Padding = new Thickness(12, 5, 12, 5),
            Margin = new Thickness(8, 0, 0, 0),
        };
        _close.Click += (_, _) => Close();
        _install.IsEnabled = false;

        Build();
        Loaded += async (_, _) => await RefreshAsync();
        _showBetas.Checked += (_, _) => ApplyReleaseFilter();
        _showBetas.Unchecked += (_, _) => ApplyReleaseFilter();
        _releases.SelectionChanged += (_, _) => UpdateInstallButton();
    }

    public bool ShouldQuitAfterInstall { get; private set; }

    internal static IReadOnlyList<UpdateReleaseInfo> FilterReleases(
        IEnumerable<UpdateReleaseInfo> releases,
        bool showBetas
    )
    {
        return releases
            .Where(release => showBetas || !release.Prerelease)
            .ToArray();
    }

    private void Build()
    {
        _releases.Columns.Add(new DataGridTextColumn
        {
            Header = "Version",
            Binding = new DataBinding(nameof(UpdateReleaseInfo.Version)),
            Width = new DataGridLength(120),
        });
        _releases.Columns.Add(new DataGridTextColumn
        {
            Header = "Channel",
            Binding = new DataBinding(nameof(UpdateReleaseInfo.Channel)),
            Width = new DataGridLength(90),
        });
        _releases.Columns.Add(new DataGridTextColumn
        {
            Header = "Title",
            Binding = new DataBinding(nameof(UpdateReleaseInfo.DisplayTitle)),
            Width = new DataGridLength(1, DataGridLengthUnitType.Star),
        });
        _releases.Columns.Add(new DataGridTextColumn
        {
            Header = "Published",
            Binding = new DataBinding(nameof(UpdateReleaseInfo.PublishedDisplay)),
            Width = new DataGridLength(150),
        });
        _releases.Columns.Add(new DataGridTextColumn
        {
            Header = "Size",
            Binding = new DataBinding(nameof(UpdateReleaseInfo.SizeDisplay)),
            Width = new DataGridLength(95),
        });

        var root = new DockPanel { Margin = new Thickness(14) };
        var footer = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = WpfHorizontalAlignment.Right,
            Margin = new Thickness(0, 12, 0, 0),
        };
        footer.Children.Add(_refresh);
        footer.Children.Add(_install);
        footer.Children.Add(_close);
        DockPanel.SetDock(footer, Dock.Bottom);
        root.Children.Add(footer);

        var content = new StackPanel();
        content.Children.Add(new TextBlock
        {
            Text = "Available releases",
            FontSize = 17,
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(0, 0, 0, 8),
        });
        content.Children.Add(_showBetas);
        content.Children.Add(_releases);
        content.Children.Add(ProgressRow("Download", _downloadProgress));
        content.Children.Add(ProgressRow("Installation", _installProgress));
        content.Children.Add(_status);
        root.Children.Add(content);
        Content = root;
    }

    private async Task RefreshAsync()
    {
        if (_busy)
        {
            return;
        }
        SetBusy(true, "Checking public releases...");
        try
        {
            ResetProgress();
            var releases = await _backend.CallAsync<List<UpdateReleaseInfo>>(
                "updates.releases",
                new { include_prereleases = true },
                timeout: TimeSpan.FromSeconds(30)
            );
            _allReleases = releases ?? new List<UpdateReleaseInfo>();
            ApplyReleaseFilter();
            _status.Text = _allReleases.Count == 0
                ? "No newer public releases found."
                : "Select a release to download and install.";
        }
        catch (Exception ex)
        {
            _allReleases.Clear();
            ApplyReleaseFilter();
            _status.Text = ex.Message;
            MessageBox.Show(ex.Message, "XTray Updates", MessageBoxButton.OK, MessageBoxImage.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task InstallSelectedAsync()
    {
        if (_busy || _releases.SelectedItem is not UpdateReleaseInfo release)
        {
            return;
        }

        SetBusy(true, $"Downloading XTray {release.Version}...");
        try
        {
            ResetProgress();
            var installer = await DownloadInstallerAsync(release);
            _downloadProgress.IsIndeterminate = false;
            _downloadProgress.Value = 100;

            _status.Text = "Preparing installer...";
            _installProgress.Value = 0;
            _installProgress.IsIndeterminate = true;
            await _backend.CallAsync(
                "updates.install",
                new { installer },
                timeout: TimeSpan.FromSeconds(30)
            );
            _installProgress.IsIndeterminate = false;
            _installProgress.Value = 100;
            ShouldQuitAfterInstall = true;
            _status.Text = "Installation is starting. XTray will close and relaunch after the update.";
            await Task.Delay(1200);
            Close();
        }
        catch (Exception ex)
        {
            _installProgress.IsIndeterminate = false;
            _status.Text = ex.Message;
            MessageBox.Show(ex.Message, "XTray Updates", MessageBoxButton.OK, MessageBoxImage.Error);
            SetBusy(false);
        }
    }

    private async Task<string> DownloadInstallerAsync(UpdateReleaseInfo release)
    {
        if (string.IsNullOrWhiteSpace(release.Asset.DownloadUrl))
        {
            throw new InvalidOperationException("The selected release does not include a downloadable installer.");
        }

        var fileName = SafeAssetName(release.Asset.Name);
        var directory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "XTray",
            "updates"
        );
        Directory.CreateDirectory(directory);
        var target = Path.Combine(directory, fileName);
        var temp = target + ".download";

        using var response = await Http.GetAsync(
            release.Asset.DownloadUrl,
            HttpCompletionOption.ResponseHeadersRead
        );
        response.EnsureSuccessStatusCode();
        var expectedSize = release.Asset.Size > 0
            ? release.Asset.Size
            : response.Content.Headers.ContentLength;
        _downloadProgress.IsIndeterminate = expectedSize is null or <= 0;

        long total = 0;
        await using (var source = await response.Content.ReadAsStreamAsync())
        await using (var destination = new FileStream(
            temp,
            FileMode.Create,
            FileAccess.Write,
            FileShare.None,
            bufferSize: 128 * 1024,
            options: FileOptions.Asynchronous | FileOptions.SequentialScan
        ))
        {
            var buffer = new byte[128 * 1024];
            while (true)
            {
                var read = await source.ReadAsync(buffer);
                if (read == 0)
                {
                    break;
                }
                await destination.WriteAsync(buffer.AsMemory(0, read));
                total += read;
                if (expectedSize is > 0)
                {
                    _downloadProgress.Value = Math.Clamp(total * 100.0 / expectedSize.Value, 0, 100);
                    _status.Text = $"Downloading XTray {release.Version}: {FormatBytes(total)} of {FormatBytes(expectedSize.Value)}";
                }
                else
                {
                    _status.Text = $"Downloading XTray {release.Version}: {FormatBytes(total)}";
                }
            }
        }

        if (release.Asset.Size is > 0 && total != release.Asset.Size.Value)
        {
            File.Delete(temp);
            throw new InvalidOperationException(
                $"Downloaded installer size mismatch: expected {release.Asset.Size.Value}, got {total}."
            );
        }

        File.Move(temp, target, overwrite: true);
        return target;
    }

    private void ApplyReleaseFilter()
    {
        var filtered = FilterReleases(_allReleases, _showBetas.IsChecked == true);
        _releases.ItemsSource = filtered;
        if (filtered.Count > 0)
        {
            _releases.SelectedIndex = 0;
        }
        else
        {
            _releases.SelectedItem = null;
        }
        if (!_busy)
        {
            _status.Text = filtered.Count == 0
                ? (_showBetas.IsChecked == true ? "No newer public releases found." : "No newer stable releases found.")
                : "Select a release to download and install.";
        }
        UpdateInstallButton();
    }

    private void UpdateInstallButton()
    {
        _install.IsEnabled = !_busy && _releases.SelectedItem is UpdateReleaseInfo;
    }

    private void SetBusy(bool busy, string? status = null)
    {
        _busy = busy;
        if (!string.IsNullOrWhiteSpace(status))
        {
            _status.Text = status;
        }
        _showBetas.IsEnabled = !busy;
        _releases.IsEnabled = !busy;
        _refresh.IsEnabled = !busy;
        _close.IsEnabled = !busy;
        UpdateInstallButton();
    }

    private void ResetProgress()
    {
        _downloadProgress.IsIndeterminate = false;
        _downloadProgress.Value = 0;
        _installProgress.IsIndeterminate = false;
        _installProgress.Value = 0;
    }

    private Button Button(string text, Func<Task> action)
    {
        var button = new Button
        {
            Content = text,
            MinWidth = 110,
            Padding = new Thickness(12, 5, 12, 5),
            Margin = new Thickness(8, 0, 0, 0),
        };
        button.Click += async (_, _) =>
        {
            try
            {
                await action();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.Message, "XTray Updates", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        };
        return button;
    }

    private static UIElement ProgressRow(string label, ProgressBar progress)
    {
        var grid = new Grid { Margin = new Thickness(0, 12, 0, 0) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(90) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.Children.Add(new TextBlock
        {
            Text = label,
            VerticalAlignment = VerticalAlignment.Center,
            FontWeight = FontWeights.SemiBold,
        });
        Grid.SetColumn(progress, 1);
        grid.Children.Add(progress);
        return grid;
    }

    private static string SafeAssetName(string name)
    {
        var fileName = Path.GetFileName(name);
        if (!string.Equals(fileName, name, StringComparison.Ordinal)
            || !fileName.StartsWith("XTray-Setup-", StringComparison.OrdinalIgnoreCase)
            || !fileName.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException($"Unsafe update asset name: {name}");
        }
        return fileName;
    }

    private static string FormatBytes(long bytes)
    {
        string[] units = { "B", "KB", "MB", "GB" };
        double value = bytes;
        var unit = 0;
        while (value >= 1024 && unit < units.Length - 1)
        {
            value /= 1024;
            unit++;
        }
        return $"{value:0.##} {units[unit]}";
    }

    private static HttpClient CreateHttpClient()
    {
        var client = new HttpClient();
        client.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue("XTray", "updater"));
        return client;
    }
}

internal sealed class UpdateReleaseInfo
{
    [JsonPropertyName("version")]
    public string Version { get; set; } = "";

    [JsonPropertyName("release_url")]
    public string ReleaseUrl { get; set; } = "";

    [JsonPropertyName("asset")]
    public UpdateAssetInfo Asset { get; set; } = new();

    [JsonPropertyName("title")]
    public string Title { get; set; } = "";

    [JsonPropertyName("published_at")]
    public string PublishedAt { get; set; } = "";

    [JsonPropertyName("prerelease")]
    public bool Prerelease { get; set; }

    public string Channel => Prerelease ? "Beta" : "Stable";

    public string DisplayTitle => string.IsNullOrWhiteSpace(Title) ? $"XTray {Version}" : Title;

    public string PublishedDisplay => DateTimeOffset.TryParse(PublishedAt, out var value)
        ? value.LocalDateTime.ToString("yyyy-MM-dd HH:mm")
        : "";

    public string SizeDisplay => Asset.Size is > 0 ? UpdateWindowFormat.FormatBytes(Asset.Size.Value) : "";
}

internal sealed class UpdateAssetInfo
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("download_url")]
    public string DownloadUrl { get; set; } = "";

    [JsonPropertyName("size")]
    public long? Size { get; set; }
}

internal static class UpdateWindowFormat
{
    public static string FormatBytes(long bytes)
    {
        string[] units = { "B", "KB", "MB", "GB" };
        double value = bytes;
        var unit = 0;
        while (value >= 1024 && unit < units.Length - 1)
        {
            value /= 1024;
            unit++;
        }
        return $"{value:0.##} {units[unit]}";
    }
}
