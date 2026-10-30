import { verifyGoogleToken } from "../.test/auth.mjs";
const enc = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
const { publicKey, privateKey } = await crypto.subtle.generateKey(
  { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const jwk = { ...(await crypto.subtle.exportKey("jwk", publicKey)), kid: "k1" };
const keys = async () => [jwk];
const sign = async (claims, kid = "k1") => {
  const head = enc({ alg: "RS256", kid }) + "." + enc(claims);
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", privateKey, new TextEncoder().encode(head));
  return head + "." + Buffer.from(sig).toString("base64url");
};
const now = Date.now();
const base = { iss: "https://accounts.google.com", aud: "cid", sub: "123", email: "a@ufl.edu", email_verified: true, exp: now / 1000 + 600 };
const cases = [
  ["valid", await sign(base), true],
  ["wrong aud", await sign({ ...base, aud: "other" }), false],
  ["expired", await sign({ ...base, exp: now / 1000 - 3600 }), false],
  ["bad iss", await sign({ ...base, iss: "evil.com" }), false],
  ["unverified email", await sign({ ...base, email_verified: false }), false],
  ["unknown kid", await sign(base, "k2"), false],
  ["tampered", (await sign(base)).replace(/\.([^.]+)\./, "." + enc({ ...base, sub: "999" }) + "."), false],
  ["garbage", "a.b.c", false],
];
let fail = 0;
for (const [name, tok, want] of cases) {
  const got = !!(await verifyGoogleToken(tok, "cid", keys, now));
  console.log(got === want ? "ok  " : "FAIL", name);
  if (got !== want) fail++;
}
process.exit(fail);
