// hook for walkthrough text replacements. (8.0: DQXGame.exe+2E3030)
/*
    55                    - push ebp
    8B EC                 - mov ebp,esp
    83 EC 40              - sub esp,40
    8B 15 C8201702        - mov edx,[DQXGame.exe+1CC20C8]
    53                    - push ebx
    8B D9                 - mov ebx,ecx
    89 5D FC              - mov [ebp-04],ebx
    56                    - push esi
    57                    - push edi
    85 D2                 - test edx,edx
    ...
    ...
 >> E8 337FFFFF           - call DQXGame.exe+2DAFA0   ; <- signature anchors here, callee hooked
 >> 8D B8 EC000000        - lea edi,[eax+000000EC]
    8B CF                 - mov ecx,edi
    8D 51 01              - lea edx,[ecx+01]
    8A 01                 - mov al,[ecx]
    41                    - inc ecx
    84 C0                 - test al,al
    75 F9                 - jne DQXGame.exe+2E3078
    2B CA                 - sub ecx,edx

    to find this, search for walkthrough text:
    メインコマンド『せんれき』の
    ^ is text when you are caught up with the story.
    you are looking for the original source string that is read,
    not the ones that are just written to the screen. to figure
    this out, with the command window closed, update the first
    jp letter with "eee", then open the window. if the window
    shows "eee", then put a "what reads this" breakpoint here.
    should be the entry, "mov al, [ecx]". it should only trigger
    when the command window opens, that's it. from there, go down
    a few instructions and look for a clean place to hook.
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

    // derive callee address dynamically from the call instruction (E8 <rel32>)
    const callAddr = results[0].address;
    const rel32 = callAddr.add(1).readS32();
    const calleeAddr = callAddr.add(5).add(rel32);

    // return address when called from here is always the instruction after the call
    // this makes sure that we only process when our hooked function makes this call
    const expectedReturnAddr = callAddr.add(5);

    send({
        type: 'info',
        payload: `[${hookName}] Found at: ${callAddr}, hooking callee at: ${calleeAddr}`
    });

    // cache for translations to avoid blocking
    const translationCache = new Map();
    // The game may call this formatter again with the text we wrote. Keep a
    // reverse cache so an already translated walkthrough is never sent back
    // through the API.
    const translatedValues = new Set();

    function utf8ByteLength(value) {
        return unescape(encodeURIComponent(value)).length;
    }

    function truncateUtf8(value, maxBytes) {
        const encoded = unescape(encodeURIComponent(value));
        if (encoded.length <= maxBytes) {
            return value;
        }

        // Cut only at a valid UTF-8 boundary. No ellipsis is added: it would
        // consume buffer space and become part of the game text.
        for (let length = maxBytes; length >= 0; length--) {
            try {
                return decodeURIComponent(escape(encoded.slice(0, length)));
            } catch (e) {
                // The cut landed in the middle of a multibyte character.
            }
        }
        return "";
    }

    function writeWalkthroughText(address, sourceText, replacement) {
        // This field is an inline game buffer. Its current string length is a
        // safe lower bound for the available capacity; fit longer translations
        // into that bound instead of overwriting adjacent memory.
        const capacityBytes = utf8ByteLength(sourceText);
        const safeReplacement = truncateUtf8(replacement, capacityBytes);
        if (!safeReplacement) {
            send({
                type: 'info',
                payload: `[${hookName}] Walkthrough replacement could not fit the source buffer; keeping pack text`
            });
            return null;
        }
        if (safeReplacement !== replacement) {
            send({
                type: 'info',
                payload: `[${hookName}] Walkthrough replacement was shortened to fit the game buffer`
            });
        }
        address.writeUtf8String(safeReplacement);
        return safeReplacement;
    }

    Interceptor.attach(calleeAddr, {
        onLeave: function(retval) {
            if (!this.returnAddress.equals(expectedReturnAddr)) {
                return;
            }
            try {
                // retval (eax) = object pointer; retval + 0xEC = text address
                const textAddress = retval.add(236);
                const originalText = textAddress.readUtf8String();

                if (!originalText || originalText.length === 0) {
                    return;
                }

                if (translatedValues.has(originalText)) {
                    return;
                }

                // check cache first
                if (translationCache.has(originalText)) {
                    const cachedReplacement = translationCache.get(originalText);
                    if (cachedReplacement && cachedReplacement !== originalText) {
                        const written = writeWalkthroughText(textAddress, originalText, cachedReplacement);
                        if (written) {
                            translatedValues.add(written);
                        }
                    }
                    return;
                }

                // send to Python for translation/lookup
                send({
                    type: 'get_replacement',
                    text: originalText
                });

                // block and wait for Python response
                var replacement = null;
                var op = recv('replacement', function(message) {
                    replacement = message.text;
                });
                op.wait();

                if (replacement !== null) {
                    // write replacement to memory if different
                    if (replacement !== originalText) {
                        const written = writeWalkthroughText(textAddress, originalText, replacement);
                        if (written) {
                            translationCache.set(originalText, replacement);
                            translatedValues.add(written);
                        } else {
                            // Do not retry an unsafe replacement every time the
                            // menu opens; the English pack text is the fallback.
                            translationCache.set(originalText, originalText);
                        }
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
