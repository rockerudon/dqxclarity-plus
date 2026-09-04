// hook for network text template string replacements. (8.0: DQXGame.exe+53A750)
/*
    55                    - push ebp
    8B EC                 - mov ebp,esp
    81 EC DC030000        - sub esp,000003DC
    A1 C0211502           - mov eax,[DQXGame.exe+1CA21C0]   ; /GS cookie
    33 C5                 - xor eax,ebp
    89 45 FC              - mov [ebp-04],eax
    8B 45 14              - mov eax,[ebp+14]
    8B 0D D0E41702        - mov ecx,[DQXGame.exe+1CCE4D0]
    89 45 D8              - mov [ebp-28],eax
    64 A1 2C000000        - mov eax,fs:[0000002C]
    53                    - push ebx
    56                    - push esi
*/
(function() {
    const hookName = '{{HOOK_NAME}}';
    const signature = '{{SIGNATURE}}';

    const baseAddr = Process.enumerateModules()[0].base;
    const baseSize = Process.enumerateModules()[0].size;

    const results = Memory.scanSync(baseAddr, baseSize, signature);
    if (results.length != 1) {
        send({
            type: 'error',
            payload: `[${hookName}] Function not found with signature`
        });
        return;
    }

    const funcAddress = results[0].address;
    send({
        type: 'info',
        payload: `[${hookName}] Found at: ${funcAddress}`
    });

    // cache for translations to avoid blocking on repeated text
    const translationCache = new Map();
    const translatedValues = new Set();
    const chatHistoryEnabled = {{CHAT_HISTORY_ENABLED}};
    const debugLogging = {{DEBUG_LOGGING}};
    const speakerTraceSamples = new Set();
    const speakerTraceCounts = { standalone: 0, prefix: 0, composed: 0 };
    let speakerCaptureCount = 0;
    let requestSequence = 0;

    // Temporary diagnostic: bounded reads of this formatter's arguments, not
    // a new hook or a memory write. Do not log complete player messages.
    function inspectSpeakerArgument(address) {
        if (!address) return { value: 'unavailable' };
        const result = { value: address.toString() };
        try {
            const range = Process.findRangeByAddress(address);
            if (!range || range.protection.indexOf('r') === -1) return result;
            const remaining = range.base.add(range.size).sub(address).toInt32();
            const count = Math.min(64, remaining);
            if (count <= 0) return result;
            const bytes = new Uint8Array(address.readByteArray(count));
            const length = bytes.indexOf(0);
            if (length <= 0) return result;
            const text = address.readUtf8String(length);
            if (!/[\x00-\x03\x05-\x1f\x7f]/.test(text)) result.text = text;
        } catch (_) {
            // Integers and non-text arguments are expected; never dereference
            // further or let a diagnostic interrupt formatting.
        }
        return result;
    }

    function traceSpeaker(invocation, category, originalText) {
        if (!debugLogging || !chatHistoryEnabled || category.indexOf('<%sM_speaker>') === -1) return;
        const opening = category.indexOf('[<%sM_chat>]') !== -1 ? '[' : '"';
        const stage = category === '<%sM_speaker>' ? 'standalone' :
            (originalText.indexOf(opening) === -1 ? 'prefix' : 'composed');
        const speaker = originalText.split(opening, 1)[0].slice(0, 48);
        const key = `${stage}:${speaker}`;
        if (speakerTraceCounts[stage] >= 4 || speakerTraceSamples.has(key)) return;
        speakerTraceSamples.add(key);
        speakerTraceCounts[stage]++;
        const visibleSpeaker = speaker.replace(/[\s\x00-\x1f\x7f]/g, '');
        function describe(argument) {
            const result = { value: argument.value };
            if (argument.text !== undefined) {
                result.textBytes = utf8ByteLength(argument.text);
                result.matchesSpeaker = argument.text.replace(/[\s\x00-\x1f\x7f]/g, '') === visibleSpeaker;
                if (['M_speaker', '<%sM_speaker>', 'M_chat', '<%sM_chat>'].includes(argument.text))
                    result.field = argument.text;
            }
            return result;
        }
        send({ type: 'info', payload: `[chat-speaker-trace] ${JSON.stringify({
            stage, category, speaker,
            caller: invocation.speakerCaller,
            before: invocation.speakerBefore ? invocation.speakerBefore.map(describe) : undefined,
            after: (invocation.speakerArgs || []).map(inspectSpeakerArgument).map(describe)
        })}` });
    }

    function utf8ByteLength(value) {
        return unescape(encodeURIComponent(value)).length;
    }

    function isChatCategory(category) {
        return category === '<%sM_CW_stamp>' ||
            category.indexOf('<%sM_chat>') !== -1;
    }

    function isHistorySeparator(category, text) {
        // These are UI separators, not player messages. Leave their layout
        // and control sequences entirely to the game's formatter.
        return category.indexOf('<%sW_DELIMITER>') !== -1 ||
            /^\s*-{3,}\s*Current (?:Real )?Time\b/i.test(text);
    }

    function truncateUtf8(value, maxBytes) {
        const encoded = unescape(encodeURIComponent(value));
        if (encoded.length <= maxBytes) {
            return value;
        }
        for (let length = maxBytes; length >= 0; length--) {
            try {
                return decodeURIComponent(escape(encoded.slice(0, length)));
            } catch (e) {
                // Continue until the cut is on a valid UTF-8 boundary.
            }
        }
        return "";
    }

    function applyReplacement(address, sourceBytes, replacement, context, originalText, updateContext) {
        // A different formatting thread may have reused this buffer while the
        // reply was in flight. Never write into a changed string or context.
        if (context.add(0x10).readU32() !== sourceBytes ||
            context.add(0x18).readU32() !== address.add(sourceBytes).toUInt32() ||
            address.readUtf8String(sourceBytes) !== originalText) {
            return null;
        }
        // This formatter's return value is consumed from its original inline
        // buffer. Repointing the context fields produced a successful Python
        // log entry but left Story So Far in Japanese on screen. The working
        // BR hook writes this exact address; retain that behavior while
        // bounding the replacement to the known source-buffer size.
        const safeReplacement = truncateUtf8(replacement, sourceBytes);
        if (!safeReplacement) {
            return null;
        }
        address.writeUtf8String(safeReplacement);
        if (updateContext) {
            // This formatter is a string builder. Nested templates read these
            // fields again, so they must describe the shorter replacement or
            // the next read includes our NUL terminator and fails UTF-8 decode.
            const replacementBytes = utf8ByteLength(safeReplacement);
            context.add(0x10).writeU32(replacementBytes);
            context.add(0x18).writeU32(address.add(replacementBytes).toUInt32());
        }
        return safeReplacement;
    }
    Interceptor.attach(funcAddress, {
        onEnter: function (args) {
            // bool __cdecl ProcessTemplateString(int a1, int a2, unsigned int a3, int a4)
            // arg1 is the pointer to the context
            this.arg1 = args[0];
            if (debugLogging && chatHistoryEnabled && speakerCaptureCount < 32) {
                this.speakerArgs = [args[1], args[2], args[3]];
                this.speakerCaller = this.returnAddress ? this.returnAddress.toString() : 'unavailable';
                try {
                    const template = args[0].add(0x1c).readPointer();
                    const category = template.isNull() ? '' : template.readUtf8String();
                    if (category && category.indexOf('<%sM_speaker>') !== -1) {
                        speakerCaptureCount++;
                        this.speakerBefore = this.speakerArgs.map(inspectSpeakerArgument);
                    }
                } catch (_) {
                    // The template may not be initialized until the function runs.
                }
            }
        },

        onLeave: function(retval) {
            try {
                // only process if function returned true
                if (retval.toInt32() !== 1) {
                    return;
                }

                const arg1 = this.arg1;
                if (!arg1 || arg1.isNull()) {
                    return;
                }

                // 0x10 of context - string length
                const stringLength = arg1.add(0x10).readU32();

                // 0x18 of context - address to end of string buffer
                const endOfStringAddr = arg1.add(0x18).readU32();

                // calculate start of string by subtracting length from end address
                const startOfStringAddr = ptr(endOfStringAddr - stringLength);

                // read string content
                if (startOfStringAddr.isNull() || stringLength === 0 ||
                    stringLength > 16384 || endOfStringAddr < stringLength) {
                    return;
                }

                let originalText;
                try {
                    originalText = startOfStringAddr.readUtf8String(stringLength);
                } catch (e) {
                    // Never retry without a length: that can consume adjacent
                    // UI strings when an intermediate builder value is invalid.
                    return;
                }

                // 0x1c of context - pointer to template string
                const templateStringPtr = arg1.add(0x1c).readPointer();
                if (templateStringPtr.isNull()) {
                    return;
                }

                const category = templateStringPtr.readUtf8String();

                if (!originalText || !category) {
                    return;
                }
                if (isHistorySeparator(category, originalText)) {
                    return;
                }
                traceSpeaker(this, category, originalText);
                // Romanize only the standalone sender before the composed
                // chat row consumes it. Never change an already padded prefix.
                const isChatSpeaker = category === '<%sM_speaker>';
                if (isChatSpeaker && !chatHistoryEnabled) {
                    return;
                }

                // Chat history translation is non-blocking. Python publishes
                // completed entries to the launcher without delaying the game.
                if (isChatCategory(category)) {
                    if (!chatHistoryEnabled) {
                        return;
                    }
                    const responseType = `chat_replacement:${++requestSequence}`;
                    send({
                        type: 'get_chat_replacement',
                        text: originalText,
                        category: category,
                        instance: startOfStringAddr.toString(),
                        response_type: responseType
                    });

                    var chatReplacement = null;
                    var chatOp = recv(responseType, function(message) {
                        chatReplacement = message.text;
                    });
                    chatOp.wait();

                    if (chatReplacement !== null && chatReplacement !== originalText) {
                        const written = applyReplacement(
                            startOfStringAddr,
                            stringLength,
                            chatReplacement,
                            arg1,
                            originalText,
                            true
                        );
                        if (written) {
                            translatedValues.add(`${category}:${written}`);
                        }
                    }
                    return;
                }

                if (translatedValues.has(`${category}:${originalText}`)) {
                    return;
                }

                // create cache key combining category and text
                const cacheKey = `${category}:${originalText}`;

                // check cache first
                if (translationCache.has(cacheKey)) {
                    const cachedReplacement = translationCache.get(cacheKey);
                    if (cachedReplacement && cachedReplacement !== originalText) {
                        const written = applyReplacement(startOfStringAddr, stringLength, cachedReplacement, arg1, originalText, isChatSpeaker);
                        if (written) {
                            translatedValues.add(`${category}:${written}`);
                        }
                    }
                    return;
                }

                // send to Python for translation/lookup
                const responseType = `replacement:${++requestSequence}`;
                send({
                    type: 'get_replacement',
                    text: originalText,
                    category: category,
                    response_type: responseType
                });

                // block and wait for Python response
                var replacement = null;
                var op = recv(responseType, function(message) {
                    replacement = message.text;
                });
                op.wait();

                if (replacement !== null) {
                    // write replacement to memory if different
                    if (replacement !== originalText) {
                        const written = applyReplacement(startOfStringAddr, stringLength, replacement, arg1, originalText, isChatSpeaker);
                        if (written) {
                            translationCache.set(cacheKey, written);
                            translatedValues.add(`${category}:${written}`);
                        } else {
                            translationCache.set(cacheKey, null);
                        }
                    } else {
                        translationCache.set(cacheKey, null);
                    }
                }

            } catch (e) {
                send({
                    type: 'error',
                    payload: `[${hookName}] onLeave error: ${e.message}`
                });
            }
        }
    });
})();
