// Run with: node scripts/tests/network-text.test.cjs
// Exercise the actual Frida script using isolated memory, never a game process.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../app/hooking/scripts/network_text.ts'), 'utf8');

function harness(chatEnabled = true, debugLogging = false) {
    const memory = Buffer.alloc(65536);
    const requests = [];
    const writes = [];
    const diagnostics = [];
    let callbacks;
    let reply;
    let beforeReply;
    let unboundedBodyRead = false;
    class Pointer {
        constructor(address) { this.address = address; }
        add(offset) { return new Pointer(this.address + offset); }
        sub(other) { return new Pointer(this.address - other.address); }
        toInt32() { return this.address; }
        isNull() { return this.address === 0; }
        toUInt32() { return this.address; }
        toString() { return `0x${this.address.toString(16)}`; }
        readU32() { return memory.readUInt32LE(this.address); }
        writeU32(value) { memory.writeUInt32LE(value, this.address); }
        readPointer() { return new Pointer(this.readU32()); }
        readByteArray(length) { return Uint8Array.from(memory.subarray(this.address, this.address + length)).buffer; }
        readUtf8String(length) {
            if (this.address === 0x2000 && length === undefined) unboundedBodyRead = true;
            const end = length === undefined ? memory.indexOf(0, this.address) : this.address + length;
            return new TextDecoder('utf-8', { fatal: true }).decode(memory.subarray(this.address, end));
        }
        writeUtf8String(text) {
            writes.push(text);
            put(this.address, text);
        }
    }
    function put(address, text) {
        const bytes = Buffer.from(text, 'utf8');
        bytes.copy(memory, address);
        memory[address + bytes.length] = 0;
        return bytes.length;
    }
    vm.runInNewContext(source
        .replaceAll('{{CHAT_HISTORY_ENABLED}}', String(chatEnabled))
        .replaceAll('{{DEBUG_LOGGING}}', String(debugLogging)), {
        Process: {
            enumerateModules: () => [{ base: new Pointer(0x4000), size: 100 }],
            findRangeByAddress: address => address.address > 0 && address.address < memory.length ?
                { base: new Pointer(0), size: memory.length, protection: 'rw-' } : null,
        },
        Memory: { scanSync: () => [{ address: new Pointer(0x4100) }] },
        Interceptor: { attach: (_address, handlers) => { callbacks = handlers; } },
        ptr: address => new Pointer(address),
        send: payload => {
            if (payload.type !== 'info') requests.push(payload);
            else if (payload.payload.startsWith('[chat-speaker-trace]')) diagnostics.push(payload.payload);
        },
        recv: (type, callback) => ({ wait() {
            assert.equal(type, requests.at(-1).response_type);
            beforeReply?.();
            callback({ text: reply });
        } }),
    });
    return {
        requests, writes, memory, diagnostics,
        get unboundedBodyRead() { return unboundedBodyRead; },
        render(text, category, replacement, mutate, malformed = false) {
            const length = put(0x2000, text);
            put(0x3000, category);
            memory.writeUInt32LE(length, 0x1010);
            memory.writeUInt32LE(0x2000 + length, 0x1018);
            memory.writeUInt32LE(0x3000, 0x101c);
            reply = replacement;
            beforeReply = mutate;
            const invocation = {};
            put(0x5000, 'private message body');
            put(0x6000, 'M_speaker');
            callbacks.onEnter.call(invocation, [new Pointer(0x1000), new Pointer(0x5000), new Pointer(20), new Pointer(0x6000)]);
            if (malformed) memory[0x2000] = 0xff;
            callbacks.onLeave.call(invocation, { toInt32: () => 1 });
        },
    };
}

const chatCategory = '<%sM_speaker> "<%sM_chat>"';
{
    const h = harness();
    for (const [opening, closing] of [['"', '"'], ['[', ']']]) {
        const category = `<%sM_speaker> ${opening}<%sM_chat>${closing}`;
        const original = `        ロマ ${opening}こんにちは！${closing}`;
        const replacement = `       \x04Roma ${opening}こんにちは！${closing}`;
        h.render(original, category, replacement);
        assert.equal(h.writes.at(-1), replacement, 'name-only replacement must retain the Japanese body');
        assert.equal(h.memory.readUInt32LE(0x1010), Buffer.byteLength(replacement));
        assert.equal(h.memory.readUInt32LE(0x1018), 0x2000 + Buffer.byteLength(replacement));
    }
}
{
    const h = harness(true, true);
    const text = '     \x04Kanapi [private stamp caption]';
    h.render(text, '<%sM_speaker> [<%sM_chat>]', text);
    assert.equal(h.diagnostics.length, 1);
    assert.ok(h.diagnostics[0].includes('"stage":"composed"'));
    assert.ok(!h.diagnostics[0].includes('private stamp caption'));
}
{
    const h = harness(true, true);
    for (let i = 0; i < 30; i++) {
        h.render(`Name${i}`, chatCategory, `Name${i}`);
        h.render(`Name${i} "private message body`, chatCategory, `Name${i} "private message body`);
    }
    assert.equal(h.diagnostics.length, 8, 'diagnostics must stop after four names per stage');
    assert.equal(h.writes.length, 0, 'diagnostic itself must never write memory');
    assert.ok(h.diagnostics.every(line => !line.includes('private message body')));
}
{
    const h = harness(true, false);
    h.render('Name', chatCategory, 'Name');
    assert.equal(h.diagnostics.length, 0, 'normal runs must not collect speaker diagnostics');
}
{
    const h = harness();
    for (let i = 0; i < 2; i++) {
        h.render('おぴよ', '<%sM_speaker>', '\x04Opiyo');
        assert.equal(h.memory.readUInt32LE(0x1010), 6, 'sender byte length must be updated, including cache hits');
        assert.equal(h.memory.readUInt32LE(0x1018), 0x2006, 'builder must append after the romanized sender');
    }
    assert.equal(h.requests.length, 1, 'sender romanization should use the local cache');
    assert.equal(h.writes.length, 2);
}
{
    const h = harness(false);
    h.render('おぴよ', '<%sM_speaker>', '\x04Opiyo');
    assert.equal(h.requests.length, 0, 'chat option must gate sender romanization');
    assert.equal(h.writes.length, 0);
}
{
    const h = harness();
    h.render('Rock "ありがとう', chatCategory, 'Rock "Thanks');
    h.render('Rock "こんにちは', chatCategory, 'Rock "Hello');
    assert.equal(h.writes.length, 2);
    assert.notEqual(h.requests[0].response_type, h.requests[1].response_type);
    assert.equal(h.memory.readUInt32LE(0x1010), Buffer.byteLength('Rock "Hello'));
    assert.equal(h.memory.readUInt32LE(0x1018), 0x2000 + Buffer.byteLength('Rock "Hello'));
}
{
    const h = harness();
    h.render('Rock "ありがとう', chatCategory, 'Rock "Thanks', () => {
        // Same address and same size, but the buffer now belongs to another UI value.
        h.memory[0x2000] = 88;
    });
    assert.equal(h.writes.length, 0, 'must not overwrite a reused buffer');
}
{
    const h = harness();
    h.render('Rock "ありがとう', chatCategory, 'Rock "Thanks', () => h.memory.writeUInt32LE(1, 0x1010));
    assert.equal(h.writes.length, 0, 'must not overwrite a changed builder');
}
{
    const h = harness();
    h.render('---------- Current Real Time 12:30 JST', '<%sW_DELIMITER>', 'bad');
    h.render('----------Current Time 12:30', 'some template', 'bad');
    assert.equal(h.requests.length, 0, 'separator must never reach translation');
    assert.equal(h.writes.length, 0);
}
{
    const h = harness();
    h.render('日本語', '<%sM_00>', 'ABC');
    h.render('日本語', '<%sM_00>', 'ABC');
    assert.equal(h.requests.length, 1, 'generic cache should still work');
    assert.equal(h.writes.length, 2);
}
{
    const h = harness();
    h.render('bad UTF-8', '<%sM_chat>', 'replacement', null, true);
    assert.equal(h.requests.length, 0);
    assert.equal(h.writes.length, 0);
    assert.equal(h.unboundedBodyRead, false, 'malformed input must not trigger an unbounded retry');
}
{
    const h = harness();
    h.memory[0x2002] = 0x5a;
    h.render('x', '<%sM_chat>', 'a much longer message');
    assert.equal(h.writes[0], 'a', 'write must respect the original byte bound');
    assert.equal(h.memory[0x2002], 0x5a, 'adjacent memory must remain untouched');
}
console.log('Network formatter script tests passed.');
