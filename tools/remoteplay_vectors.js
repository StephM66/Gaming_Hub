// Reference vectors for the PS5 Remote Play port (tests/fixtures/remoteplay_vectors.json).
// Run from an empty folder: npm install playactor@0.4.1 && node remoteplay_vectors.js
// The fixture adds an "inputs" block mirroring the constants below.
const base = require("playactor/dist/remoteplay/crypto/base");
const modern = require("playactor/dist/remoteplay/crypto/modern");
const { RemotePlayCrypto } = require("playactor/dist/remoteplay/crypto");
const { RemotePlayPacketCodec } = require("playactor/dist/remoteplay/codec");
const { RemotePlayOutgoingPacket } = require("playactor/dist/remoteplay/packets");
const { registKeyToCredential, extractAccountId } = require("playactor/dist/credentials/oauth/requester");
const { formatDiscoveryMessage } = require("playactor/dist/protocol");
const crypto = require("crypto");
const device = { type: "PS5", systemVersion: "0", address: { address: "1.2.3.4" } };
const clientNonce = Buffer.from("000102030405060708090a0b0c0d0e0f", "hex");
const serverNonce = Buffer.from("f0e1d2c3b4a5968778695a4b3c2d1e0f", "hex");
const rpKey = "00112233445566778899aabbccddeeff";
const registKey = "3132333461626364"; // ascii "1234abcd"
const out = {};
out.iv0 = base.generateIv(3, clientNonce, 0n).toString("hex");
out.iv5 = base.generateIv(3, serverNonce, 5n).toString("hex");
out.pin_seed = modern.generateSeed("PS5", 12345678, 1).toString("hex");
out.auth_nonce = modern.transformServerNonceForAuth("PS5", serverNonce).toString("hex");
out.auth_seed = modern.generateAuthSeed("PS5", Buffer.from(rpKey, "hex"), serverNonce).toString("hex");
// registration payload with a fixed client nonce
const rc = RemotePlayCrypto.forDeviceAndPin(device, "12345678", clientNonce);
const body = rc.createSignedPayload({ "Client-Type": "dabfa2ec873de5839bee8d3f4c0239c4282c07c25c6077a2931afcf0adc0d34f", "Np-AccountId": "AQIDBAUGBwg=" });
out.regist_body = body.toString("hex");
const respPlain = Buffer.from("AP-Ssid: x\r\nPS5-RegistKey: 3132333461626364\r\nRP-Key: 00112233445566778899aabbccddeeff\r\nPS5-Nickname: PS5-123\r\n");
// what the console would send back: same key/iv, fresh stream
const ctx = modern.generateSeed("PS5", 12345678, 1);
const enc = crypto.createCipheriv("aes-128-cfb", ctx, base.generateIv(3, clientNonce, 0n));
out.regist_response_plain = respPlain.toString("hex");
out.regist_response = enc.update(respPlain).toString("hex");
// control channel header encryption sequence
const creds = { registration: { "PS5-RegistKey": registKey, "RP-Key": rpKey } };
const codec = new RemotePlayPacketCodec(new modern.ModernCryptoStrategy("PS5", 3), creds, serverNonce);
const pad = (b) => Buffer.concat([b, Buffer.alloc(16 - b.length)]);
const did = Buffer.concat([Buffer.from([0x00,0x18,0x00,0x00,0x00,0x07,0x00,0x40,0x00,0x80]), Buffer.alloc(16), Buffer.alloc(6)]);
out.rp_auth = codec.encodeBuffer(pad(Buffer.from(registKey, "hex"))).toString("base64");
out.rp_did = codec.encodeBuffer(did).toString("base64");
out.rp_ostype = codec.encodeBuffer(Buffer.from("Win10.0.0")).toString("base64");
const sb = Buffer.alloc(4); out.rp_startbitrate = codec.encodeBuffer(sb).toString("base64");
const st = Buffer.alloc(4); st.writeInt32LE(1); out.rp_streamingtype = codec.encodeBuffer(st).toString("base64");
out.passcode_packet = codec.encode(new RemotePlayOutgoingPacket(0x8004, Buffer.from("1234")).toBuffer()).toString("hex");
out.standby_packet = codec.encode(new RemotePlayOutgoingPacket(80).toBuffer()).toString("hex");
out.credential = registKeyToCredential(registKey);
out.account_b64 = extractAccountId({ user_id: "1234567890123456789" });
out.wake = formatDiscoveryMessage({ type: "WAKEUP", version: "00030010", data: { "app-type": "r", "auth-type": "R", "client-type": "vr", model: "w", "user-credential": "305441741", accountId: "x" } }).toString();
out.srch = formatDiscoveryMessage({ type: "SRCH", version: "00030010" }).toString();
console.log(JSON.stringify(out, null, 2));
