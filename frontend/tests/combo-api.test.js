/* eslint-env node */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../modules/api.js"), "utf8");
const plain = value => JSON.parse(JSON.stringify(value));
const data = { combos: [{ name: "中文🔧", path: ["same", "same"] }], truncated: true };
const progress = { type: "progress", slot: "枪托", frontier: 17, capped: true };
const stream = `: heartbeat\n\ndata: ${JSON.stringify(progress)}\n\ndata: ${JSON.stringify({ type: "result", data })}\n\n`;

function request(text, sizes = [3], options = {}) {
    const EFTForge = { config: { API_BASE: "" }, state: {} };
    const ctx = vm.createContext({ window: { EFTForge }, EFTForge, TextDecoder, DOMException });
    vm.runInContext(source, ctx);
    const bytes = Buffer.from(text);
    const controller = new AbortController();
    let offset = 0, reads = 0, cancels = 0, releases = 0;
    let posted;
    const events = [];
    ctx.fetch = async (url, init) => {
        posted = JSON.parse(init.body);
        assert.equal(init.signal, controller.signal);
        return {
            ok: options.status == null, status: options.status,
            headers: new Map([["content-type", options.json ? "application/json; charset=utf-8" : "text/event-stream"]]),
            async json() {
                if (options.abortJSON) controller.abort();
                return JSON.parse(text);
            },
            body: { getReader: () => ({
                async read() {
                    if (options.abortRead === reads) controller.abort();
                    if (options.failRead === reads) throw new TypeError("read failed");
                    if (offset === bytes.length) return { done: true };
                    const size = sizes[reads++ % sizes.length];
                    const value = bytes.subarray(offset, offset + size);
                    offset += value.length;
                    return { done: false, value };
                },
                async cancel() {
                    cancels++;
                    if (options.failCancel) throw new Error("cancel failed");
                },
                releaseLock() { releases++; },
            }) },
        };
    };
    if (options.preAbort) controller.abort();
    const promise = ctx.comboFull(options.payload ?? {}, controller.signal, event => {
        events.push(plain(event));
        if (options.abortProgress) controller.abort();
    });
    return { promise, events, counts: () => ({ cancels, releases }), posted: () => posted };
}

for (const sizes of [[1], [2], [3], [7], [65536], [1, 8, 2, 19]]) {
    for (const ending of ["\n", "\r\n", "\r"]) {
        test(`UTF-8, progress and delimiters: chunks ${sizes}, newline ${JSON.stringify(ending)}`, async () => {
            const run = request(stream.replaceAll("\n", ending), sizes);
            assert.deepEqual(plain(await run.promise), data);
            assert.deepEqual(run.events, [progress]);
            assert.deepEqual(run.counts(), { cancels: 1, releases: 1 });
            assert.equal(run.posted().response_format, "items-v1");
        });
    }
}

test("multiline SSE data, ignored fields and explicit legacy request", async () => {
    const run = request('event: message\nid: 1\ndata:{"type":"result",\ndata: "data":{"combos":[]}}\n\n', [2],
        { payload: { response_format: "legacy" } });
    assert.deepEqual(plain(await run.promise), { combos: [] });
    assert.equal(run.posted().response_format, "legacy");
});

test("one large result with many small reads", async () => {
    const large = { items: { item: { name: "长".repeat(200000) } }, combos: [], response_format: "items-v1" };
    const run = request(`data: ${JSON.stringify({ type: "result", data: large })}\n\n`, [127]);
    assert.deepEqual(plain(await run.promise), large);
});

for (const [name, text, options, error] of [
    ["EOF before delimiter", 'data: {"type":"result","data":{}}', {}, /ended without result/],
    ["EOF after progress", `data: ${JSON.stringify(progress)}\n\n`, {}, /ended without result/],
    ["server stream error", 'data: {"type":"error","message":"sample failure"}\n\n', {}, /sample failure/],
    ["malformed JSON", "data: broken\n\n", { failCancel: true }, { name: "SyntaxError" }],
    ["abort during read", stream, { abortRead: 2 }, { name: "AbortError" }],
    ["already aborted", stream, { preAbort: true }, { name: "AbortError" }],
    ["abort from progress in the same chunk", stream, { abortProgress: true }, { name: "AbortError" }],
    ["network error", stream, { failRead: 0, failCancel: true }, /read failed/],
]) {
    test(`${name} releases the reader and preserves the error`, async () => {
        const run = request(text, options.abortProgress ? [65536] : [3], options);
        await assert.rejects(run.promise, error);
        assert.deepEqual(run.counts(), { cancels: 1, releases: 1 });
    });
}

for (const response_format of [undefined, "items-v1"]) {
    test(`ordinary JSON empty response: ${response_format ?? "legacy"}`, async () => {
        const value = { base: {}, combos: [], response_format };
        const run = request(JSON.stringify(value), [3], { json: true });
        assert.deepEqual(plain(await run.promise), plain(value));
        assert.deepEqual(run.counts(), { cancels: 0, releases: 0 });
    });
}

test("JSON abort and HTTP failure do not return a result", async () => {
    await assert.rejects(request("{}", [3], { json: true, abortJSON: true }).promise, { name: "AbortError" });
    const run = request("", [3], { status: 422 });
    await assert.rejects(run.promise, /Server error: 422/);
    assert.deepEqual(run.counts(), { cancels: 0, releases: 0 });
});
