// PaperFlow transport only: official SIWC SDK, no Codex executable or agent loop.
import { createInterface } from 'node:readline';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const { createChatGPT } = await import('../.local/siwc-devkit/packages/local/dist/index.js');
let key;
function encryptionKey() {
  if (key) return key;
  const args = ['-s', 'PaperFlow.ChatGPT', '-a', 'paperflow'];
  let result = spawnSync('/usr/bin/security', ['find-generic-password', ...args, '-w'], {encoding:'utf8'});
  if (result.status === 44) {
    const candidate = randomBytes(32).toString('base64');
    const saved = spawnSync('/usr/bin/security', ['add-generic-password', ...args, '-w', candidate], {encoding:'utf8'});
    // Another local process may have created it concurrently. Read the stored value.
    result = spawnSync('/usr/bin/security', ['find-generic-password', ...args, '-w'], {encoding:'utf8'});
    if (saved.status !== 0 && result.status !== 0) throw new Error('Cannot save the PaperFlow encryption key in macOS Keychain.');
  }
  if (result.status !== 0) throw new Error('Allow PaperFlow to access its own macOS Keychain item, then retry.');
  key = Buffer.from(result.stdout.trim(), 'base64');
  if (key.length !== 32) throw new Error('PaperFlow Keychain encryption key has an invalid format.');
  return key;
}
const storageDir = resolve(root, 'data/chatgpt-auth');
mkdirSync(storageDir, {recursive:true, mode:0o700});
let loginUrl = null;
let loginError = null;
let loginPending = false;
const client = createChatGPT({
  appName:'PaperFlow', appId:'paperflow', redirectPort:0,
  storageDir, sendHostId:true,
  credentialEncryption:{
    id:'paperflow-macos-keychain-aes256gcm-v1',
    isAvailable:()=>process.platform === 'darwin',
    encrypt(text) {
      const iv = randomBytes(12);
      const cipher = createCipheriv('aes-256-gcm', encryptionKey(), iv);
      const encrypted = Buffer.concat([cipher.update(text, 'utf8'), cipher.final()]);
      return Buffer.concat([iv, cipher.getAuthTag(), encrypted]);
    },
    decrypt(raw) {
      const data = Buffer.from(raw);
      const cipher = createDecipheriv('aes-256-gcm', encryptionKey(), data.subarray(0,12));
      cipher.setAuthTag(data.subarray(12,28));
      return Buffer.concat([cipher.update(data.subarray(28)), cipher.final()]).toString('utf8');
    },
  },
  openBrowser(url) { loginUrl = url; },
});
function safeError(error) {
  // Only SDK user-facing error messages. Never print SDK objects or credentials.
  return {code:error?.code || 'bridge_error', message:error?.message || 'ChatGPT connection failed.'};
}
async function status() {
  return {session:await client.getSession(), profiles:await client.listProfiles(),
    loginPending, loginUrl:loginPending ? loginUrl : null, loginError};
}
async function run(op, args={}) {
  switch(op) {
    case 'status': return status();
    case 'login': {
      if (loginPending) return status();
      loginUrl=null; loginError=null; loginPending=true;
      client.signIn({newProfile:!!args.newProfile}).catch(e=>{loginError=safeError(e);})
        .finally(()=>{loginPending=false; loginUrl=null;});
      return status();
    }
    case 'cancel': client.cancelSignIn(); return status();
    case 'select': await client.selectProfile(args.id); return status();
    case 'logout': await client.disconnect(); return status();
    case 'models': return {models:await client.listModels()};
    case 'generate': {
      let model=args.model;
      if (!model || model === 'auto') {
        const models=await client.listModels();
        model=models[0]?.slug;
        if (!model) throw new Error('No model is available for this ChatGPT account.');
      }
      const result=await client.streamResponse({model, input:args.prompt,
        instructions:args.system || undefined, signal:AbortSignal.timeout(180000)});
      if (!result.text.trim()) throw new Error('The completed response contained no text.');
      return {text:result.text, model};
    }
    default: throw new Error('Unknown bridge operation.');
  }
}
const input=createInterface({input:process.stdin});
input.on('line', line=>{
  let req;
  try {req=JSON.parse(line);} catch {return;}
  run(req.op,req.args).then(result=>process.stdout.write(JSON.stringify({id:req.id,result})+'\n'))
    .catch(error=>process.stdout.write(JSON.stringify({id:req.id,error:safeError(error)})+'\n'));
});
input.on('close',()=>{client.cancelSignIn(); process.exit(0);});
