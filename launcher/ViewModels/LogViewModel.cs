using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using DqxClarity.Launcher.Models;
using DqxClarity.Launcher.Services;

namespace DqxClarity.Launcher.ViewModels;

public partial class LogViewModel : ObservableObject
{
    private const int MaxLines = 1000;
    private const int MaxChatTranslations = 200;
    private const int GameChatCharacterLimit = GameChatInputService.MaxChars;
    private readonly ProcessService _processSvc;
    private readonly GameChatInputService _chatInput = new();

    public event Action? NavigateBack;
    public event Action? CloseApp;

    [ObservableProperty] private bool _exitedWithError;
    [ObservableProperty] private bool _hasExited;
    [ObservableProperty] private bool _showStopWarning;
    [ObservableProperty] private string _statusTitle = "dqxclarity - running";
    [ObservableProperty] private string _activeLogTab = "dqxclarity";
    [ObservableProperty] private string _outgoingText = "";
    [ObservableProperty] private string _outgoingJapanese = "";
    [ObservableProperty] private string _outgoingStatus = "";
    [ObservableProperty] private bool _isTranslatingOutgoing;
    [ObservableProperty] private bool _autoTranslateOutgoing;

    public string OutgoingActionLabel => AutoTranslateOutgoing ? "Translate & Send" : "Send to DQX";
    public bool HasOutgoingStatus => !string.IsNullOrWhiteSpace(OutgoingStatus);
    public string OutgoingCharacterCount => $"{OutgoingText.Length}/{GameChatCharacterLimit}";

    public ObservableCollection<LogLine> Lines { get; } = [];
    public ObservableCollection<ChatTranslation> ChatTranslations { get; } = [];
    public Text2ClipboardViewModel Text2Clipboard { get; }
    public bool HasNoLines => Lines.Count == 0;
    public bool HasNoChatTranslations => ChatTranslations.Count == 0;

    public LogViewModel(ProcessService processSvc, Text2ClipboardViewModel text2Clipboard)
    {
        _processSvc = processSvc;
        Text2Clipboard = text2Clipboard;
        _processSvc.LogLine       += OnLogLine;
        _processSvc.ChatTranslationReceived += OnChatTranslation;
        _processSvc.ProcessExited += OnProcessExited;
    }

    public void UpdateTitle(string version)
    {
        StatusTitle = ExitedWithError
            ? "dqxclarity - exited with error"
            : $"dqxclarity - running (v{version})";
    }

    private void OnLogLine(LogLine line) =>
        Avalonia.Threading.Dispatcher.UIThread.Post(() =>
        {
            Lines.Add(line);
            while (Lines.Count > MaxLines)
                Lines.RemoveAt(0);
            OnPropertyChanged(nameof(HasNoLines));
        });

    private void OnChatTranslation(ChatTranslation chat) =>
        Avalonia.Threading.Dispatcher.UIThread.Post(() =>
        {
            ChatHistory.Apply(ChatTranslations, chat, MaxChatTranslations);
            OnPropertyChanged(nameof(HasNoChatTranslations));
        });

    private void OnProcessExited(bool isError) =>
        Avalonia.Threading.Dispatcher.UIThread.Post(() =>
        {
            var userStop = _userInitiatedStop;
            _userInitiatedStop = false;

            if (userStop)
            {
                NavigateBack?.Invoke();
                return;
            }
            if (!isError)
            {
                CloseApp?.Invoke();
                return;
            }
            ExitedWithError = true;
            HasExited = true;
            StatusTitle = "dqxclarity - exited with error";
        });

    private bool _userInitiatedStop;

    [RelayCommand]
    private void Stop()
    {
        _userInitiatedStop = true;
        _processSvc.Stop();
    }

    [RelayCommand]
    private void Back() => NavigateBack?.Invoke();

    private bool CanSendOutgoing() =>
        !IsTranslatingOutgoing && !string.IsNullOrWhiteSpace(OutgoingText);

    partial void OnOutgoingTextChanged(string value)
    {
        OnPropertyChanged(nameof(OutgoingCharacterCount));
        SendOutgoingCommand.NotifyCanExecuteChanged();
    }

    partial void OnIsTranslatingOutgoingChanged(bool value) =>
        SendOutgoingCommand.NotifyCanExecuteChanged();

    partial void OnOutgoingStatusChanged(string value) =>
        OnPropertyChanged(nameof(HasOutgoingStatus));

    partial void OnAutoTranslateOutgoingChanged(bool value)
    {
        OnPropertyChanged(nameof(OutgoingActionLabel));
        OutgoingJapanese = "";
        OutgoingStatus = "";
    }

    [RelayCommand(CanExecute = nameof(CanSendOutgoing))]
    private async Task SendOutgoing()
    {
        IsTranslatingOutgoing = true;
        try
        {
            var output = OutgoingText.Trim();
            if (AutoTranslateOutgoing)
            {
                OutgoingStatus = "Translating to Japanese…";
                var result = await _processSvc.TranslateOutgoingChatAsync(output);
                if (!string.IsNullOrWhiteSpace(result.Error))
                {
                    OutgoingStatus = result.Error;
                    return;
                }
                output = result.Translation;
                if (output.Length > GameChatCharacterLimit)
                {
                    OutgoingStatus = $"Translation is {output.Length} characters; the game limit is {GameChatCharacterLimit}. Shorten the message.";
                    return;
                }
                OutgoingJapanese = output;
            }
            else
                OutgoingJapanese = "";

            OutgoingStatus = await WriteToDqxChatAsync(output);
        }
        catch (Exception ex)
        {
            OutgoingStatus = $"Could not prepare or send the message: {ex.Message}";
        }
        finally
        {
            IsTranslatingOutgoing = false;
        }
    }

    private async Task<string> WriteToDqxChatAsync(string text)
    {
        if (string.IsNullOrWhiteSpace(text) || text.Length > GameChatCharacterLimit || text.Any(char.IsControl))
            return $"Use a single-line message with 1–{GameChatCharacterLimit} characters.";

        if (!LocaleEmulatorService.EnsureInjectedIntoRunningGame(out var pid, out var injectedNow, out var error))
            return error;

        if (!await Text2Clipboard.StageForGameInputAsync(text))
            return "Clipboard is not available.";

        // A newly injected hook starts a small watcher that subclasses the game window.
        if (injectedNow)
            await Task.Delay(500);

        if (!_chatInput.ActivateAndPaste(pid, out var inputError))
            return inputError;

        return AutoTranslateOutgoing
            ? $"Translated; input sent to DQX ({text.Length}/{GameChatCharacterLimit}). Check the chat box before pressing Enter."
            : $"Input sent to DQX ({text.Length}/{GameChatCharacterLimit}). Check the chat box before pressing Enter.";
    }

    [RelayCommand]
    private void DismissStopWarning() => ShowStopWarning = false;

    public void Reset()
    {
        Lines.Clear();
        ChatTranslations.Clear();
        ExitedWithError = false;
        HasExited = false;
        StatusTitle = "dqxclarity - running";
        ActiveLogTab = "dqxclarity";
        OutgoingText = "";
        OutgoingJapanese = "";
        OutgoingStatus = "";
        IsTranslatingOutgoing = false;
        AutoTranslateOutgoing = false;
        OnPropertyChanged(nameof(HasNoLines));
        OnPropertyChanged(nameof(HasNoChatTranslations));
    }

    public bool TryClose()
    {
        if (_processSvc.IsRunning())
        {
            ShowStopWarning = true;
            return false; // block close
        }
        return true;
    }
}
