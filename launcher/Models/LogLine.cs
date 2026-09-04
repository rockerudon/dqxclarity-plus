namespace DqxClarity.Launcher.Models;

/// <summary>A single contiguous span of text with an optional ANSI foreground color.</summary>
public record AnsiRun(string Text, string? HexColor = null);

public class LogLine
{
    public string Level { get; init; } = "info"; // "info" | "error"
    public string Text  { get; init; } = "";     // plain text (ANSI stripped)

    /// <summary>Colored segments parsed from ANSI escape codes. Empty = use Level brush.</summary>
    public IReadOnlyList<AnsiRun> Runs { get; init; } = [];
}

public class ChatTranslation
{
    public string Id { get; init; } = "";
    public bool IsUpdate { get; init; }
    public string Sender { get; init; } = "";
    public string Recipient { get; init; } = "";
    public string Status { get; init; } = "";
    public string Source { get; init; } = "";
    public string Translation { get; init; } = "";
    public string Category { get; init; } = "";
    public string Participants => string.IsNullOrEmpty(Recipient) ? Sender : $"{Sender} → {Recipient}";
    public bool HasOriginal => Source != Translation;
}

public static class ChatHistory
{
    // Capture events reserve their position. Translation completion replaces
    // that row, so cache hits cannot overtake older pending entries.
    public static void Apply(IList<ChatTranslation> rows, ChatTranslation chat, int limit = 200)
    {
        if (!string.IsNullOrEmpty(chat.Id))
        {
            for (var i = 0; i < rows.Count; i++)
            {
                if (rows[i].Id != chat.Id) continue;
                rows[i] = chat;
                return;
            }
        }
        // A late reply must not resurrect a row removed by Clear or the limit.
        if (chat.IsUpdate) return;
        rows.Add(chat);
        while (rows.Count > limit) rows.RemoveAt(0);
    }
}

public class OutgoingChatTranslation
{
    public string Id { get; init; } = "";
    public string Source { get; init; } = "";
    public string Translation { get; init; } = "";
    public string Error { get; init; } = "";
}

public record UpdateInfo(string Version, string Body);

public class DbRow
{
    public long RowId { get; init; }
    public List<string?> Values { get; init; } = [];
    public bool Selected { get; set; }
}

public class DbTableData
{
    public List<string> Columns { get; init; } = [];
    public List<DbRow> Rows { get; init; } = [];
}
